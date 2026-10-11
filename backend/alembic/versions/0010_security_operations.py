"""Security simulations, audit search indexes and PostgreSQL append-only audit guard."""
from alembic import op
from sqlalchemy import Index
from app.models import SecuritySimulation, AuditEvent
revision='0010'
down_revision='0009'
branch_labels=None
depends_on=None

def upgrade():
    bind=op.get_bind()
    SecuritySimulation.__table__.create(bind,checkfirst=True)
    for name,columns in [('ix_audit_created_actor',['created_at','actor_id']),('ix_audit_action_created',['event_type','created_at'])]:
        Index(name,*(AuditEvent.__table__.c[c] for c in columns)).create(bind,checkfirst=True)
    if bind.dialect.name=='postgresql':
        op.execute("""CREATE OR REPLACE FUNCTION sentinel_audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Audit records are append-only'; END $$""")
        op.execute('CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION sentinel_audit_append_only()')

def downgrade():
    bind=op.get_bind()
    if bind.dialect.name=='postgresql':
        op.execute('DROP TRIGGER IF EXISTS audit_append_only ON audit_events')
        op.execute('DROP FUNCTION IF EXISTS sentinel_audit_append_only()')
    for name in ('ix_audit_created_actor','ix_audit_action_created'):op.drop_index(name,table_name='audit_events')
    SecuritySimulation.__table__.drop(bind,checkfirst=True)
