"""Add integration connections, runs, encrypted inbox, and replay protection."""
from alembic import op
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    from app.models import IntegrationConnection, IntegrationRun, IntegrationRecord, IntegrationEvent
    for model in (IntegrationConnection, IntegrationRun, IntegrationRecord, IntegrationEvent):
        model.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    for name in ("integration_events", "integration_records", "integration_runs", "integration_connections"):
        op.drop_table(name)
