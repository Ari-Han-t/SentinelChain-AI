from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Role, SupplyChainNode, User
from .security import ROLE_PERMISSIONS, permissions_for


@dataclass(frozen=True)
class PolicyItem:
    name: str
    quantity: int
    access: str


@dataclass(frozen=True)
class PolicyAction:
    key: str
    label: str
    permission: str
    minimum_clearance: int


CLEARANCE_LEVELS: dict[str, int] = {
    Role.AUDITOR.value: 1,
    Role.ANALYST.value: 2,
    Role.MANAGER.value: 3,
    Role.ADMIN.value: 4,
}

ROLE_LABELS = {
    Role.ADMIN.value: "Administrator",
    Role.ANALYST.value: "Inventory analyst",
    Role.MANAGER.value: "Procurement manager",
    Role.AUDITOR.value: "Auditor",
}

POLICY_ACTIONS: tuple[PolicyAction, ...] = (
    PolicyAction("view_step", "View step and evidence", "audit.read", 1),
    PolicyAction("submit_evidence", "Submit operational evidence", "evidence.submit", 2),
    PolicyAction("refresh_guidance", "Refresh deterministic guidance", "guidance.refresh", 1),
    PolicyAction("generate_forecast", "Generate forecast", "forecast.manage", 2),
    PolicyAction("generate_recommendation", "Generate recommendation", "recommendation.generate", 2),
    PolicyAction("escalate_action", "Escalate an action", "action.escalate", 3),
    PolicyAction("decide_action", "Approve or reject an action", "action.decide", 3),
    PolicyAction("verify_step", "Verify the step", "node.verify", 1),
    PolicyAction("manage_step", "Create, edit, or deactivate the step", "node.manage", 4),
)

ITEMS_BY_STAGE: dict[str, tuple[PolicyItem, ...]] = {
    "demand": (
        PolicyItem("Signed sales records", 1, "analyst,administrator,auditor"),
        PolicyItem("Forecast dataset", 1, "analyst,administrator,auditor"),
    ),
    "supplier": (
        PolicyItem("Supplier profile", 1, "analyst,manager,administrator,auditor"),
        PolicyItem("Encrypted supplier contact", 1, "administrator"),
    ),
    "procurement": (
        PolicyItem("Purchase order", 1, "manager,administrator,auditor"),
        PolicyItem("Approved recommendation", 1, "manager,administrator,auditor"),
    ),
    "production": (
        PolicyItem("Inventory lot", 1, "analyst,manager,administrator,auditor"),
        PolicyItem("Stock movement record", 1, "analyst,manager,administrator,auditor"),
    ),
    "logistics": (
        PolicyItem("Shipment record", 1, "analyst,manager,administrator,auditor"),
        PolicyItem("Tracking event", 1, "analyst,manager,administrator,auditor"),
    ),
    "quality": (
        PolicyItem("Quality inspection", 1, "analyst,manager,administrator,auditor"),
        PolicyItem("Quarantine decision", 1, "manager,administrator,auditor"),
    ),
    "customer": (
        PolicyItem("Delivery confirmation", 1, "analyst,manager,administrator,auditor"),
        PolicyItem("Customer exception", 1, "manager,administrator,auditor"),
    ),
    "process": (
        PolicyItem("Process evidence", 1, "analyst,manager,administrator,auditor"),
        PolicyItem("Control record", 1, "administrator,auditor"),
    ),
}


def _stage_items(stage_type: str) -> tuple[PolicyItem, ...]:
    return ITEMS_BY_STAGE.get(stage_type, ITEMS_BY_STAGE["process"])


def _action_json(action: PolicyAction, role: str) -> dict[str, Any]:
    allowed = (
        CLEARANCE_LEVELS.get(role, 0) >= action.minimum_clearance
        and action.permission in ROLE_PERMISSIONS.get(role, frozenset())
    )
    return {
        "key": action.key,
        "label": action.label,
        "permission": action.permission,
        "minimum_clearance": action.minimum_clearance,
        "allowed": allowed,
    }


def clearance_matrix() -> dict[str, Any]:
    return {
        "clearance_levels": [
            {
                "role": role,
                "label": ROLE_LABELS[role],
                "level": level,
                "permissions": permissions_for(role),
                "actions": [_action_json(action, role) for action in POLICY_ACTIONS],
            }
            for role, level in sorted(CLEARANCE_LEVELS.items(), key=lambda item: item[1], reverse=True)
        ],
        "items_by_stage": {
            stage: [
                {"name": item.name, "quantity": item.quantity, "access": item.access.split(",")}
                for item in items
            ]
            for stage, items in sorted(ITEMS_BY_STAGE.items())
        },
    }


def step_spec(node: SupplyChainNode, users: list[User]) -> dict[str, Any]:
    people = []
    involved_roles = {node.owner_role, Role.ADMIN.value, Role.AUDITOR.value}
    for user in sorted(users, key=lambda item: (CLEARANCE_LEVELS.get(item.role, 0), item.id), reverse=True):
        if user.role in involved_roles:
            people.append(
                {
                    "id": user.id,
                    "display_name": user.display_name,
                    "role": user.role,
                    "clearance_level": CLEARANCE_LEVELS.get(user.role, 0),
                    "permissions": permissions_for(user.role),
                }
            )

    actions = [
        {
            **_action_json(action, role),
            "role": role,
            "role_label": ROLE_LABELS[role],
        }
        for role in sorted(CLEARANCE_LEVELS, key=CLEARANCE_LEVELS.get, reverse=True)
        for action in POLICY_ACTIONS
    ]
    return {
        "name": node.name,
        "key": node.key,
        "stage_type": node.stage_type,
        "entities": {
            "people": people,
            "items": [
                {"name": item.name, "quantity": item.quantity, "access": item.access.split(",")}
                for item in _stage_items(node.stage_type)
            ],
        },
        "actions": actions,
        "security": {
            "policy_source": "server-owned clearance policy",
            "metadata_can_describe": False,
            "authorization_enforced_by": "backend route guards and permission matrix",
        },
    }
