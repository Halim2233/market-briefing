# 프로젝트 규칙

## 모의투자 (paper/, docs/paper/)
- 가상 거래만 한다. 실제 계좌 접속·주문 금지. 기록은 `paper/sim.py`로만 변경하고, 기록을 수정·삭제하지 않는다.
- **새 종목을 매수할 때마다** `docs/assets/paper.js` 상단 `KO` 목록에 `티커: "한국식 이름"`을 같은 커밋에 추가한다 (페이지가 `AMZN (아마존)`처럼 표시). `sim.py buy`가 목록에 없는 티커를 경고한다.
- 매수·매도 후에는 `daily_report.md`를 갱신하고 `python -I paper/sim.py sync` 후 `paper docs`를 커밋·푸시한다 (`docs/paper/data/`는 .gitignore 예외 처리돼 있음).
- 장외 가정 체결(`--at-close`)은 사용자가 지시했을 때만 사용하고 보고서에 명시한다.

## 자동화 (.github/workflows/auto.yml)
- 평일 06:30 KST(미국 마감 후)에 수집 → Gemini 브리핑(`scripts/gemini_briefing.py`, 시크릿 `GEMINI_API_KEY`) → `paper/sim.py autorun` → 커밋/푸시.
- `autorun`은 평가, 손절/목표가 **규칙 매도**, 일일 기록을 한다.
- **신규 매수/매도 판단도 자동화됨 (2026-11-13 사용자 지시, 가상 거래; 투자 성향은 공격적·기술주 중심 — 전략 v0.3; ETF 전면 허용+지수/섹터 레버리지 ETF 허용(v0.5), 단일종목 레버리지·인버스·공매도·옵션·마진은 금지):** 장중 `auto-open.yml`(평일 14:05~19:35 UTC 30분마다 시도, 정규장·ET 10:00 이후·당일 미판단일 때만 동작)이 `scripts/gemini_trader.py --live`로 Gemini 제안(지표는 직전 거래일 종가까지의 일봉, 오늘 진행 중인 봉은 제외 + 현재가 별도 전달)을 하드 규칙(20% 한도·현금 20%·추가매수 금지·일 매수 3/매도 3건·당일 +8% 이상 급등 추격 금지·손절/목표 필수)으로 검증해 `paper/orders.json`에 저장하고, 같은 실행에서 `sim.py exec-orders --same-day`가 실제 시세로 체결한다. 매매 후보 종목은 `paper.js`의 `KO` 목록(DENY 제외)에 있는 티커뿐 — 새 종목을 허용하려면 KO에 한글 이름을 먼저 추가한다. 손절/목표가 규칙 매도는 마감 후 `autorun`이 종가 기준으로 한다. 세션에서 수동 거래할 때는 당일 `orders.json`과 겹치지 않는지 확인한다.
- 자동 점검·계획·체결이 `daily_report.md` 끝에 항목을 추가하므로 수동 보고서와 겹치지 않게 날짜별로 이어 쓴다.
