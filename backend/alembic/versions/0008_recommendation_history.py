"""Capture recommendation explanations and decision/implementation history."""
from alembic import op
revision='0008'
down_revision='0007'
branch_labels=None
depends_on=None
def upgrade():
    from app.models import RecommendationSnapshot,RecommendationProgress,RecommendationHistoryEvent,StageRiskAssessment,AuditWriteLock
    for model in (RecommendationSnapshot,RecommendationProgress,RecommendationHistoryEvent,StageRiskAssessment,AuditWriteLock):model.__table__.create(op.get_bind(),checkfirst=True)
def downgrade():
    for name in ('audit_write_lock','stage_risk_assessments','recommendation_history_events','recommendation_progress','recommendation_snapshots'):op.drop_table(name)
