"""
Repository for managing multi-user authentication, roles, organizations, and projects.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from sqlalchemy import (
    Table,
    Column,
    String,
    Float,
    select,
    insert,
    update,
)

from actuary_engine.infrastructure.database import engine, metadata

organizations_table = Table(
    "organizations",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("created_at", Float, default=time.time),
    Column("updated_at", Float, default=time.time),
    extend_existing=True,
)

projects_table = Table(
    "projects",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("description", String, default=""),
    Column("organization_id", String, nullable=False),
    Column("created_at", Float, default=time.time),
    Column("updated_at", Float, default=time.time),
    extend_existing=True,
)

users_table = Table(
    "users",
    metadata,
    Column("id", String, primary_key=True),
    Column("username", String, unique=True, index=True, nullable=False),
    Column("hashed_password", String, nullable=False),
    Column("role", String, nullable=False), # Admin, Actuary, Reviewer, Viewer
    Column("organization_id", String, nullable=False),
    Column("created_at", Float, default=time.time),
    Column("updated_at", Float, default=time.time),
    extend_existing=True,
)


class AuthRepository:
    def __init__(self) -> None:
        self.engine = engine

    def get_user_by_username(self, username: str) -> Optional[dict[str, Any]]:
        with self.engine.connect() as conn:
            query = select(users_table).where(users_table.c.username == username)
            result = conn.execute(query).fetchone()
            if result:
                return dict(result._mapping)
            return None

    def get_user_by_id(self, user_id: str) -> Optional[dict[str, Any]]:
        with self.engine.connect() as conn:
            query = select(users_table).where(users_table.c.id == user_id)
            result = conn.execute(query).fetchone()
            if result:
                return dict(result._mapping)
            return None

    def get_project_by_id(self, project_id: str) -> Optional[dict[str, Any]]:
        with self.engine.connect() as conn:
            query = select(projects_table).where(projects_table.c.id == project_id)
            result = conn.execute(query).fetchone()
            if result:
                return dict(result._mapping)
            return None

    def create_user(self, username: str, hashed_password: str, role: str, organization_id: str) -> dict[str, Any]:
        user_id = str(uuid.uuid4())
        now = time.time()
        user_data = {
            "id": user_id,
            "username": username,
            "hashed_password": hashed_password,
            "role": role,
            "organization_id": organization_id,
            "created_at": now,
            "updated_at": now,
        }
        with self.engine.begin() as conn:
            conn.execute(insert(users_table).values(user_data))
        return user_data

    def create_organization(self, name: str, org_id: Optional[str] = None) -> dict[str, Any]:
        if org_id is None:
            org_id = str(uuid.uuid4())
        now = time.time()
        org_data = {
            "id": org_id,
            "name": name,
            "created_at": now,
            "updated_at": now,
        }
        with self.engine.begin() as conn:
            conn.execute(insert(organizations_table).values(org_data))
        return org_data

    def create_project(self, name: str, organization_id: str, description: str = "", project_id: Optional[str] = None) -> dict[str, Any]:
        if project_id is None:
            project_id = str(uuid.uuid4())
        now = time.time()
        proj_data = {
            "id": project_id,
            "name": name,
            "description": description,
            "organization_id": organization_id,
            "created_at": now,
            "updated_at": now,
        }
        with self.engine.begin() as conn:
            conn.execute(insert(projects_table).values(proj_data))
        return proj_data

auth_repo = AuthRepository()
