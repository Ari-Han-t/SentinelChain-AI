"""Normalized pull adapters; only deployment-owned profiles can perform HTTP."""
from __future__ import annotations
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import ipaddress
import json
import os
import socket
import time
from typing import Protocol
from urllib.parse import urlsplit
import httpx
from pydantic import ValidationError
from ..config import settings
from .schemas import Page, Profile, RESOURCES


class AdapterFailure(Exception):
    def __init__(self, code, detail, *, attempts=0, retry_after=None):
        self.code, self.detail, self.attempts, self.retry_after = code, detail, attempts, retry_after
        super().__init__(detail)


class Adapter(Protocol):
    attempts: int
    def check(self) -> None: ...
    def pull(self, cursor: str | None) -> Page: ...


def profiles() -> dict[str, Profile]:
    try:
        raw = json.loads(settings.integration_profiles_json)
        if not isinstance(raw, dict) or len(raw) > 50:
            raise ValueError("Invalid profile registry")
        result = {name: Profile.model_validate(value) for name, value in raw.items()}
        for name, profile in result.items():
            if not isinstance(name, str) or not 1 <= len(name) <= 80:
                raise ValueError("Invalid profile name")
            parsed = urlsplit(profile.base_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("Profiles require credential-free HTTPS origins or base paths")
        return result
    except (ValueError, TypeError, ValidationError) as exc:
        raise AdapterFailure("configuration", "Integration profile configuration is invalid") from exc


def validate_destination(url):
    parsed = urlsplit(url)
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
            raise ValueError("Nonpublic destination")
    except (OSError, ValueError) as exc:
        raise AdapterFailure("destination", "Integration destination is unavailable or not public") from exc


def retry_delay(value: str | None) -> int:
    if value is None: return 5
    try:
        return max(0, min(3600, int(value)))
    except ValueError:
        try:
            return max(0, min(3600, int((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())))
        except (ValueError, TypeError, OverflowError):
            return 5


class HTTPAdapter:
    system = ""
    path = ""
    def __init__(self, profile: Profile, *, transport=None, sleep=time.sleep):
        self.profile, self.transport, self.sleep, self.attempts = profile, transport, sleep, 0

    def _request(self, suffix, cursor=None):
        token = os.environ.get(self.profile.token_env)
        if not token:
            raise AdapterFailure("credentials", "Backend integration credential is not configured")
        url = self.profile.base_url.rstrip("/") + suffix
        for attempt in range(1, self.profile.max_attempts + 1):
            self.attempts = attempt
            validate_destination(url)
            retry = None
            try:
                with httpx.Client(timeout=self.profile.timeout_seconds, follow_redirects=False, trust_env=False, transport=self.transport) as client:
                    with client.stream("GET", url, headers={"Authorization":f"Bearer {token}", "Accept":"application/json"}, params={"cursor":cursor} if cursor else None) as response:
                        if response.status_code == 429:
                            delay = retry_delay(response.headers.get("Retry-After"))
                            if delay > 5 or attempt == self.profile.max_attempts:
                                raise AdapterFailure("rate_limited", "Partner rate limit reached; retry after the cooldown", attempts=attempt, retry_after=delay)
                            retry = delay
                        elif response.status_code in (408, 500, 502, 503, 504):
                            retry = 2 ** (attempt - 1)
                        elif response.status_code in (401, 403):
                            raise AdapterFailure("authentication", "Partner rejected the integration credential", attempts=attempt)
                        elif response.status_code != 200:
                            raise AdapterFailure("http_status", "Partner returned an unsupported response status", attempts=attempt)
                        else:
                            chunks, size = [], 0
                            for chunk in response.iter_bytes():
                                size += len(chunk)
                                if size > 1048576:
                                    raise AdapterFailure("response_size", "Partner response exceeds the 1 MiB limit", attempts=attempt)
                                chunks.append(chunk)
                            try:
                                return json.loads(b"".join(chunks))
                            except (ValueError, UnicodeDecodeError) as exc:
                                raise AdapterFailure("invalid_response", "Partner response is not valid JSON", attempts=attempt) from exc
            except (httpx.TimeoutException, httpx.NetworkError):
                retry = 2 ** (attempt - 1)
            except httpx.HTTPError as exc:
                raise AdapterFailure("transport", "Partner transport request failed", attempts=attempt) from exc
            if attempt == self.profile.max_attempts:
                raise AdapterFailure("transient", "Partner remains unavailable after bounded retries", attempts=attempt)
            if retry is not None:
                self.sleep(retry)
        raise AdapterFailure("transport", "Partner request did not complete", attempts=self.attempts)

    def check(self):
        data = self._request("/health")
        if not isinstance(data, dict) or data.get("status") != "ok":
            raise AdapterFailure("invalid_response", "Partner health response does not confirm availability", attempts=self.attempts)

    def pull(self, cursor):
        try:
            page = Page.model_validate(self._request(self.path, cursor))
            if any(record.resource not in RESOURCES[self.system] for record in page.records):
                raise ValueError("Wrong adapter resource")
            if cursor is not None and page.next_cursor == cursor:
                raise ValueError("Cursor did not advance")
            return page
        except (ValidationError, ValueError) as exc:
            raise AdapterFailure("validation", "Partner records failed the normalized adapter contract", attempts=self.attempts) from exc


class ERPAdapter(HTTPAdapter):
    system, path = "erp", "/erp/changes"


class InventoryAdapter(HTTPAdapter):
    system, path = "inventory", "/inventory/changes"


class SupplierAdapter(HTTPAdapter):
    system, path = "supplier", "/supplier/changes"


class LogisticsAdapter(HTTPAdapter):
    system, path = "logistics", "/logistics/changes"


class MockAdapter:
    def __init__(self, system, scenario="healthy"):
        self.system, self.scenario, self.attempts = system, scenario, 0

    def check(self):
        self.attempts = 1
        if self.scenario == "rate_limited":
            raise AdapterFailure("rate_limited", "Synthetic partner rate limit; no live request occurred", attempts=1, retry_after=60)
        if self.scenario == "invalid":
            raise AdapterFailure("validation", "Synthetic invalid partner response; no live request occurred", attempts=1)
        self.attempts = 2 if self.scenario == "transient" else 1

    def pull(self, cursor):
        self.check()
        # Stable fixtures deliberately remain in the mock-only inbox.
        supplier = {"name":"Mock Components", "reliability":.96, "average_lead_time":7, "defect_rate":.01, "price_variance":.04, "compliance_status":"pending", "identity_status":"unverified"}
        fixtures = {
            "erp": [("suppliers","mock-supplier",supplier), ("products","mock-product",{"sku":"MOCK-SKU-001","name":"Mock sensor","current_stock":40,"unit_cost":20}), ("purchase-orders","mock-order",{"order_number":"MOCK-PO-001","supplier_external_id":"mock-supplier","lines":[{"sku":"MOCK-SKU-001","quantity":20,"unit_cost":20}]})],
            "supplier": [("suppliers","mock-supplier",supplier)],
            "inventory": [("warehouses","mock-warehouse",{"code":"MOCK-WH-001","name":"Mock warehouse","location":"Synthetic test site"}), ("inventory","mock-lot",{"sku":"MOCK-SKU-001","lot_number":"MOCK-LOT-001","quantity":40,"location":"Synthetic test site","warehouse_external_id":"mock-warehouse"}), ("stock-movements","mock-movement",{"lot_external_id":"mock-lot","movement_type":"receipt","quantity":5,"reason":"Synthetic stock receipt"})],
            "logistics": [("shipments","mock-shipment",{"shipment_number":"MOCK-SHIP-001","purchase_order_external_id":"mock-order","carrier":"Mock carrier","tracking_number":"MOCK-TRACK-001","reported_status":"in_transit","estimated_arrival":"2026-10-12T10:00:00Z"}), ("tracking-events","mock-tracking",{"shipment_external_id":"mock-shipment","status":"in_transit","location":"Synthetic transit hub","notes":"Synthetic checkpoint"})],
        }
        return Page(records=[{"event_id":f"{external_id}-v1", "external_id":external_id, "resource":resource, "source_version":1, "occurred_at":"2026-10-11T00:00:00Z", "data":data} for resource, external_id, data in fixtures[self.system]], next_cursor=None)


ADAPTERS = {"erp":ERPAdapter, "inventory":InventoryAdapter, "supplier":SupplierAdapter, "logistics":LogisticsAdapter}


def adapter_for(connection):
    if connection.mode == "mock":
        if settings.environment.lower() == "production":
            raise AdapterFailure("mock_disabled", "Mock adapters are disabled in production")
        return MockAdapter(connection.system, connection.mock_scenario)
    profile = profiles().get(connection.profile)
    if profile is None or profile.system != connection.system:
        raise AdapterFailure("configuration", "Matching backend integration profile is unavailable")
    return ADAPTERS[connection.system](profile)
