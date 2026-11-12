"""파이프라인 실행: 수집 → 분석 → 차트 → 리스크 → 종합 → docs/ 에 마크다운 저장."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tomllib

import chart
import collector

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


def _snapshot_md(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        arrow = "🔺" if r["change_pct"] > 0 else "🔻" if r["change_pct"] < 0 else "➖"
        lines.append(f"- **{r['name']}** {r['close']:,} ({arrow} {r['change_pct']:+.2f}%)")
    return "\n".join(lines)


def _news_md(items: list[dict]) -> str:
    return "\n".join(
        f"- [{n['importance']}/10 · {n['sentiment']} · {n['horizon']}] **{n['ko_title']}** "
        f"({', '.join(n['tickers'])}) — {n['ko_summary']} / 이유: {n['why']}"
        for n in items
    )


def _sources_md(items: list[dict]) -> str:
    return "\n".join(
        f"- {n['ko_title']} — [{n['source']}]({n['link']}) · {n['sentiment']} · 중요도 {n['importance']}"
        for n in items
    )


def main(dry_run: bool = False) -> Path:
    cfg = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
    model = cfg["model"]

    # 1) 수집
    news = collector.collect_news(cfg)
    snapshot = collector.collect_market_snapshot(cfg)
    charts = chart.analyze_watchlist(cfg)
    if not news:
        sys.exit("수집된 뉴스가 없습니다. 네트워크/피드 확인 필요.")

    snapshot_md = _snapshot_md(snapshot)
    if dry_run:
        print(snapshot_md)
        print(f"뉴스 {len(news)}건, 차트 {len(charts)}종목 — dry-run이라 LLM 호출 생략")
        return ROOT

    import agents  # LLM 의존성은 dry-run에서 필요 없으므로 지연 import

    # 2) 분석가: 필터/번역/요약
    analyzed = agents.run_analyst(model, news)
    important = sorted(
        (n for n in analyzed if n["importance"] >= cfg["news"]["min_importance"]),
        key=lambda n: n["importance"], reverse=True,
    )
    print(f"[analyst] 중요 뉴스 {len(important)}건 선별")
    news_md = _news_md(important)

    # 3) 차트 트레이더 → 4) 리스크 검토 → 5) 종합
    trader_md = agents.run_trader(model, charts)
    risk_md = agents.run_risk(model, news_md, trader_md)
    body = agents.run_synth(model, snapshot_md, news_md, trader_md, risk_md)

    # 6) 마크다운 조립 & 저장
    now = datetime.now(KST)
    date = now.strftime("%Y-%m-%d")
    report = f"""---
layout: page
title: "{date} 미국 증시 브리핑"
date: {now.strftime('%Y-%m-%d %H:%M:%S +0900')}
---

> 생성 시각 {now.strftime('%Y-%m-%d %H:%M')} KST · 자동 생성 문서이며 **투자 권유가 아닙니다.**

## 시장 스냅샷 (직전 거래일 종가)
{snapshot_md}

{body}

## 차트 분석 (기술적 관점)
{trader_md}

## 반대 시나리오 · 리스크 점검
{risk_md}

## 뉴스 출처
{_sources_md(important)}
"""
    out = ROOT / "docs" / "reports" / f"{date}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"[publisher] 저장 완료: {out}")
    return out


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
