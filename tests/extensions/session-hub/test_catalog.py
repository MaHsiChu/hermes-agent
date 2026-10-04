"""Native catalog pages retain a stable source snapshot and explicit coverage."""
import importlib
import json
from pathlib import Path
import sqlite3
import shutil
import sys

from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[3] / "extensions" / "session-hub"
    extension = tmp_path / "extension"
    extension.mkdir()
    module_names = []
    for path in source.glob("*.py"):
        shutil.copy2(path, extension / path.name)
        module_names.append(path.stem)
        monkeypatch.delitem(sys.modules, path.stem, raising=False)
    codex = tmp_path / "codex"
    codex.mkdir()
    database = codex / "state_5.sqlite"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE threads(id TEXT, rollout_path TEXT, cwd TEXT, title TEXT, "
                   "name TEXT, updated_at REAL, archived INTEGER, source TEXT, history_mode TEXT)")
        db.executemany("INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?)", [
            (str(i), str(codex / f"{i}.jsonl"), str(tmp_path), f"Task {i}", "", i,
             int(i % 3 == 0), "cli", "legacy") for i in range(307)
        ])
    db.close()
    claude = tmp_path / "claude" / "projects" / "project"
    claude.mkdir(parents=True)
    (claude / "claude-session.jsonl").write_text(json.dumps({
        "type": "user", "cwd": str(tmp_path), "message": {"content": "Claude task"},
    }) + "\n", encoding="utf-8")
    settings = json.loads((source / "settings.example.json").read_text(encoding="utf-8"))
    settings.update(codex_home=str(codex), claude_home=str(tmp_path / "claude"),
                    claude_desktop_home=str(tmp_path / "desktop"))
    (extension / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    monkeypatch.syspath_prepend(str(extension))
    service = importlib.import_module("service")
    reader = service.READERS
    client = TestClient(service.app)
    client.headers["Authorization"] = "Bearer " + service.TOKEN
    try:
        yield client, reader, database
    finally:
        client.close()
        for name in module_names:
            module = sys.modules.get(name)
            if module and Path(getattr(module, "__file__", "")).is_relative_to(extension):
                sys.modules.pop(name, None)


def test_catalog_pages_cover_archive_and_remain_stable_across_refresh(catalog):
    client, reader, database = catalog
    default = client.post("/rpc/sessions", json={"engine": "codex", "limit": 200}).json()
    assert not any(row["archived"] for row in default["sessions"])
    first = client.post("/rpc/sessions", json={
        "engine": "codex", "include_archived": True, "limit": 73,
    }).json()
    snapshot = first["pagination"]["snapshot_id"]
    with sqlite3.connect(database) as db:
        db.execute("UPDATE threads SET updated_at=9999 WHERE id='0'")
    db.close()
    reader.sessions(refresh=True)
    # Board projection resolves each native task; that must not evict an export.
    for i in range(45):
        assert reader.resolve("codex", str(i))["session_id"] == str(i)
    rows = list(first["sessions"])
    offset = first["pagination"]["next_offset"]
    while offset is not None:
        response = client.post("/rpc/sessions", json={
            "engine": "codex", "include_archived": True, "limit": 73,
            "offset": offset, "snapshot_id": snapshot,
        })
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["pagination"]["complete"] is True
        rows.extend(page["sessions"])
        offset = page["pagination"]["next_offset"]
    assert [row["session_id"] for row in rows] == [str(i) for i in reversed(range(307))]
    assert {row["session_id"] for row in rows if row["archived"]} == {
        str(i) for i in range(307) if i % 3 == 0
    }
    denied = client.post("/rpc/sessions", json={"snapshot_id": snapshot, "engine": "claude"})
    assert denied.status_code == 400


def test_partial_catalog_and_expired_snapshot_cannot_claim_full_coverage(catalog, monkeypatch):
    client, reader, database = catalog
    reader.desktop.mkdir()
    metadata = reader.desktop / "local_claude.json"
    metadata.write_text('{"cliSessionId":', encoding="utf-8")
    incomplete = client.post("/rpc/sessions", json={"refresh": True, "query": "Missing title"}).json()
    assert incomplete["pagination"]["complete"] is False
    assert incomplete["errors"]
    metadata.unlink()
    database.unlink()
    result = client.post("/rpc/sessions", json={"refresh": True, "include_archived": True}).json()
    assert result["sessions"][0]["engine"] == "claude"
    assert result["errors"]
    assert result["pagination"]["complete"] is False
    snapshot = result["pagination"]["snapshot_id"]
    import readers
    expires = readers.time.monotonic() + 181
    monkeypatch.setattr(readers.time, "monotonic", lambda: expires)
    expired = client.post("/rpc/sessions", json={"snapshot_id": snapshot, "include_archived": True})
    assert expired.status_code == 400
    for body in ({"offset": -1}, {"include_archived": "false"}):
        response = client.post("/rpc/sessions", json=body)
        assert response.status_code == 400
