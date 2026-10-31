import re

import pytest

from jarvis.config import Settings
from jarvis.core import JarvisCore

# Release gate uchun test toifalari (fayl bo'yicha + test nomi bo'yicha)
FILE_CATEGORIES = {
    "test_security": ["permissions", "unit"], "test_approval": ["permissions", "unit"], "test_policy": ["permissions", "unit"],
    "test_memory_audit": ["unit"], "test_chat_agents": ["unit"], "test_api_files": ["api"], "test_bi_pos": ["integration"],
    "test_integrations": ["integration"], "test_studio_browser": ["integration"], "test_planner_improve": ["integration"],
    "test_router_guard": ["unit"], "test_provenance_decisions": ["unit"], "test_sandbox": ["permissions", "integration"],
    "test_backup": ["integration"], "test_graphs": ["integration"], "test_plugins": ["permissions", "integration"],
    "test_diagnostics": ["api", "unit"], "test_dashboard_e2e": ["frontend"], "test_auth": ["permissions", "api"],
    "test_apps": ["permissions", "integration"], "test_ai_features": ["unit", "integration"],
}
ERROR_NAME = re.compile(r"fail|error|invalid|reject|block|forbidden|unknown|tamper|limit|validation|honest|unapproved|cannot|dangerous|missing|not_configured|refuse|untrusted")


def pytest_collection_modifyitems(items):
    for item in items:
        cats = set(FILE_CATEGORIES.get(item.path.stem, ["unit"]))
        if "api" in item.name or "client" in getattr(item, "fixturenames", ()):
            cats.add("api")
        if ERROR_NAME.search(item.name):
            cats.add("errors")
        for c in cats:
            item.add_marker(getattr(pytest.mark, c))
        item.user_properties.append(("categories", ",".join(sorted(cats))))



@pytest.fixture
def core(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    ws = tmp_path / "workspace"
    ws.mkdir()
    # Umumiy testlarda PIN o'chiq; himoya test_auth.py da alohida sinaladi
    s = Settings(allowed_read_dirs=[str(ws)], allowed_write_dirs=[str(ws)], auth_enabled=False,
                 allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    c = JarvisCore(db_path=tmp_path / "t.db", settings=s)
    c.integrations.auto_learn = False             # fonda avtomatik o'rganish — alohida testda yoqiladi
    return c


@pytest.fixture
def client(core):
    from fastapi.testclient import TestClient
    from jarvis.api import create_app
    return TestClient(create_app(core))
