"""Versioned server-side policy configuration."""
from alembic import op
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    from app.models import PolicyRevision, PolicyState
    PolicyRevision.__table__.create(op.get_bind(), checkfirst=True)
    PolicyState.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    op.drop_table("policy_state")
    op.drop_table("policy_revisions")
