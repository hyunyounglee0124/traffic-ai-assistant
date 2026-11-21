"""Codyssey API 호출 — OpenAI 호환 / Anthropic 호환 두 방식을 모두 지원.

  OpenAI 호환   : POST {base}/v1/chat/completions   헤더 Authorization: Bearer <key>
  Anthropic 호환: POST {base}/v1/messages           헤더 x-api-key: <key>, anthropic-version

키는 서버에서만 사용하고 브라우저로 보내지 않는다. 오류 메시지에도 키를 넣지 않는다.
"""
from __future__ import annotations

import time

import httpx

from .config import Settings


class LLMError(Exception):
    """AI 호출 실패 (사용자에게 보여 줄 수 있는 안전한 메시지만 담는다)."""


def call_llm(settings: Settings, system: str, messages: list[dict], transport: httpx.BaseTransport | None = None) -> tuple[str, int]:
    """messages: [{'role': 'user'|'assistant', 'content': str}, ...] → (답변, 걸린 시간 ms)"""
    if not settings.llm_enabled:
        raise LLMError("API 키가 설정되지 않았습니다 (.env의 CODYSSEY_API_KEY)")

    headers = {"content-type": "application/json"}
    if settings.session_id:
        headers["X-Codyssey-Session-Id"] = settings.session_id
    if settings.api_style == "anthropic":
        url = f"{settings.base_url}/v1/messages"
        headers |= {"x-api-key": settings.api_key, "anthropic-version": "2023-06-01"}
        body = {"model": settings.model, "max_tokens": 1024, "system": system, "messages": messages}
    else:
        url = f"{settings.base_url}/v1/chat/completions"
        headers["Authorization"] = f"Bearer {settings.api_key}"
        # gpt-5 계열은 temperature·max_tokens 지정이 제한되므로 기본값을 사용한다
        body = {"model": settings.model, "messages": [{"role": "system", "content": system}, *messages]}

    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=settings.timeout, transport=transport) as client:
            r = client.post(url, headers=headers, json=body)
    except httpx.TimeoutException:
        raise LLMError(f"AI 응답 시간이 {settings.timeout:.0f}초를 넘었습니다")
    except httpx.HTTPError as e:
        raise LLMError(f"AI 서버에 연결하지 못했습니다 ({type(e).__name__})")
    ms = int((time.perf_counter() - t0) * 1000)

    if r.status_code != 200:
        hint = {401: "API 키가 올바르지 않거나 만료되었습니다", 403: "이 키로 사용할 수 없는 모델이거나 권한이 없습니다",
                404: "API 주소 또는 모델 이름을 확인하세요", 429: "사용량 한도를 넘었습니다. 잠시 후 다시 시도하세요"}
        raise LLMError(f"AI 서버 오류 {r.status_code}: {hint.get(r.status_code, '잠시 후 다시 시도하세요')}")
    try:
        data = r.json()
        if settings.api_style == "anthropic":
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        else:
            text = data["choices"][0]["message"]["content"] or ""
    except Exception:
        raise LLMError("AI 응답 형식을 해석하지 못했습니다")
    if not text.strip():
        raise LLMError("AI가 빈 답변을 보냈습니다")
    return text.strip(), ms
