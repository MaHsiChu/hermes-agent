from __future__ import annotations

import os
import json
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Secret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: str | None = None
    env: str | None = None

    def read(self) -> str:
        if bool(self.file) == bool(self.env):
            raise ValueError("Secret requires exactly one file or env reference")
        if self.env:
            return os.environ[self.env]
        path = Path(self.file)
        if os.name != "nt" and path.stat().st_mode & 0o077:
            raise ValueError("Secret files must have mode 0600")
        return path.read_text(encoding="utf-8").strip()


class OIDCConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issuer: str
    client_id: str
    client_secret: Secret | None = None


def validate_url(url: str, development: bool) -> str:
    u = urlsplit(url)
    if u.username or u.password or u.query or u.fragment:
        raise ValueError("URLs must not contain credentials, query or fragment")
    if u.scheme != "https" and not (development and u.scheme == "http" and u.hostname in
                                     {"localhost", "127.0.0.1", "::1", "testserver"}):
        raise ValueError("HTTPS required; development permits loopback HTTP only")
    return url.rstrip("/")


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public_url: str = "http://127.0.0.1:8787"
    database_url: str = "sqlite:///remote-relay.sqlite3"
    database_secret: Secret | None = None
    development: bool = False
    host: str = "127.0.0.1"
    port: int = 8787
    oidc: OIDCConfig | None = None
    session_seconds: int = 43200
    pairing_seconds: int = 600
    command_seconds: int = 30
    attachment_limit: int = 8 * 1024 * 1024
    static_dir: str | None = None

    @model_validator(mode="after")
    def secure_urls(self):
        self.public_url = validate_url(self.public_url, self.development)
        if self.oidc:
            self.oidc.issuer = validate_url(self.oidc.issuer, self.development)
        if not self.development and self.database_url.startswith("sqlite") and not self.database_secret:
            raise ValueError("Production requires PostgreSQL; SQLite is development-only")
        return self


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend_id: str = Field(min_length=1, max_length=100)
    profile: str = Field(min_length=1, max_length=100)
    engine: str = Field(pattern="^(hermes|codex|claude)$")


class Backend(Source):
    url: str
    token: Secret
    # The user's explicit upload scope. There is no source auto-discovery.
    attachment_roots: list[str] = Field(default_factory=list)


class BridgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relay_url: str
    development: bool = False
    device_name: str
    credential_file: str
    state_file: str
    backends: list[Backend] = Field(min_length=1, max_length=32)
    poll_seconds: float = 5

    @model_validator(mode="after")
    def validate_sources(self):
        self.relay_url = validate_url(self.relay_url, self.development)
        keys = [source_key(b.model_dump()) for b in self.backends]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate backend/profile/engine scope")
        for b in self.backends:
            b.url = validate_url(b.url, self.development)
        return self


def source_key(value: dict) -> str:
    return json.dumps([value[k] for k in ("backend_id", "profile", "engine")],separators=(',',':'),ensure_ascii=False)


def load(path: str, cls):
    return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
