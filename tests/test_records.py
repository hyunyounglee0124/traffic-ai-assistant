"""② 데이터 관리(CRUD) — 추가·조회·수정·삭제와 입력 검증, 변경 시 분석 결과 자동 저장"""


def snap_id(c):
    return c.get("/api/analysis/latest").json()["id"]


def test_create_read_update_delete(make_client):
    c = make_client()
    s0 = snap_id(c)
    # Create
    r = c.post("/api/records", json={"date": "2024-01-02", "value": 100, "memo": "  첫 기록  "})
    assert r.status_code == 201
    rec = r.json()
    assert rec["date"] == "2024-01-02" and rec["value"] == 100 and rec["memo"] == "첫 기록"
    assert rec["snapshot_id"] > s0                         # 추가하면 분석이 다시 저장됨
    # Read
    assert c.get(f"/api/records/{rec['id']}").json()["value"] == 100
    lst = c.get("/api/records").json()
    assert lst["total"] == 1 and lst["items"][0]["id"] == rec["id"]
    # Update
    r = c.put(f"/api/records/{rec['id']}", json={"date": "2024-01-03", "value": 150.5, "memo": "수정"})
    assert r.status_code == 200 and r.json()["value"] == 150.5 and r.json()["date"] == "2024-01-03"
    assert r.json()["snapshot_id"] > rec["snapshot_id"]
    # Delete
    r = c.delete(f"/api/records/{rec['id']}")
    assert r.status_code == 200 and r.json()["deleted"] == rec["id"]
    assert c.get(f"/api/records/{rec['id']}").status_code == 404
    assert c.get("/api/records").json()["total"] == 0


def test_validation_errors(make_client):
    c = make_client()
    bad = [
        {"date": "2024-13-01", "value": 1},       # 없는 날짜
        {"date": "2024/01/01", "value": 1},       # 형식 오류
        {"date": "", "value": 1},
        {"date": "2024-01-01", "value": "abc"},   # 숫자가 아님
        {"date": "2024-01-01"},                   # value 누락
        {"date": "2024-01-01", "value": 1, "memo": "x" * 201},  # 메모 200자 초과
    ]
    for b in bad:
        assert c.post("/api/records", json=b).status_code == 422, b
    r = c.post("/api/records", json={"date": "2024-13-01", "value": 1})
    assert "YYYY-MM-DD" in str(r.json()["detail"])


def test_duplicate_date_and_missing(make_client):
    c = make_client()
    a = c.post("/api/records", json={"date": "2024-01-01", "value": 1}).json()
    b = c.post("/api/records", json={"date": "2024-01-02", "value": 2}).json()
    assert c.post("/api/records", json={"date": "2024-01-01", "value": 9}).status_code == 409
    assert c.put(f"/api/records/{b['id']}", json={"date": "2024-01-01", "value": 9}).status_code == 409
    assert c.put(f"/api/records/{a['id']}", json={"date": "2024-01-01", "value": 9}).status_code == 200  # 자기 날짜는 허용
    assert c.put("/api/records/9999", json={"date": "2024-02-01", "value": 1}).status_code == 404
    assert c.delete("/api/records/9999").status_code == 404


def test_filter_search_paging_export(make_client):
    c = make_client()
    for i in range(1, 26):
        c.post("/api/records", json={"date": f"2024-03-{i:02d}", "value": i, "memo": "공휴일" if i % 10 == 0 else ""})
    r = c.get("/api/records", params={"size": 10, "page": 3}).json()
    assert r["total"] == 25 and r["pages"] == 3 and len(r["items"]) == 5
    assert [x["date"] for x in c.get("/api/records", params={"q": "공휴일"}).json()["items"]] == ["2024-03-20", "2024-03-10"]
    rng = c.get("/api/records", params={"start": "2024-03-05", "end": "2024-03-07", "order": "asc"}).json()
    assert [x["value"] for x in rng["items"]] == [5, 6, 7]
    csv = c.get("/api/records/export.csv")
    assert csv.status_code == 200 and "date,value,memo" in csv.text and "2024-03-25" in csv.text


def test_sql_injection_is_harmless(make_client):
    c = make_client()
    c.post("/api/records", json={"date": "2024-01-01", "value": 1, "memo": "'); DROP TABLE records; --"})
    assert c.get("/api/records", params={"q": "' OR 1=1 --"}).json()["total"] == 0
    assert c.get("/api/records").json()["total"] == 1     # 테이블이 그대로 있음
