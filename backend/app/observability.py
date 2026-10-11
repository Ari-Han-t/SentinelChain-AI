"""Safe request context: never includes headers, query strings or request bodies."""
from contextvars import ContextVar
from uuid import uuid4
request_context = ContextVar('request_context', default=None)

SENSITIVE = {'password','password_hash','authorization','token','access_token','api_key','secret','credentials','encrypted_contact','encrypted_data','contact','email','csv_content'}
def sanitize(value):
    if isinstance(value, dict):
        return {str(k): '[redacted]' if str(k).lower() in SENSITIVE or any(x in str(k).lower() for x in ('secret','password','token','credential')) else sanitize(v) for k,v in value.items()}
    if isinstance(value, list): return [sanitize(v) for v in value]
    return value

def context():
    return request_context.get() or {'request_id':str(uuid4()),'identity':'service','operation':'background'}
