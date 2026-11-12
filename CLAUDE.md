# 프로젝트 규칙

## 모의투자 (paper/, docs/paper/)
- 가상 거래만 한다. 실제 계좌 접속·주문 금지. 기록은 `paper/sim.py`로만 변경하고, 기록을 수정·삭제하지 않는다.
- **새 종목을 매수할 때마다** `docs/assets/paper.js` 상단 `KO` 목록에 `티커: "한국식 이름"`을 같은 커밋에 추가한다 (페이지가 `AMZN (아마존)`처럼 표시). `sim.py buy`가 목록에 없는 티커를 경고한다.
- 매수·매도 후에는 `daily_report.md`를 갱신하고 `python -I paper/sim.py sync` 후 `paper docs`를 커밋·푸시한다 (`docs/paper/data/`는 .gitignore 예외 처리돼 있음).
- 장외 가정 체결(`--at-close`)은 사용자가 지시했을 때만 사용하고 보고서에 명시한다.
