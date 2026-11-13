"""마감 후 자동 매매 '계획' 생성: 포트폴리오 + 지표 + 오늘 브리핑 → Gemini → 규칙 검증 → paper/orders.json.
체결은 하지 않는다. 다음 거래일 개장 후 `paper/sim.py exec-orders`가 실제 시세로 체결한다(기준가 ±5% 초과면 매수 취소).
가상 거래 전용. 종료 코드: 0 정상(주문 없음 포함), 1 실패, 3 키 없음.
환경변수: GEMINI_API_KEY. 옵션: --dry-run (파일을 쓰지 않고 출력만), --force (같은 거래일 계획이 이미 있어도, 체결된 주문이 없을 때 다시 만든다)"""
import importlib.util, json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPER = Path(os.environ.get("PAPER_DIR") or ROOT / "paper")
MAX_POS, MIN_CASH, SLIP = 0.20, 0.20, 0.0005
MAX_BUYS, MAX_SELLS, CHASE, GAP = 3, 3, 8.0, 5.0


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def universe():
    js = (ROOT / "docs" / "assets" / "paper.js").read_text(encoding="utf-8")
    block = re.search(r"var KO = \{(.*?)\};", js, re.S).group(1)
    return {m.group(1).strip('"'): m.group(2) for m in re.finditer(r'("?[A-Z][A-Z.\-]*"?)\s*:\s*"([^"]+)"', block)}


def parse_json(text):
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(t[t.index("{"): t.rindex("}") + 1])


def fmt(c):
    return (f"{c['symbol']}: 종가 {c['close']} (1일 {c['change_pct_1d']:+}%, 1개월 {c['change_pct_1m']:+}%) "
            f"SMA20/50/200 {c['sma20']}/{c['sma50']}/{c['sma200']} RSI {c['rsi14']} MACD {c['macd']}/{c['macd_signal']} "
            f"거래량비 {c['volume_vs_20d_avg']} 지지(20일저) {c['support_20d_low']} 저항(20일고) {c['resistance_20d_high']} 52주 {c['low_52w']}~{c['high_52w']}")


SYSTEM = """당신은 가상 모의투자(실제 돈 아님)의 포트폴리오 매니저입니다. 입력에 있는 수치와 뉴스만 근거로 하고, 없는 숫자·사실은 만들지 마세요.
투자 성향은 **공격적 성장·모멘텀**입니다. 기술주(AI·반도체·클라우드·빅테크) 중심으로 높은 수익을 노립니다. 현금을 놀리지 말고 최소 현금 한도(20%)에 가깝게 투입하되, 한 종목 20% 한도 안에서 확신 높은 2~4종목에 집중하세요. 상승 추세 종목의 추가 상승, 과매도 후 반등 초입, 뉴스 모멘텀 모두 근거가 될 수 있습니다. 약해진 보유 종목은 손절 전이라도 교체 매도할 수 있습니다. 다만 입력에 없는 숫자·사실은 쓰지 말고, 근거 없이 거래하지는 마세요.
주문은 다음 거래일 개장 후 체결되며, 시세가 기준가(오늘 종가)에서 ±5% 넘게 벌어지면 매수는 자동 취소됩니다.
반드시 아래 JSON만 출력하세요(코드블록 금지):
{"summary":"시장 판단 2~3문장","orders":[{"action":"BUY|SELL","ticker":"티커","qty":정수,"stop":손절가(BUY만),"target":목표가(BUY만),"reason":"근거 1~2문장(수치 포함)"}]}
주문이 없으면 "orders":[] 로 두고 summary에 이유를 쓰세요."""


def main():
    dry = "--dry-run" in sys.argv
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY 없음 — 건너뜀"); sys.exit(3)
    pf = json.loads((PAPER / "portfolio.json").read_text(encoding="utf-8"))
    session = pf.get("last_auto_session")
    if not session:
        print("자동 점검(autorun) 기록 없음 — 계획 건너뜀"); return
    of = PAPER / "orders.json"
    if of.exists():
        old = json.loads(of.read_text(encoding="utf-8"))
        if old.get("session") == session:
            if "--force" not in sys.argv or any(o["status"] != "pending" for o in old["orders"]):
                print(f"{session} 거래일 계획은 이미 있음(또는 일부 체결됨) — 건너뜀"); return
            print("--force: 체결 전 계획을 새로 만든다")

    uni = universe()
    col = _load("collect", ROOT / "scripts" / "collect.py")
    gb = _load("gb", ROOT / "scripts" / "gemini_briefing.py")
    tick = list(dict.fromkeys(list(pf["holdings"]) + list(uni)))
    an = {}
    for s in tick:
        try:
            r = col.analyze(s)
        except Exception as e:
            print(f"[분석 실패] {s}: {e}"); r = None
        if r: an[s] = r
    held_missing = [s for s in pf["holdings"] if s not in an]
    if held_missing:
        sys.exit(f"보유 종목 지표 수집 실패 {held_missing} — 판단 불가")

    reports = sorted((ROOT / "docs" / "reports").glob("20*.md"))
    brief = reports[-1].read_text(encoding="utf-8") if reports else ""
    brief = re.sub(r"^---.*?---", "", brief, count=1, flags=re.S)[:7000]
    strat = (PAPER / "investment_strategy.md").read_text(encoding="utf-8")
    m = re.search(r"## 의사결정 규칙.*?(?=\n## )", strat, re.S)
    eq = pf["total_equity"]
    held = "\n".join(f"- {s}: {h['qty']}주 평단 {h['avg_price']} 종가 {h['last_price']} 손절 {h.get('stop')} 목표 {h.get('target')}" for s, h in pf["holdings"].items()) or "- 없음"
    user = f"""[기준 거래일] {session} 종가 (체결은 다음 거래일 개장 후)
[포트폴리오] 총자산 ${eq:,.2f}, 현금 ${pf['cash']:,.2f} ({pf['cash']/eq*100:.1f}%), 신규매수중단={pf['halt_buys']}
[보유]
{held}
[하드 규칙 - 코드가 강제, 어기면 주문 폐기] 종목당 최대 {MAX_POS:.0%}(${MAX_POS*eq:,.0f}), 거래 후 현금 {MIN_CASH:.0%}(${MIN_CASH*eq:,.0f}) 이상, 보유 종목 추가매수 금지, 공매도·레버리지·옵션 금지, 당일 +{CHASE}% 이상 급등 종목 매수 금지, 하루 최대 매수 {MAX_BUYS}건·매도 {MAX_SELLS}건, 매수에는 손절가(<종가)와 목표가(>종가) 필수, 정수 수량.
[거래 가능 종목] {', '.join(uni)}  (이 밖의 종목은 불가)
[전략 규칙]
{m.group(0) if m else ''}
[지표]
""" + "\n".join(fmt(an[s]) for s in tick if s in an) + f"\n\n[오늘 브리핑 발췌]\n{brief}"
    raw = gb.gemini(SYSTEM, user, 6000)
    try:
        plan = parse_json(raw)
    except Exception as e:
        sys.exit(f"응답 JSON 파싱 실패: {e}\n{raw[:300]}")

    cash, buys, sells, ok, bad = pf["cash"], 0, 0, [], []
    for o in plan.get("orders", []):
        try:
            act, s, q = str(o["action"]).upper(), str(o["ticker"]).upper(), int(o["qty"])
            ref = an[s]["close"]; why = str(o.get("reason", "")).strip()
        except Exception as e:
            bad.append((o, f"형식 오류 {e}")); continue
        err = None
        if s not in uni and act == "BUY": err = "거래 가능 종목 아님"
        elif s not in an: err = "지표 없음"
        elif q <= 0: err = "수량 오류"
        elif not why: err = "근거 없음"
        elif act == "SELL":
            h = pf["holdings"].get(s)
            if not h or q > h["qty"]: err = "보유 수량 초과(공매도 금지)"
            elif sells >= MAX_SELLS: err = "일일 매도 한도"
        elif act == "BUY":
            stop, tgt = o.get("stop"), o.get("target")
            amt = ref * (1 + SLIP) * q
            if pf["halt_buys"]: err = "리스크 규칙: 신규 매수 중단"
            elif s in pf["holdings"]: err = "보유 종목 추가매수 금지"
            elif buys >= MAX_BUYS: err = "일일 매수 한도"
            elif an[s]["change_pct_1d"] >= CHASE: err = f"당일 {an[s]['change_pct_1d']:+}% 급등 추격 금지"
            elif not (isinstance(stop, (int, float)) and isinstance(tgt, (int, float)) and 0.8 * ref <= stop < ref < tgt): err = "손절/목표가 부적절"
            elif amt > MAX_POS * eq: err = f"종목 한도 초과(${amt:,.0f})"
            elif cash - amt < MIN_CASH * eq: err = "최소 현금 위반"
            else: cash -= amt
        else:
            err = "action 오류"
        if err:
            bad.append((o, err)); continue
        buys += act == "BUY"; sells += act == "SELL"
        ok.append({"action": act, "ticker": s, "qty": q, "stop": o.get("stop") if act == "BUY" else None,
                   "target": o.get("target") if act == "BUY" else None, "reason": why, "ref_price": ref, "status": "pending"})

    out = {"session": session, "created": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z",
           "summary": str(plan.get("summary", ""))[:600], "orders": ok,
           "rejected": [{"order": o, "why": e} for o, e in bad]}
    L = [f"\n## {session} (거래일) — 자동 매매 계획 (LLM 판단)",
         "> Gemini가 지표·브리핑을 보고 제안하고 코드가 규칙을 검증한 계획입니다. 체결은 다음 거래일 개장 후 실제 시세로 하며, 시세가 기준가(종가)에서 ±5% 넘게 벌어지면 매수는 취소합니다. LLM 판단은 틀릴 수 있습니다(가상 거래).",
         f"- **시장 판단:** {out['summary']}"]
    for o in ok:
        px = f"기준가 {o['ref_price']}" + (f" · 손절 {o['stop']} · 목표 {o['target']}" if o["action"] == "BUY" else "")
        L.append(f"- **{o['action']} {o['ticker']} {o['qty']}주** ({px}) — {o['reason']}")
    for r in out["rejected"]:
        L.append(f"- ~~제안 폐기~~ {json.dumps(r['order'], ensure_ascii=False)[:160]} — **{r['why']}**")
    if not ok: L.append("- **주문 없음** (유지)")
    print("\n".join(L))
    if dry: return
    of.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    with (PAPER / "daily_report.md").open("a", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")
    sim = _load("sim", PAPER / "sim.py") if (PAPER / "sim.py").exists() else None
    if sim: sim.sync()


if __name__ == "__main__":
    main()
