"""시계열 분석 — DB의 (date, value, memo)로 요약 통계를 계산한다.

계산 결과(summary dict)는 analysis_snapshots 테이블에 저장되고,
AI 채팅에서 '데이터 근거'로 프롬프트에 들어간다(summary_to_text).
"""
from __future__ import annotations

import math
from datetime import date as Date

import pandas as pd

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def _r(x, n=1):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), n)


def _row(s: pd.DataFrame, idx):
    r = s.loc[idx]
    return {"date": idx.strftime("%Y-%m-%d"), "value": _r(r["value"]), "memo": r["memo"]}


def compute_summary(rows: list[dict]) -> dict:
    """rows: [{'date': 'YYYY-MM-DD', 'value': float, 'memo': str}, ...]"""
    if not rows:
        return {"count": 0}
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    s = df.sort_values("date").set_index("date")
    v = s["value"]

    out = {
        "count": int(len(s)),
        "start": s.index.min().strftime("%Y-%m-%d"),
        "end": s.index.max().strftime("%Y-%m-%d"),
        "mean": _r(v.mean()), "median": _r(v.median()), "std": _r(v.std()) if len(v) > 1 else 0.0,
        "min": _row(s, v.idxmin()), "max": _row(s, v.idxmax()),
        "latest": _row(s, s.index.max()),
    }
    span = (s.index.max() - s.index.min()).days + 1
    out["calendar_days"] = int(span)
    out["missing_days"] = int(span - len(s))

    # ── 최근 흐름: 마지막 날짜 기준 달력 7일·30일 이동평균, 직전 30일 대비 변화율 ──
    end = s.index.max()
    last7 = v[v.index > end - pd.Timedelta(days=7)]
    last30 = v[v.index > end - pd.Timedelta(days=30)]
    prev30 = v[(v.index <= end - pd.Timedelta(days=30)) & (v.index > end - pd.Timedelta(days=60))]
    out["last7_avg"] = _r(last7.mean())
    out["last30_avg"] = _r(last30.mean())
    out["prev30_avg"] = _r(prev30.mean()) if len(prev30) else None
    out["change_30d_pct"] = _r((last30.mean() / prev30.mean() - 1) * 100, 2) if len(prev30) else None

    # 전년 같은 기간(최근 30일) 대비
    ly = v[(v.index > end - pd.Timedelta(days=365 + 30)) & (v.index <= end - pd.Timedelta(days=365))]
    out["yoy_30d_pct"] = _r((last30.mean() / ly.mean() - 1) * 100, 2) if len(ly) >= 10 else None

    # ── 추세: 최근 90일 선형 회귀 기울기 (하루당 변화량) ──
    recent = v[v.index > end - pd.Timedelta(days=90)]
    if len(recent) >= 10:
        x = (recent.index - recent.index.min()).days.to_numpy(dtype=float)
        y = recent.to_numpy(dtype=float)
        xm, ym = x.mean(), y.mean()
        slope = float(((x - xm) * (y - ym)).sum() / ((x - xm) ** 2).sum())
        monthly_change_pct = slope * 30 / ym * 100 if ym else 0.0
        out["trend_90d"] = {"slope_per_day": _r(slope, 2), "per_month_pct": _r(monthly_change_pct, 2),
                            "direction": "증가" if monthly_change_pct > 1 else ("감소" if monthly_change_pct < -1 else "보합")}
    else:
        out["trend_90d"] = None

    # ── 요일별 평균 (계절성: 1주 주기) ──
    wd = v.groupby(v.index.dayofweek).mean()
    out["weekday_avg"] = {WEEKDAYS[i]: _r(wd[i]) for i in wd.index}
    if len(wd):
        out["weekday_high"] = WEEKDAYS[int(wd.idxmax())]
        out["weekday_low"] = WEEKDAYS[int(wd.idxmin())]

    # ── 월별 평균 (최근 12개월) ──
    m = v.resample("MS").agg(["mean", "count"]).dropna()
    m = m[m["count"] > 0].tail(12)
    out["monthly"] = [{"month": i.strftime("%Y-%m"), "avg": _r(r["mean"]), "count": int(r["count"])} for i, r in m.iterrows()]

    # ── 이상치: 같은 요일 평균에서 2.5 표준편차 이상 벗어난 날 (요일 효과를 빼고 판단) ──
    g = v.groupby(v.index.dayofweek)
    z = (v - g.transform("mean")) / g.transform("std").replace(0, float("nan"))
    an = z[z.abs() > 2.5].sort_values(key=lambda t: -t.abs()).head(10)
    out["anomalies"] = [{**_row(s, i), "z": _r(an[i], 2)} for i in an.index]

    # ── 메모가 있는 최근 기록 ──
    memo = s[s["memo"].str.strip() != ""].tail(10)
    out["recent_memos"] = [_row(s, i) for i in memo.index]
    return out


def summary_to_text(sm: dict, label: str, unit: str) -> str:
    """AI 프롬프트에 넣을 짧은 한국어 요약 (토큰 절약을 위해 핵심만)."""
    if not sm or sm.get("count", 0) == 0:
        return f"[데이터 요약] {label}: 저장된 데이터가 없습니다."
    f = lambda x: "없음" if x is None else f"{x:,.0f}"
    L = [f"[데이터 요약] {label} (단위: {unit})",
         f"- 기간: {sm['start']} ~ {sm['end']}, 기록 {sm['count']}건 (달력 {sm['calendar_days']}일 중 빈 날 {sm['missing_days']}일)",
         f"- 전체 평균 {f(sm['mean'])}, 중앙값 {f(sm['median'])}, 표준편차 {f(sm['std'])}",
         f"- 최고 {f(sm['max']['value'])} ({sm['max']['date']}{', ' + sm['max']['memo'] if sm['max']['memo'] else ''}), "
         f"최저 {f(sm['min']['value'])} ({sm['min']['date']}{', ' + sm['min']['memo'] if sm['min']['memo'] else ''})",
         f"- 가장 최근: {sm['latest']['date']} = {f(sm['latest']['value'])}{' (' + sm['latest']['memo'] + ')' if sm['latest']['memo'] else ''}",
         f"- 최근 7일 평균 {f(sm['last7_avg'])}, 최근 30일 평균 {f(sm['last30_avg'])}, 직전 30일 평균 {f(sm['prev30_avg'])}"
         + (f" → 변화율 {sm['change_30d_pct']:+.2f}%" if sm.get("change_30d_pct") is not None else ""),
         ]
    if sm.get("yoy_30d_pct") is not None:
        L.append(f"- 최근 30일 평균의 전년 같은 기간 대비 변화율 {sm['yoy_30d_pct']:+.2f}%")
    if sm.get("trend_90d"):
        t = sm["trend_90d"]
        L.append(f"- 최근 90일 추세: {t['direction']} (하루 {t['slope_per_day']:+,.1f}, 한 달 환산 {t['per_month_pct']:+.2f}%)")
    if sm.get("weekday_avg"):
        L.append("- 요일별 평균: " + ", ".join(f"{k} {f(v)}" for k, v in sm["weekday_avg"].items())
                 + f" (가장 높은 요일 {sm['weekday_high']}, 가장 낮은 요일 {sm['weekday_low']})")
    if sm.get("monthly"):
        L.append("- 최근 월별 평균: " + ", ".join(f"{m['month']} {f(m['avg'])}" for m in sm["monthly"]))
    if sm.get("anomalies"):
        L.append("- 이상치(같은 요일 평균에서 크게 벗어난 날): " + "; ".join(
            f"{a['date']} {f(a['value'])} (z={a['z']:+.1f}{', ' + a['memo'] if a['memo'] else ''})" for a in sm["anomalies"][:6]))
    if sm.get("recent_memos"):
        L.append("- 메모가 있는 최근 기록: " + "; ".join(f"{m['date']} {f(m['value'])} '{m['memo']}'" for m in sm["recent_memos"][-6:]))
    return "\n".join(L)


def weekday_name(d: str) -> str:
    return WEEKDAYS[Date.fromisoformat(d).weekday()]
