"""Add dynamic supply-chain context, evidence, guidance, and actions.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

from app.database import Base
from app import models  # noqa: F401

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    for name in (
        "action_proposals",
        "guidance_runs",
        "evidence_records",
        "supply_chain_edges",
        "supply_chain_nodes",
        "user_contexts",
        "organization_profiles",
    ):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
