"""Real PostgreSQL acceptance checks. Only accepts an explicitly disposable database."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from sqlalchemy.engine import make_url
url=os.getenv('SENTINEL_TEST_POSTGRES_URL')
if not url:
    print('NOT RUN: set SENTINEL_TEST_POSTGRES_URL for a disposable PostgreSQL database');sys.exit(2)
parsed=make_url(url)
if not parsed.drivername.startswith('postgresql') or not (parsed.database or '').startswith('sentinel_test_'):
    print('REFUSED: database name must start with sentinel_test_');sys.exit(2)
os.environ.update(DATABASE_URL=url,ENVIRONMENT='test',DEMO_MODE='true',SEED_DEMO_DATA='true',AI_PROVIDER='deterministic',AZURE_AI_FOUNDRY_ENABLED='false',RATE_LIMIT_PER_MINUTE='10000')
from alembic.config import Config
from alembic import command
from sqlalchemy import text, select
from sqlalchemy.exc import DBAPIError
from app.database import engine, SessionLocal
from app.models import AuditEvent
from app.audit import verify_chain
from app.main import app
from fastapi.testclient import TestClient
from concurrent.futures import ThreadPoolExecutor
root=Path(__file__).resolve().parents[1]
config=Config(str(root/'backend/alembic.ini'));config.set_main_option('script_location',str(root/'backend/alembic'))
command.upgrade(config,'head')
with TestClient(app) as client:
    assert client.get('/ready').status_code==200
    login=client.post('/auth/login',json={'email':'admin@sentinelchain.local','password':'demo1234'});assert login.status_code==200
    headers={'Authorization':'Bearer '+login.json()['access_token']}
    assert client.get('/security/overview',headers=headers).status_code==200
    assert client.post('/notifications/reconcile',headers=headers).status_code==200
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(lambda _:client.get('/dashboard',headers={'Authorization':'Bearer invalid'}).status_code,range(12)))==[401]*12
    assert client.get('/security/audit',headers=headers).json()['valid']
with SessionLocal() as db:
    assert verify_chain(db)==(True,None)
    id=db.scalar(select(AuditEvent.id).limit(1))
    try:
        db.execute(text('UPDATE audit_events SET payload_json=:value WHERE id=:id'),{'value':'{}','id':id});db.commit()
    except DBAPIError:db.rollback()
    else:raise AssertionError('PostgreSQL audit UPDATE guard failed')
    assert verify_chain(db)==(True,None)
print('PASS: real PostgreSQL migrations, startup, UTC timestamps, API, notification reconciliation, concurrent audit writes and append-only trigger')
print('Disposable fixtures retained for inspection; no database was dropped.')
engine.dispose()
