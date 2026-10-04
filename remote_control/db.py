"""Versioned SQLAlchemy schema shared by SQLite development and PostgreSQL."""
from sqlalchemy import (MetaData, Table, Column, String, Text, Float, Integer, Boolean,
                        JSON, LargeBinary, UniqueConstraint, ForeignKey, create_engine, event, select)

metadata = MetaData()
versions = Table("remote_schema", metadata, Column("version", Integer, primary_key=True))
users = Table("remote_users", metadata,
    Column("id", String(64), primary_key=True), Column("issuer", String(500), nullable=False),
    Column("subject", String(255), nullable=False), Column("name", String(255)),
    UniqueConstraint("issuer", "subject"))
logins = Table("remote_logins", metadata,
    Column("hash", String(64), primary_key=True), Column("user_id", ForeignKey(users.c.id)),
    Column("csrf", String(100), nullable=False), Column("expires_at", Float, nullable=False))
flows = Table("remote_oidc_flows", metadata,
    Column("hash", String(64), primary_key=True), Column("data", JSON, nullable=False),
    Column("expires_at", Float, nullable=False))
devices = Table("remote_devices", metadata,
    Column("id", String(64), primary_key=True), Column("user_id", ForeignKey(users.c.id), nullable=False),
    Column("name", String(100)), Column("token_hash", String(64), unique=True),
    Column("sources", JSON, nullable=False), Column("revoked", Boolean, default=False, nullable=False),
    Column("last_seen", Float, default=0))
pairings = Table("remote_pairings", metadata,
    Column("id", String(64), primary_key=True), Column("device_hash", String(64), nullable=False),
    Column("user_code", String(30)), Column("name", String(100)), Column("sources", JSON),
    Column("approved_sources", JSON), Column("user_id", ForeignKey(users.c.id)),
    Column("expires_at", Float), Column("claimed", Boolean, default=False, nullable=False))
sessions = Table("remote_sessions", metadata,
    Column("id", String(64), primary_key=True), Column("device_id", ForeignKey(devices.c.id), nullable=False),
    Column("backend_id", String(100), nullable=False), Column("profile", String(100), nullable=False),
    Column("engine", String(20), nullable=False), Column("native_session_id", String(255), nullable=False),
    Column("title", Text), Column("archived", Boolean, default=False), Column("deleted", Boolean, default=False),
    Column("revision", Integer, nullable=False), Column("updated_at", Float), Column("data", JSON),
    Column("capabilities", JSON), Column("sync", JSON), Column("pending_requests", JSON),
    UniqueConstraint("device_id", "backend_id", "profile", "engine", "native_session_id"))
messages = Table("remote_messages", metadata,
    Column("session_id", ForeignKey(sessions.c.id), primary_key=True), Column("id", String(255), primary_key=True),
    Column("revision", Integer), Column("ordinal", Float), Column("deleted", Boolean), Column("data", JSON))
commands = Table("remote_commands", metadata,
    Column("request_id", String(128), primary_key=True), Column("user_id", ForeignKey(users.c.id)),
    Column("session_id", ForeignKey(sessions.c.id)), Column("device_id", ForeignKey(devices.c.id)),
    Column("digest", String(64)), Column("operation", String(30)), Column("payload", JSON),
    Column("state", String(30)), Column("result", JSON), Column("error", Text),
    Column("created_at", Float), Column("expires_at", Float))
attachments = Table("remote_attachments", metadata,
    Column("id", String(64), primary_key=True), Column("session_id", ForeignKey(sessions.c.id)),
    Column("name", String(255)), Column("mime", String(100)), Column("size", Integer), Column("data", LargeBinary))
events = Table("remote_events", metadata,
    Column("seq", Integer, primary_key=True, autoincrement=True), Column("session_id", ForeignKey(sessions.c.id)),
    Column("type", String(100)), Column("data", JSON), Column("created_at", Float))


def open_database(url):
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {}, pool_pre_ping=True)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def pragmas(dbapi, _):
            dbapi.execute("PRAGMA foreign_keys=ON")
            # Development reliability across bundled SQLite versions takes precedence over WAL throughput.
            dbapi.execute("PRAGMA journal_mode=DELETE")
    return engine


def migrate(engine):
    metadata.create_all(engine)
    with engine.begin() as c:
        current = c.execute(select(versions.c.version)).scalar()
        if current is None:
            c.execute(versions.insert().values(version=1))
        elif current != 1:
            raise RuntimeError("Unsupported remote database schema; migrate before startup")
