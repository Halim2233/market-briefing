"""수집 결과(data/날짜.json) → Gemini API → docs/reports/날짜.md  (표준 라이브러리만 사용)

환경변수: GEMINI_API_KEY (필수), GEMINI_MODEL (기본 gemini-2.5-flash)
종료 코드: 0 성공/의도적 건너뜀, 3 키 없음, 1 실패(부분 결과는 저장하지 않음).
뉴스 선별·번역·요약 + 차트 해석 + 반도체 + 리스크 + 종합 브리핑만 만든다. 모의투자 매매 판단은 하지 않는다."""
import importlib.util, json, os, sys, time, tomllib, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"   # 404면 아래 _pick_model()이 사용 가능한 flash 모델을 찾는다
SEMI_TICKERS = {"SOXL", "SOXX", "SMH", "AMD", "TSM", "MU", "INTC", "ASML", "ARM", "QCOM", "AMAT", "LRCX", "MRVL", "NVDA", "AVGO"}

# 기존 프롬프트(src/agents.py) 재사용 — import 시 부작용 없음(표준 라이브러리만 import)
_spec = importlib.util.spec_from_file_location("agents", ROOT / "src" / "agents.py")
agents = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agents)


def _pick_model(key: str) -> str | None:
    """ListModels에서 generateContent를 지원하는 최신 일반 flash 모델을 고른다."""
    import re
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", headers={"x-goog-api-key": key})
    names = [m["name"].split("/", 1)[1] for m in json.loads(urllib.request.urlopen(req, timeout=60).read()).get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    ok = [n for n in names if re.fullmatch(r"gemini-[\d.]+-flash", n)]
    ok.sort(key=lambda n: [int(x) for x in re.findall(r"\d+", n)], reverse=True)
    return ok[0] if ok else None


def gemini(system: str, user: str, max_tokens: int = 16000) -> str:
    global MODEL
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit(3)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": max_tokens},
    }).encode()
    last = None
    for attempt in range(5):
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            data = json.loads(urllib.request.urlopen(req, timeout=180).read())
            cand = data["candidates"][0]
            text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
            if not text.strip():
                raise RuntimeError(f"빈 응답 (finishReason={cand.get('finishReason')})")
            if cand.get("finishReason") == "MAX_TOKENS":
                raise RuntimeError("출력 한도 초과로 잘림 — 부분 결과는 쓰지 않음")
            time.sleep(7)   # 무료 티어 분당 호출 한도 완충
            return text
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read()[:200]!r}"
            if e.code in (429, 500, 503):
                time.sleep(15 * (attempt + 1)); continue
            if e.code == 404 and not os.environ.get("_MODEL_PICKED"):
                os.environ["_MODEL_PICKED"] = "1"
                picked = _pick_model(key)
                if picked and picked != MODEL:
                    print(f"[model] {MODEL} 사용 불가 → {picked} 로 전환")
                    MODEL = picked
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
                    continue
            break
        except Exception as e:   # 네트워크/파싱 오류
            last = str(e)[:200]
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Gemini 호출 실패: {last}")


agents._ask = lambda model, system, user, max_tokens=8000: gemini(system, user, max(max_tokens, 8000))

SEMI_SYS = """당신은 반도체 섹터 애널리스트 겸 차트 트레이더입니다. 입력(반도체 종목 차트 수치와 반도체 관련 뉴스)에 있는 값만 근거로 쓰고, 없는 숫자·사실은 만들지 마세요. 한글 마크다운.
형식(정확히 이 3개 소제목):
### 반도체 뉴스
(수출 규제, 실적, 설비투자, AI 수요, 메모리/파운드리 동향 등 3~6개 불릿, 각 1~2문장. 관련 뉴스가 없으면 '관련 뉴스 없음')
### 반도체 차트 (SOXX·SMH·개별주)
(종목당 2~3줄: 추세/이평선 대비, RSI·MACD, 지지·저항. ETF와 개별주 방향이 갈리면 짚기. 종목 제목은 **티커 가격 (+등락%)** 형식, 제목 아래 반드시 빈 줄 후 불릿. 각 종목 마지막 불릿은 '- 결론: **강세|중립|약세, 확신도 낮음|중간|높음.**')
### SOXL (3배 레버리지) 점검
(a) 일일 3배 추종이라 횡보·변동성 큰 장에서 장기 보유 시 변동성 잠식으로 기초지수보다 손실이 커질 수 있음 (b) 같은 신호라도 위아래 폭이 큼 (c) SOXX·SMH 추세와 비교한 해석. 엔비디아 비중이 큰 지수이므로 NVDA 이벤트 영향도 언급. 매수·매도 권유와 보유 기간·손절 같은 개인 투자 판단은 금지.)
투자 권유 문구 금지."""


def snapshot_md(rows):
    out = []
    for r in rows:
        arrow = "🔺" if r["change_pct"] > 0 else "🔻" if r["change_pct"] < 0 else "➖"
        out.append(f"- **{r['name']}** {r['close']:,} ({arrow} {r['change_pct']:+.2f}%)")
    return "\n".join(out)


def main():
    force = "--force" in sys.argv
    cfg = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
    files = sorted((ROOT / "data").glob("20*.json"))
    if not files:
        sys.exit("data/*.json 없음 — scripts/collect.py 먼저 실행")
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    date = data["generated_at_kst"][:10]
    test_out = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--out=")), None)   # 시험용: 다른 경로에 저장
    out = Path(test_out) if test_out else ROOT / "docs" / "reports" / f"{date}.md"
    if not test_out and out.exists() and "generator: gemini" not in out.read_text(encoding="utf-8") and not force:
        print(f"{out.name} 이미 존재(수동 작성본) — 덮어쓰지 않음"); return
    if not data["snapshot"] or not data["news"]:
        sys.exit("스냅샷/뉴스가 비어 있음 — 데이터 부족으로 브리핑 생성 중단")
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY 없음 — 건너뜀"); sys.exit(3)

    # 1) 뉴스 분석가 (35건씩 나눠 호출 — 출력 잘림 방지)
    news, analyzed = data["news"], []
    for i in range(0, len(news), 35):
        try:
            analyzed += agents.run_analyst(MODEL, news[i:i + 35])
        except Exception as e:
            print(f"[analyst] 묶음 {i // 35 + 1} 실패: {e}")
    if not analyzed:
        sys.exit("뉴스 분석 전부 실패")
    important = sorted((n for n in analyzed if n["importance"] >= cfg["news"]["min_importance"]),
                       key=lambda n: n["importance"], reverse=True)
    print(f"[analyst] 중요 뉴스 {len(important)}건")
    news_md = "\n".join(
        f"- [{n['importance']}/10 · {n['sentiment']} · {n['horizon']}] **{n['ko_title']}** ({', '.join(n['tickers'])}) — {n['ko_summary']} / 이유: {n['why']}"
        for n in important)

    # 2) 차트 트레이더, 3) 반도체, 4) 리스크, 5) 종합
    trader_md = agents.run_trader(MODEL, data["charts"])
    semi_news = [n for n in important if SEMI_TICKERS & set(n["tickers"]) or "chip" in n["title"].lower() or "semiconductor" in n["title"].lower()]
    semi_md = gemini(SEMI_SYS, json.dumps({"semis_charts": data["semis"], "semis_news": [
        {"title": n["ko_title"], "summary": n["ko_summary"], "tickers": n["tickers"], "sentiment": n["sentiment"]} for n in semi_news]},
        ensure_ascii=False), 12000)
    risk_md = agents.run_risk(MODEL, news_md, trader_md + "\n\n" + semi_md)
    snap = snapshot_md(data["snapshot"])
    body = agents.run_synth(MODEL, snap, news_md, trader_md + "\n\n" + semi_md, risk_md)

    now = datetime.now(KST)
    sources = "\n".join(f"- {n['ko_title']} — [{n['source']}]({n['link']}) · {n['sentiment']} · 중요도 {n['importance']}" for n in important)
    report = f"""---
layout: page
title: "{date} 미국 증시 브리핑"
date: {now.strftime('%Y-%m-%d %H:%M:%S +0900')}
generator: gemini
---

> 생성 시각 {now.strftime('%Y-%m-%d %H:%M')} KST · {MODEL}가 수집 자료로 자동 작성한 문서이며 **투자 권유가 아닙니다.** 가격·지표는 직전 거래일 정규장 종가 기준입니다.

## 시장 스냅샷 (직전 거래일 종가)
{snap}

{body}

## 차트 분석 (기술적 관점)
{trader_md}

## 반도체 섹션
{semi_md}

## 반대 시나리오 · 리스크 점검
{risk_md}

## 뉴스 출처
{sources}
"""
    out.write_text(report, encoding="utf-8")
    print(f"저장 완료: {out}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"브리핑 생성 실패: {e}")
        sys.exit(1)
