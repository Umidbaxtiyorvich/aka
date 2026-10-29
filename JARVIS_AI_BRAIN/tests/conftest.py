import pytest

from jarvis.config import Settings
from jarvis.core import JarvisCore


@pytest.fixture
def core(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    ws = tmp_path / "workspace"
    ws.mkdir()
    s = Settings(allowed_read_dirs=[str(ws)], allowed_write_dirs=[str(ws)])
    return JarvisCore(db_path=tmp_path / "t.db", settings=s)


@pytest.fixture
def client(core):
    from fastapi.testclient import TestClient
    from jarvis.api import create_app
    return TestClient(create_app(core))
