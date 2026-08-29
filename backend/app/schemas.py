from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


class ImportRequest(BaseModel):
    dataset_name: str = Field(min_length=1, max_length=180)
    csv_content: str = Field(min_length=1, max_length=5_000_000)
    signature: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class DecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=500)
    expected_status: Literal["pending"] = "pending"


class AttackRequest(BaseModel):
    attack_type: Literal["demand_poisoning", "inventory_manipulation", "supplier_spoofing"]
    sku: str = "SKU-001"

