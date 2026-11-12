"""가상 모의투자 엔진 (표준 라이브러리만 사용). 실제 주문/계좌 접속 없음.
사용:
  python -I paper/sim.py init                      # 최초 1회 (이미 있으면 거부)
  python -I paper/sim.py mark                      # 시세 갱신 + portfolio/performance 갱신
  python -I paper/sim.py buy|sell TICKER QTY --reason "..." [--stop P] [--target P]
  python -I paper/sim.py status
규칙은 코드에서 강제: 종목당 20% 상한, 최소 현금 20%, 공매도/레버리지/물타기 금지(보유 중 추가매수 거부),
일 -2% / 누적 -5% 도달 시 신규 매수 거부, 휴장·시세 부재 시 거래 거부."""
import argparse, csv, json, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from datetime import timedelta, tzinfo

D = Path(__file__).resolve().parent
PF, TR, PERF = D / "portfolio.json", D / "trades.csv", D / "performance.json"


class _ET(tzinfo):
    """미국 동부시간 (tzdata 없이): 3월 둘째 일요일 02:00 ~ 11월 첫째 일요일 02:00 서머타임."""
    def _dst(self, dt):
        y = dt.year
        def nth_sun(m, n):
            d = datetime(y, m, 1); d += timedelta(days=(6 - d.weekday()) % 7 + 7 * (n - 1)); return d
        return nth_sun(3, 2).replace(hour=2) <= dt.replace(tzinfo=None) < nth_sun(11, 1).replace(hour=2)
    def utcoffset(self, dt): return timedelta(hours=-4 if self._dst(dt) else -5)
    def dst(self, dt): return timedelta(hours=1 if self._dst(dt) else 0)
    def tzname(self, dt): return "EDT" if self._dst(dt) else "EST"
    def fromutc(self, dt):
        naive = dt.replace(tzinfo=None)
        off = timedelta(hours=-4) if self._dst(naive + timedelta(hours=-4)) else timedelta(hours=-5)
        return (naive + off).replace(tzinfo=self)


ET = _ET()
INITIAL = 10_000.0
MAX_POS, MIN_CASH = 0.20, 0.20
SLIP_BPS = 5          # 가정: 대형주/ETF 편도 슬리피지 0.05%
COMMISSION = 0.0      # 가정: 수수료 $0 (미국 온라인 브로커 일반)
SITE = D.parent / "docs" / "paper"   # GitHub Pages 공개용 사본


def sync():
    """기록 파일을 docs/paper/ 로 복사 (원본은 paper/ — 페이지는 읽기 전용 사본만 본다)."""
    (SITE / "data").mkdir(parents=True, exist_ok=True)
    for n in ("portfolio.json", "performance.json", "trades.csv"):
        if (D / n).exists():
            (SITE / "data" / n).write_bytes((D / n).read_bytes())
    for src, dst, title in (("daily_report.md", "daily.md", "일일 보고서"), ("investment_strategy.md", "strategy.md", "투자 전략")):
        body = (D / src).read_text(encoding="utf-8")
        head = "---" + chr(10) + "layout: page" + chr(10) + 'title: "' + title + '"' + chr(10) + "---" + chr(10)
        (SITE / dst).write_text(head + body, encoding="utf-8")


COLS = ["datetime_et", "ticker", "side", "qty", "market_price", "fill_price", "amount", "commission",
        "est_slippage", "cash_after", "price_source", "price_time_et", "reason", "stop", "target", "realized_pnl"]


def quote(sym):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=1d&interval=1m"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    m = json.loads(urllib.request.urlopen(req, timeout=20).read())["chart"]["result"][0]["meta"]
    t = datetime.fromtimestamp(m["regularMarketTime"], timezone.utc).astimezone(ET)
    p = m["currentTradingPeriod"]["regular"]
    open_now = p["start"] <= datetime.now(timezone.utc).timestamp() <= p["end"]
    return {"price": float(m["regularMarketPrice"]), "time": t, "regular_open": open_now,
            "prev_close": m.get("chartPreviousClose"), "source": "Yahoo Finance chart API (지연/비공식 가능)"}


def load():
    return json.loads(PF.read_text(encoding="utf-8"))


def save(pf):
    PF.write_text(json.dumps(pf, ensure_ascii=False, indent=2), encoding="utf-8")


def equity(pf):
    return pf["cash"] + sum(h["qty"] * h["last_price"] for h in pf["holdings"].values())


def cmd_init(a):
    if PF.exists():
        raise SystemExit("이미 초기화됨 — 기록 변조 방지를 위해 재초기화 거부")
    now = datetime.now(ET).isoformat(timespec="seconds")
    save({"initial_capital": INITIAL, "cash": INITIAL, "holdings": {}, "total_equity": INITIAL,
          "created_et": now, "start_date_et": None, "benchmark": {"symbol": "SPY", "start_price": None},
          "day_start_equity": INITIAL, "day_start_date": None, "halt_buys": False, "last_update_et": now})
    with TR.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(COLS)
    PERF.write_text(json.dumps({"equity_curve": []}, indent=2), encoding="utf-8")
    sync(); print("초기화 완료 (거래 없음)")


def cmd_mark(a):
    pf = load()
    for s, h in pf["holdings"].items():
        h["last_price"] = quote(s)["price"]
    q = quote("SPY")
    now = datetime.now(ET)
    today = now.date().isoformat()
    if pf["day_start_date"] != today:
        pf["day_start_date"], pf["day_start_equity"] = today, equity(pf)
    pf["total_equity"] = round(equity(pf), 2)
    pf["last_update_et"] = now.isoformat(timespec="seconds")
    perf = json.loads(PERF.read_text(encoding="utf-8"))
    spy0 = pf["benchmark"]["start_price"]
    perf["equity_curve"].append({"time_et": pf["last_update_et"], "equity": pf["total_equity"],
                                 "spy": q["price"], "price_time_et": q["time"].isoformat(timespec="seconds")})
    eq = [p["equity"] for p in perf["equity_curve"]]
    peak, mdd = 0, 0
    for v in eq:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    ret = pf["total_equity"] / INITIAL - 1
    day = pf["total_equity"] / pf["day_start_equity"] - 1 if pf["day_start_equity"] else 0
    pf["halt_buys"] = ret <= -0.05 or (pf["day_start_equity"] - pf["total_equity"]) >= 0.02 * INITIAL
    perf.update({"cumulative_return_pct": round(ret * 100, 3), "today_return_pct": round(day * 100, 3),
                 "mdd_pct_snapshot_based": round(mdd * 100, 3),
                 "spy_return_pct": round((q["price"] / spy0 - 1) * 100, 3) if spy0 else None,
                 "excess_vs_spy_pct": round((ret - (q["price"] / spy0 - 1)) * 100, 3) if spy0 else None,
                 "cash_ratio_pct": round(pf["cash"] / pf["total_equity"] * 100, 2), "halt_buys": pf["halt_buys"],
                 "note": "MDD는 mark 호출 시점 스냅샷 기준(장중 변동 미반영)"})
    save(pf); PERF.write_text(json.dumps(perf, ensure_ascii=False, indent=2), encoding="utf-8"); sync()
    print(f"평가자산 ${pf['total_equity']:,.2f} 누적 {ret*100:+.2f}% 금일 {day*100:+.2f}% 현금 {pf['cash']/pf['total_equity']*100:.1f}% 신규매수중단={pf['halt_buys']}")


def cmd_trade(a):
    pf = load(); side = a.cmd.upper(); sym = a.ticker.upper(); a.qty = int(a.qty)
    if a.qty <= 0 or a.qty != int(a.qty):
        raise SystemExit("수량은 양의 정수")
    q = quote(sym)
    if a.at_close:
        # 사용자 지시 백테스트성 체결: 정규장 밖에서 직전 정규장 종가로 가정 체결. 기록에 명시한다.
        if q["regular_open"]:
            raise SystemExit("정규장 중에는 --at-close 사용 불가")
        q["source"] = "Yahoo Finance 직전 정규장 종가 — 장외 가정 체결(사용자 지시, 실제 체결 아님)"
        a.reason = "[종가 가정 체결] " + a.reason
    elif not q["regular_open"]:
        raise SystemExit(f"정규장 아님 — 거래 거부 (시세 시각 {q['time']})")
    elif (datetime.now(ET) - q["time"]).total_seconds() > 900:
        raise SystemExit("시세가 15분 이상 지연 — 데이터 불확실, 거래 보류")
    mp = q["price"]; slip = mp * SLIP_BPS / 1e4
    fill = round(mp + slip if side == "BUY" else mp - slip, 4)
    amt = round(fill * a.qty, 2); realized = ""
    if side == "BUY":
        if pf["halt_buys"]:
            raise SystemExit("리스크 규칙: 신규 매수 중단 상태")
        if sym in pf["holdings"]:
            raise SystemExit("규칙: 보유 종목 추가매수(물타기) 금지 — 필요 시 전략 변경 이력에 사유 기록 후 수동 해제")
        eq = equity(pf)
        if amt > pf["cash"] - COMMISSION: raise SystemExit("현금 부족(레버리지 금지)")
        if amt > MAX_POS * eq: raise SystemExit(f"종목 한도 {MAX_POS:.0%} 초과")
        if pf["cash"] - amt < MIN_CASH * eq: raise SystemExit(f"최소 현금 {MIN_CASH:.0%} 위반")
        pf["cash"] = round(pf["cash"] - amt - COMMISSION, 2)
        pf["holdings"][sym] = {"qty": a.qty, "avg_price": fill, "last_price": mp, "stop": a.stop, "target": a.target,
                               "opened_et": datetime.now(ET).isoformat(timespec="seconds")}
        if pf["start_date_et"] is None:
            spy = quote("SPY")
            pf["start_date_et"] = datetime.now(ET).date().isoformat()
            pf["benchmark"]["start_price"] = spy["price"]; pf["benchmark"]["start_time_et"] = spy["time"].isoformat()
    else:
        h = pf["holdings"].get(sym)
        if not h or a.qty > h["qty"]: raise SystemExit("보유 수량 초과 매도(공매도 금지)")
        realized = round((fill - h["avg_price"]) * a.qty - COMMISSION, 2)
        pf["cash"] = round(pf["cash"] + amt - COMMISSION, 2)
        h["qty"] -= a.qty
        if h["qty"] == 0: del pf["holdings"][sym]
    pf["total_equity"] = round(equity(pf), 2)
    with TR.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([datetime.now(ET).isoformat(timespec="seconds"), sym, side, a.qty, mp, fill, amt,
                                COMMISSION, round(slip * a.qty, 2), pf["cash"], q["source"],
                                q["time"].isoformat(timespec="seconds"), a.reason, a.stop or "", a.target or "", realized])
    save(pf); sync()
    print(f"{side} {sym} x{a.qty} 시장가 {mp} 체결가 {fill} 금액 ${amt:,.2f} 잔액 ${pf['cash']:,.2f}")


def cmd_status(a):
    print(json.dumps(load(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(); sp = p.add_subparsers(dest="cmd", required=True)
    for n, f in (("init", cmd_init), ("mark", cmd_mark), ("sync", lambda a: sync()), ("status", cmd_status)):
        sp.add_parser(n).set_defaults(fn=f)
    for n in ("buy", "sell"):
        s = sp.add_parser(n); s.set_defaults(fn=cmd_trade)
        s.add_argument("ticker"); s.add_argument("qty", type=float); s.add_argument("--reason", required=True)
        s.add_argument("--at-close", action="store_true"); s.add_argument("--stop", type=float); s.add_argument("--target", type=float)
    a = p.parse_args(); a.fn(a)
