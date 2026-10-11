"""Add warehouses and governance for existing operational entities."""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    # Older revisions call current metadata.create_all; support that path too.
    from app.models import Warehouse, EntityGovernance
    Warehouse.__table__.create(op.get_bind(), checkfirst=True)
    EntityGovernance.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    op.drop_table("entity_governance")
    op.drop_table("warehouses")
