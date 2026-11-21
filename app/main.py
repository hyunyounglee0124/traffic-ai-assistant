"""웹 서버 (FastAPI) — REST API + 화면(static) 제공.

실행:  uvicorn app.main:app --reload     →  http://127.0.0.1:8000
API 문서(자동 생성): http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import csv
import io
import math
import os
from datetime import date as Date

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .analysis import compute_summary, summary_to_text
from .chat import answer_question
from .config import ROOT, get_settings
from .db import Database

DATA_LABEL = os.getenv("DATA_LABEL", "I-94 고속도로 서쪽 방향 일교통량 (MnDOT ATR 301)")
DATA_UNIT = os.getenv("DATA_UNIT", "대")
SEED_CSV = ROOT / "data" / "seed_i94_daily.csv"


# ── 요청 형식 검증 (pydantic) ─────────────────────────────
class RecordIn(BaseModel):
    date: str = Field(..., examples=["2018-09-30"], description="YYYY-MM-DD")
    value: float = Field(..., examples=[78942])
    memo: str = Field("", max_length=200, examples=["노동절(공휴일)"])

    @field_validator("date")
    @classmethod
    def _date(cls, v: str):
        try:
            d = Date.fromisoformat(v.strip())
        except ValueError:
            raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다 (예: 2018-09-30)")
        if not (1900 <= d.year <= 2100):
            raise ValueError("날짜는 1900~2100년 사이여야 합니다")
        return d.isoformat()

    @field_validator("value")
    @classmethod
    def _value(cls, v: float):
        if not math.isfinite(v) or abs(v) > 1e12:
            raise ValueError("값은 유한한 숫자여야 합니다")
        return v

    @field_validator("memo")
    @classmethod
    def _memo(cls, v: str):
        return " ".join((v or "").split())      # 줄바꿈·연속 공백 정리


class ChatIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, examples=["2018년 4월 폭설 때 교통량은 얼마나 줄었어?"])

    @field_validator("question")
    @classmethod
    def _q(cls, v: str):
        v = v.strip()
        if not v:
            raise ValueError("질문을 입력하세요")
        return v


# ── 앱 생성 ───────────────────────────────────────────────
def create_app(db_path=None, transport=None) -> FastAPI:
    settings = get_settings()
    db = Database(db_path or settings.db_path)
    app = FastAPI(title="내 데이터를 아는 AI 비서 — 교통량 AI 어시스턴트", version="1.0.0",
                  description="시계열 데이터(date, value, memo) CRUD · 분석 결과 저장 · 데이터 기반 AI 채팅")
    app.state.db, app.state.settings, app.state.transport = db, settings, transport

    def refresh_analysis(trigger: str) -> int:
        rows = db.all_series()
        sm = compute_summary(rows)
        return db.save_snapshot(trigger, len(rows), sm, summary_to_text(sm, DATA_LABEL, DATA_UNIT))

    app.state.refresh_analysis = refresh_analysis

    # 처음 실행 시: 비어 있으면 예시 데이터(I-94 일교통량 803일)를 넣고 분석 결과를 저장
    if not db.list_records(limit=1)[1] and SEED_CSV.exists() and os.getenv("SEED_ON_START", "1") == "1":
        seed = pd.read_csv(SEED_CSV, keep_default_na=False)
        db.bulk_insert([(r.date, float(r.value), r.memo) for r in seed.itertuples()])
        refresh_analysis("seed")
    elif db.latest_snapshot() is None:
        refresh_analysis("startup")

    # ── 상태 ──
    @app.get("/api/health", tags=["상태"])
    def health():
        _, total = db.list_records(limit=1)
        return {"status": "ok", "records": total, "llm_configured": settings.llm_enabled,
                "api_style": settings.api_style, "model": settings.model, "data_label": DATA_LABEL, "unit": DATA_UNIT}

    # ── 데이터 CRUD ──
    @app.get("/api/records", tags=["데이터 관리(CRUD)"])
    def list_records(start: str | None = None, end: str | None = None, q: str | None = Query(None, max_length=50),
                     page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=500), order: str = "desc"):
        rows, total = db.list_records(start, end, q, order, size, (page - 1) * size)
        return {"items": rows, "total": total, "page": page, "size": size, "pages": max(1, math.ceil(total / size))}

    @app.get("/api/records/export.csv", tags=["데이터 관리(CRUD)"])
    def export_csv():
        buf = io.StringIO()
        w = csv.writer(buf); w.writerow(["date", "value", "memo"])
        for r in db.all_series():
            w.writerow([r["date"], r["value"], r["memo"]])
        return StreamingResponse(iter(["﻿" + buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=records.csv"})

    @app.get("/api/records/{rid}", tags=["데이터 관리(CRUD)"])
    def get_record(rid: int):
        r = db.get_record(rid)
        if not r:
            raise HTTPException(404, "해당 기록이 없습니다")
        return r

    @app.post("/api/records", status_code=201, tags=["데이터 관리(CRUD)"])
    def create_record(body: RecordIn):
        if db.get_by_date(body.date):
            raise HTTPException(409, f"{body.date} 기록이 이미 있습니다. 수정 기능을 사용하세요")
        r = db.create_record(body.date, body.value, body.memo)
        return {**r, "snapshot_id": refresh_analysis("create")}

    @app.put("/api/records/{rid}", tags=["데이터 관리(CRUD)"])
    def update_record(rid: int, body: RecordIn):
        if not db.get_record(rid):
            raise HTTPException(404, "해당 기록이 없습니다")
        other = db.get_by_date(body.date)
        if other and other["id"] != rid:
            raise HTTPException(409, f"{body.date} 기록이 이미 있습니다")
        r = db.update_record(rid, body.date, body.value, body.memo)
        return {**r, "snapshot_id": refresh_analysis("update")}

    @app.delete("/api/records/{rid}", tags=["데이터 관리(CRUD)"])
    def delete_record(rid: int):
        if not db.delete_record(rid):
            raise HTTPException(404, "해당 기록이 없습니다")
        return {"deleted": rid, "snapshot_id": refresh_analysis("delete")}

    # ── 시계열 분석 ──
    @app.get("/api/series", tags=["시계열 분석"])
    def series(start: str | None = None, end: str | None = None):
        """차트용: 날짜순 값 + 7일·30일 이동평균(달력 기준) + 메모"""
        rows = db.all_series()
        if not rows:
            return {"items": []}
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        s = df.set_index("date").sort_index()
        s["ma7"] = s["value"].rolling("7D", min_periods=4).mean()
        s["ma30"] = s["value"].rolling("30D", min_periods=15).mean()
        if start:
            s = s[s.index >= start]
        if end:
            s = s[s.index <= end]
        out = s.reset_index()
        out["date"] = out["date"].dt.strftime("%Y-%m-%d")
        out = out.astype(object).where(out.notna(), None)
        return {"items": out[["date", "value", "ma7", "ma30", "memo"]].to_dict("records")}

    @app.get("/api/analysis/latest", tags=["시계열 분석"])
    def analysis_latest():
        return db.latest_snapshot()

    @app.post("/api/analysis/refresh", tags=["시계열 분석"])
    def analysis_refresh():
        sid = refresh_analysis("manual")
        return db.latest_snapshot() | {"id": sid}

    @app.get("/api/analysis/history", tags=["시계열 분석"])
    def analysis_history(limit: int = Query(20, ge=1, le=200)):
        return {"items": db.list_snapshots(limit)}

    # ── AI 채팅 ──
    @app.post("/api/chat", tags=["AI 채팅"])
    def chat(body: ChatIn):
        return answer_question(db, settings, body.question, DATA_LABEL, DATA_UNIT, transport=app.state.transport)

    @app.get("/api/chat/history", tags=["대화 기록"])
    def chat_history(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200), order: str = "desc"):
        rows, total = db.list_chats(size, (page - 1) * size, order)
        return {"items": rows, "total": total, "page": page, "pages": max(1, math.ceil(total / size))}

    @app.delete("/api/chat/history/{cid}", tags=["대화 기록"])
    def chat_delete(cid: int):
        if not db.delete_chat(cid):
            raise HTTPException(404, "해당 대화가 없습니다")
        return {"deleted": cid}

    @app.delete("/api/chat/history", tags=["대화 기록"])
    def chat_clear():
        return {"deleted": db.clear_chats()}

    # ── 화면 ──
    static = ROOT / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static / "index.html")

    return app


app = create_app()
