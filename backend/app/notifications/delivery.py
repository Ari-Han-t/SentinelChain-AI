from ..models import utc_naive
"""Delivery adapters receive only authorized incident metadata and stable keys.
No email provider is configured or called. Additional adapters require deployment setup.
"""
from typing import Protocol
from datetime import timedelta
from ..models import utcnow

class DeliveryFailure(Exception):
    def __init__(self,code='delivery_unavailable',retryable=True):self.code=code;self.retryable=retryable

class Channel(Protocol):
    def deliver(self,*,idempotency_key:str,recipient_id:int,incident_id:int)->None:...

class InAppChannel:
    def deliver(self,**kwargs):return None

CHANNELS:dict[str,Channel]={'in_app':InAppChannel()}

def deliver(row):
    if row.status=='delivered' or row.status=='failed':return
    if row.next_attempt_at and utc_naive(row.next_attempt_at)>utcnow():return
    row.attempts+=1
    adapter=CHANNELS.get(row.channel)
    try:
        if adapter is None:raise DeliveryFailure('channel_not_configured',False)
        adapter.deliver(idempotency_key=f'incident-{row.incident_id}-recipient-{row.user_id}-level-{row.level}',recipient_id=row.user_id,incident_id=row.incident_id)
        row.status='delivered';row.error_code=None;row.next_attempt_at=None
    except Exception as exc:
        if not isinstance(exc,DeliveryFailure):exc=DeliveryFailure('adapter_failure',True)
        row.error_code=exc.code;row.status='pending' if exc.retryable and row.attempts<3 else 'failed'
        row.next_attempt_at=utcnow()+timedelta(seconds=30*2**(row.attempts-1)) if row.status=='pending' else None
