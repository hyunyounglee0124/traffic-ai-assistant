"""Codyssey API 연결 확인 스크립트 — .env 설정이 맞는지 한 번 호출해 본다.

실행 (프로젝트 루트에서):  python scripts/check_api.py
성공하면 AI의 짧은 답이, 실패하면 원인(키·호환 방식·모델 이름 등)이 출력된다. 키 값은 출력하지 않는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings          # noqa: E402
from app.llm import LLMError, call_llm       # noqa: E402

s = get_settings()
masked = (s.api_key[:12] + "…" + s.api_key[-4:]) if len(s.api_key) > 16 else ("(비어 있음)" if not s.api_key else "(설정됨)")
print(f"호환 방식: {s.api_style}  |  주소: {s.base_url}  |  모델: {s.model}  |  키: {masked}")
try:
    text, ms = call_llm(s, "한 문장으로 짧게 답하세요.", [{"role": "user", "content": "연결 테스트입니다. '연결 성공'이라고 답해 주세요."}])
    print(f"✅ 연결 성공 ({ms / 1000:.1f}초): {text}")
except LLMError as e:
    print(f"❌ 연결 실패: {e}")
    print("   확인할 것: ① .env의 CODYSSEY_API_KEY  ② LLM_API_STYLE이 키 발급 때 고른 방식(openai/anthropic)과 같은지  ③ LLM_MODEL 이름")
    sys.exit(1)
