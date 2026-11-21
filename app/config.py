"""환경 설정 — 모든 비밀 값은 .env 파일(또는 환경 변수)에서만 읽는다. 코드에 키를 적지 않는다."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DEFAULT_MODELS = {"openai": "gpt-5-mini", "anthropic": "claude-sonnet-4"}


@dataclass(frozen=True)
class Settings:
    api_style: str            # "openai" 또는 "anthropic" (Codyssey API 키 발급 시 고른 호환 방식)
    api_key: str              # Codyssey virtual key (sk-cody-live-...)
    base_url: str             # https://copa.codyssey.kr
    model: str
    timeout: float
    session_id: str           # X-Codyssey-Session-Id (선택)
    db_path: Path
    max_question_chars: int = 500

    @property
    def llm_enabled(self) -> bool:
        return bool(self.api_key)


def get_settings() -> Settings:
    style = os.getenv("LLM_API_STYLE", "openai").strip().lower()
    if style not in DEFAULT_MODELS:
        style = "openai"
    db = os.getenv("DB_PATH", str(ROOT / "data" / "app.db"))
    return Settings(
        api_style=style,
        api_key=os.getenv("CODYSSEY_API_KEY", "").strip(),
        base_url=os.getenv("CODYSSEY_BASE_URL", "https://copa.codyssey.kr").rstrip("/"),
        model=os.getenv("LLM_MODEL", "").strip() or DEFAULT_MODELS[style],
        timeout=float(os.getenv("LLM_TIMEOUT", "60")),
        session_id=os.getenv("CODYSSEY_SESSION_ID", "traffic-ai-assistant").strip(),
        db_path=Path(db),
    )
