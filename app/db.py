"""SQLite 데이터베이스 — 테이블 생성과 CRUD.

테이블
  records            : 사용자의 시계열 데이터 (date, value, memo)       ← CRUD 대상
  analysis_snapshots : 분석 결과(요약) 저장 이력                        ← AI 답변의 근거
  chat_messages      : 대화 기록 (질문·답변·사용한 근거·모드)

모든 SQL은 ? 자리표시자(파라미터 바인딩)를 써서 SQL 인젝션을 막는다.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT    NOT NULL UNIQUE,          -- YYYY-MM-DD, 하루에 1건
    value      REAL    NOT NULL,
    memo       TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_date ON records(date);

CREATE TABLE IF NOT EXISTS analysis_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT    NOT NULL,
    trigger      TEXT    NOT NULL,              -- seed / create / update / delete / manual
    record_count INTEGER NOT NULL,
    summary_json TEXT    NOT NULL,
    summary_text TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    question    TEXT    NOT NULL,
    answer      TEXT    NOT NULL,
    mode        TEXT    NOT NULL,               -- ai / fallback
    model       TEXT    NOT NULL DEFAULT '',
    snapshot_id INTEGER,
    context     TEXT    NOT NULL DEFAULT '',    -- AI에게 보낸 데이터 근거
    latency_ms  INTEGER NOT NULL DEFAULT 0,
    error       TEXT    NOT NULL DEFAULT ''
);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ── records CRUD ─────────────────────────────────────
    def list_records(self, start=None, end=None, q=None, order="desc", limit=None, offset=0):
        sql, args = "SELECT * FROM records WHERE 1=1", []
        if start:
            sql += " AND date >= ?"; args.append(start)
        if end:
            sql += " AND date <= ?"; args.append(end)
        if q:
            sql += " AND memo LIKE ?"; args.append(f"%{q}%")
        count_sql = sql.replace("SELECT *", "SELECT COUNT(*)", 1)
        sql += f" ORDER BY date {'ASC' if order == 'asc' else 'DESC'}"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"; args2 = args + [int(limit), int(offset)]
        else:
            args2 = args
        with self.conn() as c:
            total = c.execute(count_sql, args).fetchone()[0]
            rows = [dict(r) for r in c.execute(sql, args2).fetchall()]
        return rows, total

    def get_record(self, rid: int):
        with self.conn() as c:
            r = c.execute("SELECT * FROM records WHERE id = ?", (rid,)).fetchone()
        return dict(r) if r else None

    def get_by_date(self, date: str):
        with self.conn() as c:
            r = c.execute("SELECT * FROM records WHERE date = ?", (date,)).fetchone()
        return dict(r) if r else None

    def create_record(self, date: str, value: float, memo: str = ""):
        t = now()
        with self.conn() as c:
            cur = c.execute("INSERT INTO records(date, value, memo, created_at, updated_at) VALUES (?,?,?,?,?)",
                            (date, value, memo, t, t))
            rid = cur.lastrowid
        return self.get_record(rid)

    def update_record(self, rid: int, date: str, value: float, memo: str):
        with self.conn() as c:
            c.execute("UPDATE records SET date=?, value=?, memo=?, updated_at=? WHERE id=?",
                      (date, value, memo, now(), rid))
        return self.get_record(rid)

    def delete_record(self, rid: int) -> bool:
        with self.conn() as c:
            cur = c.execute("DELETE FROM records WHERE id = ?", (rid,))
        return cur.rowcount > 0

    def bulk_insert(self, rows):
        t = now()
        with self.conn() as c:
            c.executemany("INSERT OR IGNORE INTO records(date, value, memo, created_at, updated_at) VALUES (?,?,?,?,?)",
                          [(d, v, m, t, t) for d, v, m in rows])

    def all_series(self):
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT date, value, memo FROM records ORDER BY date").fetchall()]

    # ── analysis snapshots ───────────────────────────────
    def save_snapshot(self, trigger: str, record_count: int, summary: dict, text: str):
        with self.conn() as c:
            cur = c.execute("INSERT INTO analysis_snapshots(created_at, trigger, record_count, summary_json, summary_text)"
                            " VALUES (?,?,?,?,?)", (now(), trigger, record_count, json.dumps(summary, ensure_ascii=False), text))
            return cur.lastrowid

    def latest_snapshot(self):
        with self.conn() as c:
            r = c.execute("SELECT * FROM analysis_snapshots ORDER BY id DESC LIMIT 1").fetchone()
        if not r:
            return None
        d = dict(r); d["summary"] = json.loads(d.pop("summary_json"))
        return d

    def list_snapshots(self, limit=20):
        with self.conn() as c:
            rows = c.execute("SELECT id, created_at, trigger, record_count FROM analysis_snapshots"
                             " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ── chat messages ────────────────────────────────────
    def save_chat(self, **kw):
        cols = ["created_at", "question", "answer", "mode", "model", "snapshot_id", "context", "latency_ms", "error"]
        kw.setdefault("created_at", now())
        with self.conn() as c:
            cur = c.execute(f"INSERT INTO chat_messages({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                            [kw.get(k, "" if k not in ("snapshot_id", "latency_ms") else None) for k in cols])
            rid = cur.lastrowid
            return dict(c.execute("SELECT * FROM chat_messages WHERE id=?", (rid,)).fetchone())

    def list_chats(self, limit=50, offset=0, order="desc"):
        with self.conn() as c:
            total = c.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
            rows = c.execute(f"SELECT * FROM chat_messages ORDER BY id {'ASC' if order == 'asc' else 'DESC'}"
                             " LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return [dict(r) for r in rows], total

    def delete_chat(self, cid: int) -> bool:
        with self.conn() as c:
            return c.execute("DELETE FROM chat_messages WHERE id=?", (cid,)).rowcount > 0

    def clear_chats(self) -> int:
        with self.conn() as c:
            return c.execute("DELETE FROM chat_messages").rowcount
