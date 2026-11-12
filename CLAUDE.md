# 프로젝트 규칙

## 모의투자 (paper/, docs/paper/)
- 가상 거래만 한다. 실제 계좌 접속·주문 금지. 기록은 `paper/sim.py`로만 변경하고, 기록을 수정·삭제하지 않는다.
- **새 종목을 매수할 때마다** `docs/assets/paper.js` 상단 `KO` 목록에 `티커: "한국식 이름"`을 같은 커밋에 추가한다 (페이지가 `AMZN (아마존)`처럼 표시). `sim.py buy`가 목록에 없는 티커를 경고한다.
- 매수·매도 후에는 `daily_report.md`를 갱신하고 `python -I paper/sim.py sync` 후 `paper docs`를 커밋·푸시한다 (`docs/paper/data/`는 .gitignore 예외 처리돼 있음).
- 장외 가정 체결(`--at-close`)은 사용자가 지시했을 때만 사용하고 보고서에 명시한다.

## 자동화 (.github/workflows/auto.yml)
- 평일 06:30 KST(미국 마감 후)에 수집 → Gemini 브리핑(`scripts/gemini_briefing.py`, 시크릿 `GEMINI_API_KEY`) → `paper/sim.py autorun` → 커밋/푸시.
- `autorun`은 평가, 손절/목표가 **규칙 매도**, 일일 기록만 한다. **신규 매수/매도 판단은 자동화하지 않는다** — 사용자와 세션에서 결정.
- 자동 점검이 `daily_report.md` 끝에 항목을 추가하므로 수동 보고서와 겹치지 않게 날짜별로 이어 쓴다.
