"""③ 시계열 분석 — 요약 통계 계산과 분석 결과 DB 저장"""
from datetime import date, timedelta

from app.analysis import compute_summary, summary_to_text


def make_rows(n=70, start=date(2024, 1, 1)):
    rows = []
    for i in range(n):
        d = start + timedelta(days=i)
        v = 100 + i + (50 if d.weekday() < 5 else 0)          # 증가 추세 + 평일이 높음
        rows.append({"date": d.isoformat(), "value": float(v), "memo": ""})
    return rows


def test_summary_values():
    rows = make_rows()
    rows[30]["value"] = 1000.0; rows[30]["memo"] = "이벤트"       # 이상치 1개
    sm = compute_summary(rows)
    assert sm["count"] == 70 and sm["start"] == "2024-01-01" and sm["end"] == "2024-03-10"
    assert sm["max"] == {"date": "2024-01-31", "value": 1000.0, "memo": "이벤트"}
    assert sm["anomalies"][0]["date"] == "2024-01-31"
    assert sm["trend_90d"]["direction"] == "증가"
    assert sm["weekday_high"] in "월화수목금" and sm["weekday_low"] in "토일"
    last7 = [r["value"] for r in rows[-7:]]
    assert sm["last7_avg"] == round(sum(last7) / 7, 1)
    assert sm["missing_days"] == 0
    assert sm["recent_memos"][-1]["memo"] == "이벤트"


def test_summary_text_and_empty():
    assert compute_summary([]) == {"count": 0}
    assert "저장된 데이터가 없습니다" in summary_to_text({"count": 0}, "테스트", "대")
    text = summary_to_text(compute_summary(make_rows()), "테스트 데이터", "대")
    for key in ["기간", "전체 평균", "최근 7일 평균", "요일별 평균", "최근 90일 추세"]:
        assert key in text


def test_snapshot_saved_and_refresh(make_client):
    c = make_client(seed=True)
    latest = c.get("/api/analysis/latest").json()
    assert latest["trigger"] == "seed" and latest["record_count"] == 803
    assert latest["summary"]["min"]["date"] == "2018-04-14"           # 4월 폭설
    r = c.post("/api/analysis/refresh").json()
    assert r["id"] > latest["id"] and r["trigger"] == "manual"
    hist = c.get("/api/analysis/history").json()["items"]
    assert [h["trigger"] for h in hist[:2]] == ["manual", "seed"]


def test_series_moving_average(make_client):
    c = make_client()
    for i in range(1, 11):
        c.post("/api/records", json={"date": f"2024-05-{i:02d}", "value": i * 10})
    items = c.get("/api/series").json()["items"]
    assert items[2]["ma7"] is None                    # 4일 미만은 계산하지 않음
    assert items[6]["ma7"] == 40.0                     # (10+…+70)/7
    part = c.get("/api/series", params={"start": "2024-05-09"}).json()["items"]
    assert [p["date"] for p in part] == ["2024-05-09", "2024-05-10"]
