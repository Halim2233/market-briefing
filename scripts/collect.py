"""표준 라이브러리만 사용하는 수집 스크립트 (pandas 등 외부 패키지 불필요).
뉴스 RSS + 지수 스냅샷 + 종목별 차트 지표를 모아 data/YYYY-MM-DD.json 으로 저장한다.
실행:  python -I scripts/collect.py
LLM 분석은 하지 않는다 — 그 부분은 Claude Code 세션(/briefing)이 담당."""
import hashlib
import json
import re
import time
import tomllib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (market-briefing)"}


def http_get(url: str, timeout: int = 20) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


# ───────────────────────── 뉴스 ─────────────────────────
def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _parse_feed(feed: dict) -> list[dict]:
    try:
        root = ET.fromstring(http_get(feed["url"]))
    except Exception as e:
        print(f"[news] {feed['name']} 실패: {e}")
        return []
    out = []
    for it in root.iter("item"):
        title = _clean(it.findtext("title", ""))
        if not title:
            continue
        try:
            ts = parsedate_to_datetime(it.findtext("pubDate", "")).timestamp()
        except Exception:
            ts = time.time()
        out.append({
            "source": feed["name"], "title": title,
            "summary": _clean(it.findtext("description", ""))[:400],
            "link": it.findtext("link", ""), "_ts": ts,
        })
    return out


def collect_news(cfg: dict) -> list[dict]:
    feeds = list(cfg["feeds"])
    for t in cfg["chart"]["watchlist"] + cfg["chart"].get("semis", []):
        feeds.append({"name": f"Yahoo Finance [{t}]",
                      "url": f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={t}&region=US&lang=en-US"})
    with ThreadPoolExecutor(8) as ex:
        batches = list(ex.map(_parse_feed, feeds))

    max_age, now = cfg["news"]["max_age_hours"] * 3600, time.time()
    seen, items = set(), []
    for it in (i for b in batches for i in b):
        if now - it["_ts"] > max_age:
            continue
        key = hashlib.md5(re.sub(r"\W+", "", it["title"].lower()).encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        items.append(it)
    items.sort(key=lambda x: x["_ts"], reverse=True)
    items = items[: cfg["news"]["max_items_to_analyze"]]
    for i, it in enumerate(items):
        it["id"] = i
        it["published"] = datetime.fromtimestamp(it.pop("_ts"), timezone.utc).isoformat()
    print(f"[news] {len(items)}건")
    return items


# ───────────────────────── 시세 / 지표 ─────────────────────────
def fetch_ohlcv(symbol: str, rng: str = "1y") -> dict | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range={rng}&interval=1d"
    try:
        r = json.loads(http_get(url))["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
        rows = [(o, h, l, c, v) for o, h, l, c, v in
                zip(q["open"], q["high"], q["low"], q["close"], q["volume"]) if None not in (o, h, l, c)]
        return {k: [row[i] for row in rows] for i, k in enumerate(["open", "high", "low", "close", "volume"])}
    except Exception as e:
        print(f"[quote] {symbol} 실패: {e}")
        return None


def sma(x, n):
    return sum(x[-n:]) / n if len(x) >= n else None


def ema_series(x, span):
    a, out = 2 / (span + 1), [x[0]]
    for v in x[1:]:
        out.append(a * v + (1 - a) * out[-1])
    return out


def rsi(close, n=14):
    up = down = None
    a = 1 / n
    for i in range(1, len(close)):
        d = close[i] - close[i - 1]
        u, dn = max(d, 0), max(-d, 0)
        up = u if up is None else a * u + (1 - a) * up
        down = dn if down is None else a * dn + (1 - a) * down
    return 100.0 if not down else 100 - 100 / (1 + up / down)


def candle_patterns(d: dict) -> list[str]:
    o, h, l, c = d["open"], d["high"], d["low"], d["close"]
    body, rng = abs(c[-1] - o[-1]), max(h[-1] - l[-1], 1e-9)
    upper, lower = h[-1] - max(c[-1], o[-1]), min(c[-1], o[-1]) - l[-1]
    found = []
    if body / rng < 0.1:
        found.append("도지(Doji): 매수·매도 힘 균형, 추세 전환 가능성")
    if body > 0 and lower > body * 2 and upper < body * 0.5:
        found.append("망치형(Hammer): 하락 후 나오면 반등 신호 후보")
    if body > 0 and upper > body * 2 and lower < body * 0.5:
        found.append("유성형(Shooting Star): 상승 후 나오면 하락 반전 후보")
    if c[-2] < o[-2] and c[-1] > o[-1] and c[-1] >= o[-2] and o[-1] <= c[-2]:
        found.append("상승장악형(Bullish Engulfing)")
    if c[-2] > o[-2] and c[-1] < o[-1] and c[-1] <= o[-2] and o[-1] >= c[-2]:
        found.append("하락장악형(Bearish Engulfing)")
    return found


def analyze(symbol: str) -> dict | None:
    d = fetch_ohlcv(symbol)
    if not d or len(d["close"]) < 60:
        return None
    c, v = d["close"], d["volume"]
    macd = [a - b for a, b in zip(ema_series(c, 12), ema_series(c, 26))]
    sig = ema_series(macd, 9)
    r = lambda x: None if x is None else round(x, 2)
    vol20 = sum(v[-20:]) / 20
    return {
        "symbol": symbol, "close": r(c[-1]),
        "change_pct_1d": r((c[-1] / c[-2] - 1) * 100), "change_pct_1m": r((c[-1] / c[-21] - 1) * 100),
        "sma20": r(sma(c, 20)), "sma50": r(sma(c, 50)), "sma200": r(sma(c, 200)),
        "rsi14": r(rsi(c)), "macd": r(macd[-1]), "macd_signal": r(sig[-1]),
        "volume_vs_20d_avg": r(v[-1] / vol20) if vol20 else None,
        "support_20d_low": r(min(d["low"][-20:])), "resistance_20d_high": r(max(d["high"][-20:])),
        "high_52w": r(max(d["high"])), "low_52w": r(min(d["low"])),
        "candle_patterns_today": candle_patterns(d),
        "last_10_closes": [r(x) for x in c[-10:]],
    }


def snapshot(symbol: str, name: str) -> dict | None:
    d = fetch_ohlcv(symbol, "10d")
    if not d or len(d["close"]) < 2:
        return None
    c = d["close"]
    return {"symbol": symbol, "name": name, "close": round(c[-1], 2),
            "change_pct": round((c[-1] / c[-2] - 1) * 100, 2)}


def main():
    cfg = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
    with ThreadPoolExecutor(8) as ex:
        snaps = list(ex.map(lambda kv: snapshot(*kv), cfg["indices"].items()))
        charts = list(ex.map(analyze, cfg["chart"]["watchlist"]))
        semis = list(ex.map(analyze, cfg["chart"].get("semis", [])))
    news = collect_news(cfg)
    now = datetime.now(KST)
    data = {
        "generated_at_kst": now.strftime("%Y-%m-%d %H:%M"),
        "snapshot": [s for s in snaps if s],
        "charts": [c for c in charts if c],
        "semis": [c for c in semis if c],
        "news": news,
    }
    out = ROOT / "data" / f"{now:%Y-%m-%d}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[done] 스냅샷 {len(data['snapshot'])}, 차트 {len(data['charts'])}종목, 반도체 {len(data['semis'])}종목, 뉴스 {len(news)}건 → {out}")


if __name__ == "__main__":
    main()
