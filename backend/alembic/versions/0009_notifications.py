"""Add notification rules, incident lifecycle, deduplicated occurrences and deliveries."""
from alembic import op
revision='0009'
down_revision='0008'
branch_labels=None
depends_on=None
def upgrade():
    from app.models import NotificationRule,Incident,IncidentOccurrence,IncidentHistory,NotificationDelivery
    for model in (NotificationRule,Incident,IncidentOccurrence,IncidentHistory,NotificationDelivery):model.__table__.create(op.get_bind(),checkfirst=True)
def downgrade():
    for name in ('notification_deliveries','incident_history','incident_occurrences','incidents','notification_rules'):op.drop_table(name)
