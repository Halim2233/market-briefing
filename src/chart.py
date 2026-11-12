"""차트 트레이더 에이전트의 '계산' 파트.
지표와 캔들 패턴은 코드로 정확히 계산하고, 해석만 LLM(analyst/trader)이 한다."""
import pandas as pd
import yfinance as yf


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / down)


def _candle_patterns(df: pd.DataFrame) -> list[str]:
    """최근 봉 기준 단순 캔들 패턴 탐지."""
    found = []
    c, p = df.iloc[-1], df.iloc[-2]
    body = abs(c.Close - c.Open)
    rng = max(c.High - c.Low, 1e-9)
    upper = c.High - max(c.Close, c.Open)
    lower = min(c.Close, c.Open) - c.Low

    if body / rng < 0.1:
        found.append("도지(Doji): 매수·매도 힘 균형, 추세 전환 가능성")
    if lower > body * 2 and upper < body * 0.5 and body > 0:
        found.append("망치형(Hammer): 하락 후 나오면 반등 신호 후보")
    if upper > body * 2 and lower < body * 0.5 and body > 0:
        found.append("유성형(Shooting Star): 상승 후 나오면 하락 반전 후보")
    if p.Close < p.Open and c.Close > c.Open and c.Close >= p.Open and c.Open <= p.Close:
        found.append("상승장악형(Bullish Engulfing)")
    if p.Close > p.Open and c.Close < c.Open and c.Close <= p.Open and c.Open >= p.Close:
        found.append("하락장악형(Bearish Engulfing)")
    return found


def analyze_ticker(symbol: str) -> dict | None:
    try:
        df = yf.Ticker(symbol).history(period="1y", interval="1d").dropna()
        if len(df) < 60:
            return None
    except Exception as e:
        print(f"[chart] {symbol} 실패: {e}")
        return None

    close = df["Close"]
    sma20, sma50 = close.rolling(20).mean(), close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()
    last = float(close.iloc[-1])

    def f(x):
        return None if pd.isna(x) else round(float(x), 2)

    return {
        "symbol": symbol,
        "close": round(last, 2),
        "change_pct_1d": round((last / float(close.iloc[-2]) - 1) * 100, 2),
        "change_pct_1m": round((last / float(close.iloc[-21]) - 1) * 100, 2),
        "sma20": f(sma20.iloc[-1]), "sma50": f(sma50.iloc[-1]), "sma200": f(sma200.iloc[-1]),
        "rsi14": f(_rsi(close).iloc[-1]),
        "macd": f(macd.iloc[-1]), "macd_signal": f(signal.iloc[-1]),
        "volume_vs_20d_avg": round(float(df.Volume.iloc[-1] / df.Volume.rolling(20).mean().iloc[-1]), 2),
        "support_20d_low": f(df.Low.iloc[-20:].min()),
        "resistance_20d_high": f(df.High.iloc[-20:].max()),
        "high_52w": f(df.High.max()), "low_52w": f(df.Low.min()),
        "candle_patterns_today": _candle_patterns(df),
        "last_10_closes": [round(float(x), 2) for x in close.iloc[-10:]],
    }


def analyze_watchlist(cfg: dict) -> list[dict]:
    out = [r for s in cfg["chart"]["watchlist"] if (r := analyze_ticker(s))]
    print(f"[chart] 차트 지표 {len(out)}종목 계산")
    return out
