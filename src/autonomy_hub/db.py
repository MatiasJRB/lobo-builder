from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from sqlalchemy import JSON, DateTime, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class MissionRecord(Base):
    __tablename__ = "missions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    mission_type: Mapped[str] = mapped_column(String(32), nullable=False)
    brief: Mapped[str] = mapped_column(Text, nullable=False)
    desired_outcome: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    policy_slug: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    linked_repositories: Mapped[list[str]] = mapped_column(JSON, default=list)
    linked_products: Mapped[list[str]] = mapped_column(JSON, default=list)
    linked_documents: Mapped[list[str]] = mapped_column(JSON, default=list)
    spec_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class MissionRunRecord(Base):
    __tablename__ = "mission_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    mission_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    current_task_key: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    branch_name: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    worktree_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    merge_target: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    deploy_targets: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class CommandExecutionRecord(Base):
    __tablename__ = "command_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    mission_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_key: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    cwd: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    exit_code: Mapped[Optional[int]] = mapped_column(nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    log_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class ExecutionTaskRecord(Base):
    __tablename__ = "execution_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    mission_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_key: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_profile_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    repo_scope: Mapped[list[str]] = mapped_column(JSON, default=list)
    surface: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    acceptance_criteria: Mapped[list[str]] = mapped_column(JSON, default=list)
    expected_artifacts: Mapped[list[str]] = mapped_column(JSON, default=list)
    depends_on: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class ArtifactRecord(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    mission_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    repo_scope: Mapped[list[str]] = mapped_column(JSON, default=list)
    uri: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GraphNodeRecord(Base):
    __tablename__ = "graph_nodes"

    node_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GraphEdgeRecord(Base):
    __tablename__ = "graph_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    relation: Mapped[str] = mapped_column(String(120), nullable=False)
    target_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def build_engine(database_url: str):
    if database_url.startswith("sqlite"):
        path = database_url.removeprefix("sqlite+pysqlite:///")
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url, future=True)


def build_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False, class_=Session)


def edge_exists(session: Session, source_key: str, relation: str, target_key: str) -> bool:
    query = select(GraphEdgeRecord).where(
        GraphEdgeRecord.source_key == source_key,
        GraphEdgeRecord.relation == relation,
        GraphEdgeRecord.target_key == target_key,
    )
    return session.execute(query).scalar_one_or_none() is not None
