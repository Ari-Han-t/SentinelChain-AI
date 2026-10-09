"""Scope nodes to supply chains, add auditor verification columns.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

from app.database import ensure_schema

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_schema(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    for statement in (
        'DROP INDEX IF EXISTS uq_supply_chain_node_key',
        'DROP INDEX IF EXISTS ix_supply_chain_nodes_chain_id',
        'ALTER TABLE supply_chain_nodes DROP COLUMN verified_by',
        'ALTER TABLE supply_chain_nodes DROP COLUMN verified_at',
        'ALTER TABLE supply_chain_nodes DROP COLUMN chain_id',
        'DROP TABLE IF EXISTS supply_chains',
    ):
        try:
            bind.exec_driver_sql(statement)
        except Exception:  # noqa: BLE001 - best-effort downgrade across dialects
            pass
