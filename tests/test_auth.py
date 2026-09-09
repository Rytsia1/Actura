"""
Tests for multi-user authentication and RBAC authorization.
"""
import pytest
from fastapi.testclient import TestClient
from actuary_engine.api.main import app
from actuary_engine.infrastructure.auth_repo import auth_repo
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

from actuary_engine.api.dependencies import get_current_user

@pytest.fixture(autouse=True)
def clean_dependency_overrides():
    old = dict(app.dependency_overrides)
    app.dependency_overrides.pop(get_current_user, None)
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(old)

@pytest.fixture(scope="module")
def real_client() -> TestClient:
    return TestClient(app)

@pytest.fixture(scope="module")
def setup_users():
    org = auth_repo.create_organization("Test Org")
    
    admin = auth_repo.get_user_by_username("testadmin")
    if not admin:
        admin = auth_repo.create_user("testadmin", pwd_context.hash("admin123"), "Admin", org["id"])
    
    viewer = auth_repo.get_user_by_username("testviewer")
    if not viewer:
        viewer = auth_repo.create_user("testviewer", pwd_context.hash("viewer123"), "Viewer", org["id"])
    
    return {
        "admin": admin,
        "viewer": viewer,
        "org": org
    }

def test_login_success(real_client: TestClient, setup_users):
    response = real_client.post("/api/v1/auth/token", data={
        "username": "testadmin",
        "password": "admin123"
    })
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert response.json()["token_type"] == "bearer"

def test_login_invalid_password(real_client: TestClient, setup_users):
    response = real_client.post("/api/v1/auth/token", data={
        "username": "testadmin",
        "password": "wrongpassword"
    })
    assert response.status_code == 401

def test_unauthorized_access(real_client: TestClient):
    response = real_client.get("/api/v1/models")
    assert response.status_code == 401

def test_rbac_admin_access(real_client: TestClient, setup_users):
    login = real_client.post("/api/v1/auth/token", data={
        "username": "testadmin",
        "password": "admin123"
    })
    token = login.json()["access_token"]
    
    # Admin can access models
    response = real_client.get("/api/v1/models", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200

def test_rbac_viewer_denied_post(real_client: TestClient, setup_users):
    login = real_client.post("/api/v1/auth/token", data={
        "username": "testviewer",
        "password": "viewer123"
    })
    token = login.json()["access_token"]
    
    # Viewer cannot post a model
    response = real_client.post("/api/v1/models", json={
        "name": "Test Model",
        "product_type": "endowment",
        "issue_age": 30,
        "sum_assured": 100000,
        "interest_rate": 0.05
    }, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert "Operation not permitted" in response.json()["detail"]


def test_jwt_secret_key_production_enforcement(monkeypatch):
    import os
    from actuary_engine.api.auth import get_secret_key

    # In production without key, must raise RuntimeError
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY environment variable must be set"):
        get_secret_key()

    # In production with key, must return configured key
    monkeypatch.setenv("JWT_SECRET_KEY", "prod_configured_secret_123")
    assert get_secret_key() == "prod_configured_secret_123"

