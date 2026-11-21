import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAKE_KEY = "sk-cody-test-THIS-IS-A-FAKE-KEY-123"


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    """create(style=None|'openai'|'anthropic', transport=..., seed=True/False) → TestClient
    style=None 이면 API 키 없이(대체 모드) 실행한다. 실제 네트워크는 절대 쓰지 않는다."""
    from app.main import create_app

    def _make(style=None, transport=None, seed=False):
        monkeypatch.setenv("SEED_ON_START", "1" if seed else "0")
        monkeypatch.setenv("CODYSSEY_SESSION_ID", "test-session")
        if style:
            monkeypatch.setenv("LLM_API_STYLE", style)
            monkeypatch.setenv("CODYSSEY_API_KEY", FAKE_KEY)
            monkeypatch.setenv("LLM_MODEL", "")
        else:
            monkeypatch.setenv("CODYSSEY_API_KEY", "")
        app = create_app(tmp_path / "test.db", transport=transport)
        return TestClient(app)

    return _make
