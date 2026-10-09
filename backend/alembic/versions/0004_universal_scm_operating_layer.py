"""Add the reusable universal SCM operating layer.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

from app.database import ensure_schema

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Model metadata is intentionally the source of truth for both supported
    # dialects; create_all is idempotent and preserves existing installations.
    ensure_schema(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        "control_tower_exceptions", "documents", "risks", "quality_inspections",
        "tracking_events", "shipments", "purchase_order_lines", "purchase_orders",
        "stock_movements", "inventory_lots", "operational_tasks",
        "workflow_executions", "workflows", "node_templates",
    ):
        bind.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
