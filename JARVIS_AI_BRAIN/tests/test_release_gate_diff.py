"""Release gate diff ko'rigi: haqiqiy kalit naqshlari ushlanadi, oddiy 'token' so'zi esa yo'q."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import release_gate as rg  # noqa: E402


def test_secret_value_patterns():
    hits = ['TOKEN = "ghp_' + "a" * 36 + '"', 'api_key = "zxcvbnmasdfgh123"', 'bot = "123456789:AA' + "b" * 33 + '"',
            "-----BEGIN RSA PRIVATE KEY-----", "k = 'sk-" + "x" * 24 + "'"]
    misses = ['key = get_secret("telegram_bot_token")', "token: ${m.token_set}", "tokens_in=estimate_tokens(prompt)",
              'password = ""', "api_key = settings.api_key"]
    assert all(re.search(rg.SECRET_VALUE, h) for h in hits)
    assert not any(re.search(rg.SECRET_VALUE, m) for m in misses)


def test_secret_file_names():
    assert all(re.search(rg.SECRET_FILE, f) for f in [".env", "config/.env.local", "certs/server.pem", "data/settings.json", "id_rsa"])
    assert not any(re.search(rg.SECRET_FILE, f) for f in ["jarvis/secrets.py", "docs/SECURITY.md", "tests/test_secrets_ui.py"])


def test_check_diff_runs_on_this_repo():
    r = rg.check_diff()
    assert r["name"] == "diff_review" and r["status"] in ("passed", "not_run")
