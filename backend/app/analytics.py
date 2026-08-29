from __future__ import annotations

import io
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, IsolationForest
from sklearn.metrics import mean_absolute_error, mean_squared_error

FEATURES = ["lag_1", "lag_7", "rolling_7", "day_of_week", "month"]


class DatasetError(ValueError):
    pass


@dataclass
class DatasetAnalysis:
    frame: pd.DataFrame
    accepted_indices: list[int]
    quarantined: list[dict]


def parse_sales_csv(content: str) -> pd.DataFrame:
    try:
        frame = pd.read_csv(io.StringIO(content))
    except Exception as exc:
        raise DatasetError("CSV could not be parsed") from exc
    required = {"sku", "date", "quantity"}
    missing = required - set(frame.columns)
    if missing:
        raise DatasetError(f"Missing required columns: {', '.join(sorted(missing))}")
    if frame.empty:
        raise DatasetError("Dataset contains no records")
    frame = frame[["sku", "date", "quantity"]].copy()
    frame["sku"] = frame["sku"].astype(str).str.strip()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["quantity"] = pd.to_numeric(frame["quantity"], errors="coerce")
    if frame[["sku", "date", "quantity"]].isna().any().any() or (frame["sku"] == "").any():
        raise DatasetError("Every row requires a valid sku, ISO date, and numeric quantity")
    if frame.duplicated(subset=["sku", "date"]).any():
        raise DatasetError("Duplicate sku/date records are not allowed")
    return frame


def analyze_sales(frame: pd.DataFrame) -> DatasetAnalysis:
    reasons: dict[int, list[str]] = {}
    median = max(float(frame["quantity"].median()), 1.0)
    for index, row in frame.iterrows():
        row_reasons: list[str] = []
        if row["quantity"] < 0:
            row_reasons.append("negative demand violates business rules")
        if row["quantity"] > max(5000, median * 8):
            row_reasons.append("demand spike exceeds eight times the dataset median")
        if row["date"] > pd.Timestamp.utcnow().tz_localize(None) + pd.Timedelta(days=1):
            row_reasons.append("future-dated sale")
        if row_reasons:
            reasons[int(index)] = row_reasons

    if len(frame) >= 16 and frame["quantity"].nunique() > 3:
        values = frame[["quantity"]].to_numpy(dtype=float)
        detector = IsolationForest(n_estimators=100, contamination="auto", random_state=42).fit(values)
        flags = detector.predict(values)
        scores = detector.decision_function(values)
        threshold = min(float(np.quantile(scores, 0.03)), -0.08)
        for index, flag, score in zip(frame.index, flags, scores, strict=True):
            if flag == -1 and score <= threshold:
                reasons.setdefault(int(index), []).append("Isolation Forest marked the quantity as anomalous")

    quarantined = [
        {
            "row_number": index + 2,
            "record": {
                "sku": str(frame.loc[index, "sku"]),
                "date": frame.loc[index, "date"].date().isoformat(),
                "quantity": float(frame.loc[index, "quantity"]),
            },
            "reason": "; ".join(items),
        }
        for index, items in sorted(reasons.items())
    ]
    return DatasetAnalysis(frame, [int(i) for i in frame.index if int(i) not in reasons], quarantined)


def _feature_frame(sales: pd.DataFrame) -> pd.DataFrame:
    frame = sales.sort_values("date").copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["lag_1"] = frame["quantity"].shift(1)
    frame["lag_7"] = frame["quantity"].shift(7)
    frame["rolling_7"] = frame["quantity"].shift(1).rolling(7).mean()
    frame["day_of_week"] = frame["date"].dt.dayofweek
    frame["month"] = frame["date"].dt.month
    return frame.dropna().reset_index(drop=True)


def train_forecast(sales: pd.DataFrame) -> dict:
    frame = _feature_frame(sales)
    if len(frame) < 20:
        raise DatasetError("At least 27 daily sales records are required for forecasting")
    split = max(int(len(frame) * 0.8), 1)
    if split >= len(frame):
        split = len(frame) - 1
    x_train, x_test = frame.loc[: split - 1, FEATURES], frame.loc[split:, FEATURES]
    y_train, y_test = frame.loc[: split - 1, "quantity"], frame.loc[split:, "quantity"]

    try:
        from xgboost import XGBRegressor

        model = XGBRegressor(
            n_estimators=120,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="reg:squarederror",
            random_state=42,
        )
        model_name = "XGBoost"
    except ImportError:
        model = GradientBoostingRegressor(random_state=42)
        model_name = "GradientBoosting fallback"
    model.fit(x_train, y_train)
    predictions = np.maximum(model.predict(x_test), 0)
    baseline = np.full(len(y_test), float(y_train.tail(7).mean()))
    nonzero = y_test.to_numpy() != 0
    mape = float(np.mean(np.abs((y_test.to_numpy()[nonzero] - predictions[nonzero]) / y_test.to_numpy()[nonzero])) * 100) if nonzero.any() else 0.0

    if hasattr(model, "feature_importances_"):
        importance = dict(zip(FEATURES, [float(value) for value in model.feature_importances_], strict=True))
    else:
        importance = {name: 0.0 for name in FEATURES}
    explanations = sorted(importance.items(), key=lambda item: item[1], reverse=True)

    latest = frame.iloc[-1][FEATURES].to_frame().T.astype(float)
    next_daily = max(float(model.predict(latest)[0]), 0.0)
    return {
        "daily_demand": round(next_daily, 2),
        "mae": round(float(mean_absolute_error(y_test, predictions)), 3),
        "rmse": round(float(math.sqrt(mean_squared_error(y_test, predictions))), 3),
        "mape": round(mape, 3),
        "baseline_mae": round(float(mean_absolute_error(y_test, baseline)), 3),
        "model_name": model_name,
        "explanation": [{"feature": name, "importance": round(value, 4)} for name, value in explanations],
    }


def inventory_policy(
    daily_demand: float,
    demand_stddev: float,
    lead_time_days: int,
    annual_demand: float,
    order_cost: float,
    unit_cost: float,
    holding_cost_rate: float,
    current_stock: int,
    service_z: float = 1.65,
) -> dict:
    safety_stock = service_z * demand_stddev * math.sqrt(max(lead_time_days, 1))
    reorder_point = daily_demand * lead_time_days + safety_stock
    annual_holding_cost = max(unit_cost * holding_cost_rate, 0.01)
    eoq = math.sqrt(max(2 * annual_demand * order_cost / annual_holding_cost, 0))
    recommended = max(0, math.ceil(max(eoq, reorder_point - current_stock))) if current_stock <= reorder_point else 0
    return {
        "safety_stock": round(safety_stock, 2),
        "reorder_point": round(reorder_point, 2),
        "eoq": round(eoq, 2),
        "recommended_quantity": recommended,
    }


def supplier_risk(reliability: float, lead_time: float, defect_rate: float, price_variance: float) -> float:
    reliability_risk = 1 - min(max(reliability, 0), 1)
    lead_time_risk = min(max((lead_time - 3) / 27, 0), 1)
    defect_risk = min(max(defect_rate / 0.1, 0), 1)
    price_risk = min(max(price_variance / 0.25, 0), 1)
    return round(100 * (0.4 * reliability_risk + 0.25 * lead_time_risk + 0.2 * defect_risk + 0.15 * price_risk), 1)
