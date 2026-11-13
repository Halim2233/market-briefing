"""가상 모의투자 엔진 (표준 라이브러리만 사용). 실제 주문/계좌 접속 없음.
사용:
  python -I paper/sim.py init                      # 최초 1회 (이미 있으면 거부)
  python -I paper/sim.py mark                      # 시세 갱신 + portfolio/performance 갱신
  python -I paper/sim.py buy|sell TICKER QTY --reason "..." [--stop P] [--target P]
  python -I paper/sim.py status
규칙은 코드에서 강제: 종목당 20% 상한, 최소 현금 20%, 공매도/레버리지/물타기 금지(보유 중 추가매수 거부),
일 -2% / 누적 -5% 도달 시 신규 매수 거부, 휴장·시세 부재 시 거래 거부."""
import argparse, csv, json, os, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from datetime import timedelta, tzinfo

D = Path(os.environ.get("PAPER_DIR") or Path(__file__).resolve().parent)   # PAPER_DIR: 테스트용 격리 경로
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


def _inline(t):
    import html, re
    t = html.escape(t.strip(), quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"[*][*]([^*]+)[*][*]", r"<strong>\1</strong>", t)
    return re.sub(r"(?<![\w*])[*]([^*]+)[*](?![\w*])", r"<em>\1</em>", t)


def md_tables_to_html(md):
    """GitHub Pages의 kramdown이 파이프 표를 인식하지 못해 표를 HTML로 직접 변환한다."""
    out, rows = [], []

    def flush():
        if rows:
            th = "".join("<th>%s</th>" % _inline(c) for c in rows[0])
            tr = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % _inline(c) for c in r) for r in rows[2:])
            out.append('<div class="tblwrap"><table class="tbl"><tr>%s</tr>%s</table></div>' % (th, tr))
            rows.clear()

    for line in md.split(chr(10)):
        if line.strip().startswith("|"):
            rows.append(line.strip().strip("|").split("|"))
        else:
            flush()
            out.append(line)
    flush()
    return chr(10).join(out)


def sync():
    """기록 파일을 docs/paper/ 로 복사 (원본은 paper/ — 페이지는 읽기 전용 사본만 본다)."""
    (SITE / "data").mkdir(parents=True, exist_ok=True)
    for n in ("portfolio.json", "performance.json", "trades.csv"):
        if (D / n).exists():
            (SITE / "data" / n).write_bytes((D / n).read_bytes())
    for src, dst, title in (("daily_report.md", "daily.md", "일일 보고서"), ("investment_strategy.md", "strategy.md", "투자 전략")):
        body = md_tables_to_html((D / src).read_text(encoding="utf-8"))
        slug = dst[:-3]
        css = '<link rel="stylesheet" href="{{ "/assets/paper.css" | relative_url }}">'
        head = chr(10).join(["---", "layout: page", 'title: "' + title + '"', "permalink: /paper/" + slug + "/", "---", css, "", ""])
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
    perf = json.loads(PERF.read_text(encoding="utf-8"))
    # 금일 손익 기준 = 직전 거래일(시세 기준일 이전) 마지막 기록의 자산. 없으면 초기 자산.
    session = q["time"].date().isoformat()
    prior = [p for p in perf["equity_curve"] if p["price_time_et"][:10] < session]
    pf["day_start_date"] = session
    pf["day_start_equity"] = prior[-1]["equity"] if prior else INITIAL
    pf["total_equity"] = round(equity(pf), 2)
    pf["last_update_et"] = now.isoformat(timespec="seconds")
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
    if side == "BUY":
        try:
            js = (D.parent / "docs" / "assets" / "paper.js").read_text(encoding="utf-8")
        except OSError:
            js = '"%s":' % sym
        if '"%s":' % sym not in js and (sym + ":") not in js:
            print(f"[경고] {sym} 한글 이름이 docs/assets/paper.js 의 KO 목록에 없음 — 같은 커밋에 추가할 것 (CLAUDE.md 규칙)")
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


def _rule_actions(pf):
    """규칙 기반 매도 판단 (LLM 없음). 종가 ≤ 손절 → 전량, 종가 ≥ 목표 → 절반(1주면 전량)."""
    acts = []
    for s, h in pf["holdings"].items():
        px = h["last_price"]
        if h.get("stop") and px <= h["stop"]:
            acts.append((s, h["qty"], f"손절 규칙: 종가 {px:.2f} ≤ 손절가 {h['stop']}", "stop"))
        elif h.get("target") and px >= h["target"]:
            acts.append((s, max(1, h["qty"] // 2), f"목표가 규칙: 종가 {px:.2f} ≥ 목표가 {h['target']} (절반 이익 실현)", "target"))
    return acts


def cmd_autorun(a):
    """마감 후 자동 점검: 평가 → 손절/목표가 규칙 매도 → 일일 보고서 기록 → 동기화. 신규 매매 판단은 scripts/gemini_trader.py."""
    q = quote("SPY")
    if q["regular_open"]:
        print("정규장 진행 중 — 자동 점검 건너뜀"); return
    session = q["time"].date().isoformat()
    pf = load()
    if pf.get("last_auto_session") == session:
        print(f"{session} 거래일은 이미 처리됨(휴장/중복 실행) — 건너뜀"); return
    if a.dry_run:
        for s, h in pf["holdings"].items():
            h["last_price"] = quote(s)["price"]
        print(f"[dry-run] 거래일 {session}, 매도 예정:", _rule_actions(pf) or "없음"); return
    cmd_mark(a)
    pf = load()
    done = []
    for sym, qty, why, kind in _rule_actions(pf):
        t = argparse.Namespace(cmd="sell", ticker=sym, qty=qty, reason=why, at_close=True, stop=None, target=None)
        cmd_trade(t)
        done.append(f"{sym} {qty}주 매도 — {why}")
        if kind == "target":   # 같은 목표가로 매일 반복 매도되지 않도록 잔여분 목표 해제(손절은 유지, 사용자 재검토 대상)
            pf2 = load()
            if sym in pf2["holdings"]:
                pf2["holdings"][sym]["target"] = None; save(pf2)
    pf = load()
    perf = json.loads(PERF.read_text(encoding="utf-8"))
    eq, ret = pf["total_equity"], (pf["total_equity"] / INITIAL - 1) * 100
    L = [f"\n## {session} (거래일) — 마감 후 자동 점검",
         f"> 규칙 기반 자동 기록입니다(LLM 판단 없음). 시세: Yahoo Finance 종가 (SPY 기준 시각 {q['time'].isoformat(timespec='minutes')}), 갱신 {pf['last_update_et']}. 신규 매수·매도 판단은 아래 '자동 매매 계획' 단계에서 별도로 기록합니다.",
         f"- **포트폴리오:** 총자산 ${eq:,.2f} / 현금 ${pf['cash']:,.2f} ({pf['cash']/eq*100:.1f}%) / 누적 {ret:+.2f}% / 금일 {perf.get('today_return_pct')}%",
         f"- **SPY 대비:** SPY {perf.get('spy_return_pct')}% · 초과 {perf.get('excess_vs_spy_pct')}%p · MDD(스냅샷) {perf.get('mdd_pct_snapshot_based')}%"]
    for s, h in pf["holdings"].items():
        pl = (h["last_price"] / h["avg_price"] - 1) * 100
        stop = f"손절 {h['stop']}({(h['stop']/h['last_price']-1)*100:+.1f}%)" if h.get("stop") else "손절 없음"
        tgt = f"목표 {h['target']}({(h['target']/h['last_price']-1)*100:+.1f}%)" if h.get("target") else "목표 해제"
        L.append(f"- **{s}** {h['qty']}주 · 종가 {h['last_price']:,.2f} · 평단 대비 {pl:+.2f}% · {stop} · {tgt}")
    L.append("- **자동 거래:** " + ("; ".join(done) if done else "없음 (손절·목표가 미도달)"))
    if pf["halt_buys"]:
        L.append("- ⚠ **리스크 규칙 발동:** 신규 매수 중단 상태(일 -2% 또는 누적 -5%). 전략 재검토 필요.")
    with (D / "daily_report.md").open("a", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")
    pf["last_auto_session"] = session
    save(pf); sync()
    print("자동 점검 완료:", session, "| 자동 거래:", done or "없음")


def cmd_exec_orders(a):
    """개장 후 자동 체결: paper/orders.json 의 대기 주문을 실제(15분 이내) 시세로 체결. 규칙은 cmd_trade 가 강제."""
    of = D / "orders.json"
    if not of.exists():
        print("대기 주문 없음"); return
    od = json.loads(of.read_text(encoding="utf-8"))
    todo = [o for o in od["orders"] if o["status"] == "pending"]
    if not todo:
        print("대기 주문 없음"); return
    q = quote("SPY")
    if not q["regular_open"]:
        print("정규장 아님 — 체결 보류(다음 실행에서 재시도)"); return
    today = q["time"].date(); sess = datetime.fromisoformat(od["session"]).date()
    if today <= sess or (today - sess).days > 5:
        print(f"계획 거래일 {sess} / 오늘 {today} — 체결 시점이 아님"); return
    log = []
    for o in sorted(todo, key=lambda x: x["action"] != "SELL"):     # 매도 먼저
        sym = o["ticker"]; px = quote(sym)["price"]; gap = (px / o["ref_price"] - 1) * 100
        if o["action"] == "BUY" and abs(gap) > 3:
            o["status"] = "cancelled"; o["note"] = f"시세 {px} 가 기준가 {o['ref_price']} 대비 {gap:+.1f}% — 매수 취소"
        elif a.dry_run:
            log.append(f"[dry-run] {o['action']} {sym} {o['qty']} @~{px} ({gap:+.1f}%)"); continue
        else:
            t = argparse.Namespace(cmd=o["action"].lower(), ticker=sym, qty=o["qty"], at_close=False,
                                   reason="[LLM 자동 판단] " + o["reason"], stop=o.get("stop"), target=o.get("target"))
            try:
                cmd_trade(t); o["status"] = "filled"; o["note"] = f"기준가 대비 {gap:+.1f}%에 체결"
            except SystemExit as e:
                o["status"] = "rejected"; o["note"] = f"규칙/시세로 거부: {e}"
        log.append(f"- **{o['action']} {sym} {o['qty']}주** → {o['status']} ({o.get('note','')})")
    if a.dry_run:
        print("\n".join(log)); return
    od["executed_et"] = datetime.now(ET).isoformat(timespec="minutes")
    of.write_text(json.dumps(od, ensure_ascii=False, indent=1), encoding="utf-8")
    cmd_mark(a)
    pf = load()
    L = ["", f"## {today} (거래일) — 개장 후 자동 체결 (실제 시세, 슬리피지 {SLIP_BPS}bp 가정)"] + log + [
         f"- **포트폴리오:** 총자산 ${pf['total_equity']:,.2f} / 현금 ${pf['cash']:,.2f}"]
    with (D / "daily_report.md").open("a", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")
    sync()
    print("\n".join(L))


if __name__ == "__main__":
    p = argparse.ArgumentParser(); sp = p.add_subparsers(dest="cmd", required=True)
    for n, f in (("init", cmd_init), ("mark", cmd_mark), ("sync", lambda a: sync()), ("status", cmd_status)):
        sp.add_parser(n).set_defaults(fn=f)
    sa = sp.add_parser("autorun"); sa.set_defaults(fn=cmd_autorun); sa.add_argument("--dry-run", action="store_true")
    sx = sp.add_parser("exec-orders"); sx.set_defaults(fn=cmd_exec_orders); sx.add_argument("--dry-run", action="store_true")
    for n in ("buy", "sell"):
        s = sp.add_parser(n); s.set_defaults(fn=cmd_trade)
        s.add_argument("ticker"); s.add_argument("qty", type=float); s.add_argument("--reason", required=True)
        s.add_argument("--at-close", action="store_true"); s.add_argument("--stop", type=float); s.add_argument("--target", type=float)
    a = p.parse_args(); a.fn(a)
