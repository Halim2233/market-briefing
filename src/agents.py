"""LLM 에이전트들: 분석가 / 차트 트레이더 / 리스크 검토자 / 종합 에이전트."""
import json
import re

import anthropic

_client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 사용


def _ask(model: str, system: str, user: str, max_tokens: int = 8000) -> str:
    resp = _client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _extract_json(text: str):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return json.loads(m.group(1) if m else text)


# ───────────────────────── 1) 분석가 에이전트 ─────────────────────────
ANALYST_SYS = """당신은 미국 증시 전문 뉴스 분석가입니다. 투자자는 한국인이고 나스닥100(기술주)을 가장 중시하며 S&P500 등 전체 시장도 봅니다.
기사 목록에서 '미국 증시/기술주/거시경제에 실제로 영향이 있는' 것만 골라내세요.
- 광고성, 단순 의견, 개인 재테크 팁, 이미 알려진 반복 내용은 낮은 점수.
- 같은 사건을 다룬 기사는 가장 대표적인 1건만 높은 점수를 주고 나머지는 낮게.
- 사실만 쓰고 추측은 추측이라고 표시. 기사에 없는 숫자를 만들지 마세요.
출력은 JSON 배열만. 각 원소:
{"id": 기사id, "importance": 0~10 정수, "ko_title": "한글 제목", "ko_summary": "한글 2~3문장 요약",
 "tickers": ["관련 티커"], "sentiment": "호재|악재|중립", "horizon": "단기|중기|장기", "why": "시장에 중요한 이유 한 줄"}
모든 기사에 대해 항목을 반드시 포함하세요."""


def run_analyst(model: str, news: list[dict]) -> list[dict]:
    payload = [{"id": n["id"], "source": n["source"], "title": n["title"], "summary": n["summary"]} for n in news]
    text = _ask(model, ANALYST_SYS, json.dumps(payload, ensure_ascii=False), max_tokens=16000)
    scored = {x["id"]: x for x in _extract_json(text)}
    out = []
    for n in news:
        s = scored.get(n["id"])
        if s:
            out.append({**n, **s})
    return out


# ───────────────────────── 2) 차트 트레이더 에이전트 ─────────────────────────
TRADER_SYS = """당신은 오직 차트(기술적 분석)만 공부한 트레이더입니다. 이동평균, RSI, MACD, 거래량, 지지/저항, 캔들 패턴, 엘리엇 파동 이론에 정통합니다.
주어진 수치(코드로 계산된 값)만 근거로 종목별로 해석하세요. 수치에 없는 값을 지어내지 마세요.
- 엘리엇 파동은 입력이 최근 10일 종가 정도라 확정할 수 없습니다. 언급한다면 '가능성' 수준으로만, 신뢰도 낮음을 명시.
- 반드시 '시나리오 A(상승)/시나리오 B(하락)'와 각각의 '무효화 가격'을 제시.
- 한글, 종목당 4~6줄 이내 마크다운. 마지막에 한 줄 결론(강세/중립/약세 + 확신도 낮음/중간/높음)."""


def run_trader(model: str, charts: list[dict]) -> str:
    return _ask(model, TRADER_SYS, json.dumps(charts, ensure_ascii=False), max_tokens=8000)


# ───────────────────────── 3) 리스크 검토자 ─────────────────────────
RISK_SYS = """당신은 회의적인 리스크 매니저입니다. 뉴스 요약과 차트 분석을 읽고 '반대 시나리오'를 만드는 것이 임무입니다.
- 지금 시장이 놓치고 있을 수 있는 위험 3~5개, 확증편향에 빠질 수 있는 지점, 판단이 틀릴 조건을 구체적으로.
- 한글 마크다운 불릿. 새로운 사실을 지어내지 말고 주어진 자료 안에서만 추론."""


def run_risk(model: str, news_md: str, trader_md: str) -> str:
    return _ask(model, RISK_SYS, f"## 뉴스\n{news_md}\n\n## 차트 분석\n{trader_md}", max_tokens=3000)


# ───────────────────────── 4) 종합 에이전트 ─────────────────────────
SYNTH_SYS = """당신은 수석 에디터입니다. 시장 스냅샷, 중요 뉴스, 차트 분석, 리스크 검토를 받아 모바일에서 읽기 좋은 한글 '일일 시장 브리핑'의 본문을 작성합니다.
구성(마크다운, ## 헤더 사용):
## 한눈에 보기  (오늘 시장 분위기 3~4줄: 나스닥100 중심, S&P500 등 전체 시장 포함)
## 오늘의 핵심 이슈  (가장 중요한 3~5개를 기술주 영향 중심으로, 관련 티커 표기)
## 뉴스와 차트가 일치/충돌하는 지점  (뉴스 호재/악재와 차트 신호를 대조)
## 체크할 것  (오늘/이번 주 주목할 이벤트나 가격대)
규칙: 주어진 자료에 없는 사실·수치를 만들지 말 것. 투자 권유 문구 금지, 판단 보조 정보로 서술. 표는 모바일에서 좁게 쓰고 가급적 불릿 사용. 전체 600~900자 내외 + 이슈별 간단한 설명."""


def run_synth(model: str, snapshot_md: str, news_md: str, trader_md: str, risk_md: str) -> str:
    user = f"### 스냅샷\n{snapshot_md}\n\n### 중요 뉴스\n{news_md}\n\n### 차트 분석\n{trader_md}\n\n### 리스크 검토\n{risk_md}"
    return _ask(model, SYNTH_SYS, user, max_tokens=4000)
