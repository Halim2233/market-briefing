"""수집 에이전트: RSS 뉴스 + 시장 지수 스냅샷을 모은다. (LLM 호출 없음)"""
import calendar
import hashlib
import re
import time
from datetime import datetime, timezone

import feedparser
import yfinance as yf


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def collect_news(cfg: dict) -> list[dict]:
    feeds = list(cfg["feeds"])
    for t in cfg["chart"]["watchlist"]:
        feeds.append({
            "name": f"Yahoo Finance [{t}]",
            "url": f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={t}&region=US&lang=en-US",
        })

    max_age = cfg["news"]["max_age_hours"] * 3600
    now = time.time()
    seen, items = set(), []

    for f in feeds:
        try:
            parsed = feedparser.parse(f["url"])
        except Exception as e:  # 한 피드가 죽어도 계속 진행
            print(f"[collector] {f['name']} 실패: {e}")
            continue
        for e in parsed.entries:
            ts = e.get("published_parsed") or e.get("updated_parsed")
            published = calendar.timegm(ts) if ts else now
            if now - published > max_age:
                continue
            title = _clean(e.get("title", ""))
            if not title:
                continue
            key = hashlib.md5(re.sub(r"\W+", "", title.lower()).encode()).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "source": f["name"],
                "title": title,
                "summary": _clean(e.get("summary", ""))[:400],
                "link": e.get("link", ""),
                "published": datetime.fromtimestamp(published, timezone.utc).isoformat(),
                "_ts": published,
            })

    items.sort(key=lambda x: x["_ts"], reverse=True)
    items = items[: cfg["news"]["max_items_to_analyze"]]
    for i, it in enumerate(items):
        it["id"] = i
    print(f"[collector] 뉴스 {len(items)}건 수집")
    return items


def collect_market_snapshot(cfg: dict) -> list[dict]:
    rows = []
    for symbol, name in cfg["indices"].items():
        try:
            h = yf.Ticker(symbol).history(period="10d")["Close"].dropna()
            last, prev = float(h.iloc[-1]), float(h.iloc[-2])
            rows.append({
                "symbol": symbol, "name": name,
                "close": round(last, 2),
                "change_pct": round((last / prev - 1) * 100, 2),
            })
        except Exception as e:
            print(f"[collector] {symbol} 실패: {e}")
    return rows
