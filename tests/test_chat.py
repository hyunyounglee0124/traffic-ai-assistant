"""① 데이터 기반 AI 채팅 / ④ 대화 기록

실제 Codyssey 서버 대신 httpx.MockTransport로 가짜 응답을 돌려주고,
우리 앱이 보내는 요청(주소·헤더·본문)이 Codyssey 문서의 형식과 같은지 검사한다.
"""
import json
from datetime import date

import httpx

from app.chat import find_ranges
from tests.conftest import FAKE_KEY


def recorder(reply_json, status=200):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(status, json=reply_json)
    return httpx.MockTransport(handler), seen


def test_openai_compatible_request_format(make_client):
    transport, seen = recorder({"choices": [{"message": {"role": "assistant", "content": "4월 14일은 **27,454대**로 크게 줄었습니다."}}]})
    c = make_client(style="openai", transport=transport, seed=True)
    r = c.post("/api/chat", json={"question": "2018년 4월 폭설 때 교통량은?"}).json()

    req = seen[0]
    assert str(req.url) == "https://copa.codyssey.kr/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {FAKE_KEY}"
    assert req.headers["x-codyssey-session-id"] == "test-session"
    body = json.loads(req.content)
    assert body["model"] == "gpt-5-mini"
    assert body["messages"][0]["role"] == "system" and body["messages"][-1] == {"role": "user", "content": "2018년 4월 폭설 때 교통량은?"}
    system = body["messages"][0]["content"]
    assert "[데이터 요약]" in system and "2018-04-14 | 토 | 27,454 |" in system     # 저장된 요약 + 관련 기록이 들어감
    assert r["mode"] == "ai" and "27,454" in r["answer"] and r["model"] == "gpt-5-mini"


def test_anthropic_compatible_request_format(make_client):
    transport, seen = recorder({"content": [{"type": "text", "text": "금요일이 가장 붐빕니다."}], "role": "assistant"})
    c = make_client(style="anthropic", transport=transport, seed=True)
    r = c.post("/api/chat", json={"question": "어느 요일이 가장 붐벼?"}).json()

    req = seen[0]
    assert str(req.url) == "https://copa.codyssey.kr/v1/messages"
    assert req.headers["x-api-key"] == FAKE_KEY and req.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in req.headers
    body = json.loads(req.content)
    assert body["model"] == "claude-sonnet-4" and body["max_tokens"] > 0
    assert "요일별 평균" in body["system"] and body["messages"] == [{"role": "user", "content": "어느 요일이 가장 붐벼?"}]
    assert r["mode"] == "ai" and r["answer"] == "금요일이 가장 붐빕니다."


def test_previous_turns_are_sent_for_follow_up(make_client):
    transport, seen = recorder({"choices": [{"message": {"content": "답변"}}]})
    c = make_client(style="openai", transport=transport, seed=True)
    c.post("/api/chat", json={"question": "2017년 12월 평균은?"})
    c.post("/api/chat", json={"question": "그럼 그 전 달은?"})
    msgs = json.loads(seen[1].content)["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[1]["content"] == "2017년 12월 평균은?"


def test_fallback_without_key(make_client):
    c = make_client(seed=True)
    r = c.post("/api/chat", json={"question": "2018-04-14 교통량 알려줘"}).json()
    assert r["mode"] == "fallback" and "API 키가 설정되지 않았습니다" in r["error"]
    assert "2018-04-14(토) 27,454대" in r["answer"] and "폭설" in r["answer"]
    assert "같은 요일의 전체 평균과 비교하면" in r["answer"]


def test_fallback_on_server_error_and_no_key_leak(make_client):
    transport, _ = recorder({"error": {"message": f"invalid key {FAKE_KEY}"}}, status=401)
    c = make_client(style="openai", transport=transport, seed=True)
    r = c.post("/api/chat", json={"question": "최근 30일 흐름 요약해 줘"}).json()
    assert r["mode"] == "fallback" and "401" in r["error"]
    dump = json.dumps(r, ensure_ascii=False) + json.dumps(c.get("/api/chat/history").json(), ensure_ascii=False) \
        + json.dumps(c.get("/api/health").json(), ensure_ascii=False)
    assert FAKE_KEY not in dump                                   # 키가 응답·기록·상태 어디에도 노출되지 않음


def test_fallback_on_timeout(make_client):
    def boom(request):
        raise httpx.ReadTimeout("timeout", request=request)
    c = make_client(style="openai", transport=httpx.MockTransport(boom), seed=True)
    r = c.post("/api/chat", json={"question": "오늘 교통량은?"}).json()
    assert r["mode"] == "fallback" and "초를 넘었습니다" in r["error"]


def test_question_validation(make_client):
    c = make_client()
    assert c.post("/api/chat", json={"question": ""}).status_code == 422
    assert c.post("/api/chat", json={"question": "   "}).status_code == 422
    assert c.post("/api/chat", json={"question": "가" * 501}).status_code == 422


def test_chat_history_crud(make_client):
    c = make_client(seed=True)
    ids = [c.post("/api/chat", json={"question": f"질문 {i}"}).json()["id"] for i in range(3)]
    h = c.get("/api/chat/history").json()
    assert h["total"] == 3 and h["items"][0]["id"] == ids[-1]            # 최신순
    assert h["items"][0]["context"].startswith("[관련 기록]")             # 근거도 함께 저장
    assert c.delete(f"/api/chat/history/{ids[0]}").json()["deleted"] == ids[0]
    assert c.delete(f"/api/chat/history/{ids[0]}").status_code == 404
    assert c.delete("/api/chat/history").json()["deleted"] == 2
    assert c.get("/api/chat/history").json()["total"] == 0


def test_find_ranges_parsing():
    latest, years = date(2018, 9, 30), [2016, 2017, 2018]
    def descs(q):
        return [(str(s), str(e)) for s, e, _ in find_ranges(q, latest, years)[0]]
    assert descs("2018-04-14 어땠어") == [("2018-04-14", "2018-04-14")]
    assert descs("2018년 4월 14일") == [("2018-04-14", "2018-04-14")]
    assert descs("2017년 12월 평균") == [("2017-12-01", "2017-12-31")]
    assert descs("4월 교통량") == [("2018-04-01", "2018-04-30")]          # 연도 없으면 최근 연도
    assert descs("12월은?") == [("2017-12-01", "2017-12-31")]             # 2018-12는 데이터 이후라 2017
    assert descs("최근 7일") == [("2018-09-24", "2018-09-30")]
    assert descs("지난달") == [("2018-08-01", "2018-08-31")]
    assert ("2016-01-01", "2016-12-31") in descs("2016년 전체")
    assert find_ranges("노동절에는 어땠어?", latest, years)[1] == ["노동절"]


def test_memo_keyword_context(make_client):
    transport, seen = recorder({"choices": [{"message": {"content": "ok"}}]})
    c = make_client(style="openai", transport=transport, seed=True)
    c.post("/api/chat", json={"question": "추수감사절에는 어땠어?"})
    system = json.loads(seen[0].content)["messages"][0]["content"]
    assert "2017-11-23 | 목 | 49,271 | 추수감사절(공휴일)" in system


def test_index_and_health(make_client):
    c = make_client(seed=True)
    assert "AI 비서" in c.get("/").text
    h = c.get("/api/health").json()
    assert h["records"] == 803 and h["llm_configured"] is False
