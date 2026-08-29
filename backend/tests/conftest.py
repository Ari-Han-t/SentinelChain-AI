import os
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///./test-sentinelchain.db"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["RATE_LIMIT_PER_MINUTE"] = "10000"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app
from app.seed import seed_database


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed_database()
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth(client):
    def get(role: str = "admin") -> dict[str, str]:
        emails = {
            "admin": "admin@sentinelchain.local",
            "analyst": "analyst@sentinelchain.local",
            "manager": "manager@sentinelchain.local",
            "auditor": "auditor@sentinelchain.local",
        }
        response = client.post("/auth/login", json={"email": emails[role], "password": "demo1234"})
        assert response.status_code == 200
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return get


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    Path("test-sentinelchain.db").unlink(missing_ok=True)
