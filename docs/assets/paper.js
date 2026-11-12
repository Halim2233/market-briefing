(function () {
  var root = document.getElementById("paper");
  if (!root) return;
  var base = root.getAttribute("data-base");
  var COLORS = ["#3b5bfd", "#e5383b", "#12b886", "#f59f00", "#9c36b5", "#0ca5c9"];

  var KO = { AMZN: "아마존", LLY: "일라이 릴리", JPM: "JP모건", V: "비자", AVGO: "브로드컴", NVDA: "엔비디아", AMD: "AMD",
    MSFT: "마이크로소프트", GOOGL: "알파벳", META: "메타", AAPL: "애플", TSLA: "테슬라", "BRK-B": "버크셔 해서웨이", COST: "코스트코",
    SPY: "S&P500 ETF", QQQ: "나스닥100 ETF", XLV: "헬스케어 ETF", GLD: "금 ETF" };
  var nm = function (t) { return KO[t] ? t + " <small class=\"ko\">(" + KO[t] + ")</small>" : t; };

  var $ = function (n) { return n == null ? "–" : n; };
  var usd = function (n) { return n == null ? "–" : "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
  var pct = function (n, d) { return n == null ? "–" : (n > 0 ? "+" : "") + Number(n).toFixed(d == null ? 2 : d) + "%"; };
  var cls = function (n) { return n > 0 ? "up" : n < 0 ? "down" : "flat"; };
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };

  function parseCSV(t) {
    var rows = [], row = [], f = "", q = false, i, c;
    for (i = 0; i < t.length; i++) {
      c = t[i];
      if (q) { if (c === '"') { if (t[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
      else if (c === '"') q = true;
      else if (c === ",") { row.push(f); f = ""; }
      else if (c === "\n") { row.push(f); rows.push(row); row = []; f = ""; }
      else if (c !== "\r") f += c;
    }
    if (f || row.length) { row.push(f); rows.push(row); }
    var h = rows.shift() || [];
    return rows.filter(function (r) { return r.length > 1; }).map(function (r) {
      var o = {}; h.forEach(function (k, j) { o[k] = r[j]; }); return o;
    });
  }

  function get(name, text) {
    return fetch(base + "/" + name + "?t=" + Date.now()).then(function (r) {
      if (!r.ok) throw new Error(name + " " + r.status);
      return text ? r.text() : r.json();
    });
  }

  function tile(n, v, p) {
    return '<div class="tile"><div class="n">' + n + '</div><div class="v">' + v + "</div>" +
      (p ? '<span class="p ' + p[0] + '">' + p[1] + "</span>" : "") + "</div>";
  }

  function chart(curve, initial, spy0) {
    if (!curve || curve.length < 2) return '<div class="chart"><div class="empty">자산 곡선은 기록이 2회 이상 쌓이면 표시됩니다.</div></div>';
    var W = 640, H = 240, L = 52, R = 12, T = 12, B = 26;
    var eq = curve.map(function (p) { return (p.equity / initial - 1) * 100; });
    spy0 = spy0 || curve[0].spy;
    var spy = curve.map(function (p) { return p.spy ? (p.spy / spy0 - 1) * 100 : null; });
    var all = eq.concat(spy.filter(function (v) { return v != null; }), [0]);
    var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
    var pad = (hi - lo) * 0.15 || 0.5; lo -= pad; hi += pad;
    var x = function (i) { return L + (W - L - R) * i / (curve.length - 1); };
    var y = function (v) { return T + (H - T - B) * (1 - (v - lo) / (hi - lo)); };
    var path = function (arr) {
      return arr.map(function (v, i) { return v == null ? "" : (i && arr[i - 1] != null ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); }).join("");
    };
    var g = "", k, step = (hi - lo) / 4;
    for (k = 0; k <= 4; k++) {
      var v = lo + step * k;
      g += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '" stroke="var(--line)"/>' +
        '<text x="' + (L - 6) + '" y="' + (y(v) + 4) + '" text-anchor="end" font-size="11" fill="var(--muted)">' + v.toFixed(1) + "%</text>";
    }
    g += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(0) + '" y2="' + y(0) + '" stroke="var(--muted)" stroke-dasharray="4 4"/>';
    var d0 = curve[0].time_et.slice(5, 10), d1 = curve[curve.length - 1].time_et.slice(5, 10);
    g += '<text x="' + L + '" y="' + (H - 6) + '" font-size="11" fill="var(--muted)">' + d0 + "</text>" +
      '<text x="' + (W - R) + '" y="' + (H - 6) + '" text-anchor="end" font-size="11" fill="var(--muted)">' + d1 + "</text>";
    return '<div class="chart"><svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="포트폴리오와 SPY 누적 수익률">' + g +
      '<path d="' + path(spy) + '" fill="none" stroke="#98a2b3" stroke-width="2"/>' +
      '<path d="' + path(eq) + '" fill="none" stroke="var(--accent)" stroke-width="2.5"/></svg>' +
      '<div class="legend"><span><i style="background:var(--accent)"></i>내 포트폴리오</span><span><i style="background:#98a2b3"></i>SPY (같은 기간)</span></div></div>';
  }

  function render(pf, perf, trades) {
    var eq = pf.total_equity, ret = (eq / pf.initial_capital - 1) * 100;
    var hold = Object.keys(pf.holdings).map(function (s) { var h = pf.holdings[s]; return Object.assign({ sym: s }, h); });
    var stock = hold.reduce(function (a, h) { return a + h.qty * h.last_price; }, 0);
    var h = '<div class="tiles">' +
      tile("총 평가 자산", usd(eq), [cls(ret), pct(ret)]) +
      tile("현금", usd(pf.cash), [ "flat", (pf.cash / eq * 100).toFixed(1) + "%"]) +
      tile("주식 평가금액", usd(stock), ["flat", (stock / eq * 100).toFixed(1) + "%"]) +
      tile("SPY 대비 초과", perf.excess_vs_spy_pct == null ? "–" : pct(perf.excess_vs_spy_pct), perf.spy_return_pct == null ? null : [cls(perf.spy_return_pct), "SPY " + pct(perf.spy_return_pct)]) +
      "</div>";
    if (pf.halt_buys) h += '<div class="warn">⚠ 리스크 규칙 발동: 신규 매수 중단 상태입니다 (일 -2% 또는 누적 -5%).</div>';
    h += '<p class="note">시작일(ET): ' + $(pf.start_date_et || "승인 후 첫 매수 전") + " · 마지막 갱신(ET): " + esc(pf.last_update_et) + " · 최대 낙폭(스냅샷): " + pct(perf.mdd_pct_snapshot_based) + "</p>";

    h += "<h2>자산 곡선</h2>" + chart(perf.equity_curve, pf.initial_capital, pf.benchmark && pf.benchmark.start_price);

    h += "<h2>비중</h2>";
    if (hold.length) {
      var segs = hold.map(function (x, i) { return [x.sym, x.qty * x.last_price / eq * 100, COLORS[i % COLORS.length]]; });
      segs.push(["현금", pf.cash / eq * 100, "var(--line)"]);
      h += '<div class="bar">' + segs.map(function (s) { return '<span style="width:' + s[1] + "%;background:" + s[2] + '" title="' + s[0] + '"></span>'; }).join("") + "</div>" +
        '<p class="note" style="margin-top:4px">' + segs.map(function (s) { return (KO[s[0]] ? s[0] + " (" + KO[s[0]] + ")" : s[0]) + " " + s[1].toFixed(1) + "%"; }).join(" · ") + "</p>";
    } else h += '<div class="tblwrap"><div class="empty">보유 종목이 없습니다 (현금 100%).</div></div>';

    h += "<h2>보유 종목</h2>";
    if (hold.length) {
      h += '<div class="tblwrap"><table class="tbl"><tr><th>종목</th><th>수량</th><th>평균단가</th><th>현재가</th><th>평가금액</th><th>손익</th><th>손절</th><th>목표</th></tr>' +
        hold.map(function (x) {
          var pl = (x.last_price / x.avg_price - 1) * 100;
          return "<tr><td>" + nm(x.sym) + "</td><td>" + x.qty + "</td><td>" + usd(x.avg_price) + "</td><td>" + usd(x.last_price) + "</td><td>" + usd(x.qty * x.last_price) +
            '</td><td class="' + cls(pl) + '">' + pct(pl) + "</td><td>" + $(x.stop) + "</td><td>" + $(x.target) + "</td></tr>";
        }).join("") + "</table></div>";
    } else h += '<div class="tblwrap"><div class="empty">없음</div></div>';

    h += "<h2>전체 거래 기록 (" + trades.length + "건)</h2>";
    if (trades.length) {
      h += '<div class="tblwrap"><table class="tbl"><tr><th>일시(ET)</th><th>종목</th><th>구분</th><th>수량</th><th>시장가</th><th>체결가</th><th>금액</th><th>슬리피지</th><th>잔액</th><th>실현손익</th><th>손절/목표</th><th>이유</th></tr>' +
        trades.slice().reverse().map(function (t) {
          return "<tr><td>" + esc(t.datetime_et.replace("T", " ").slice(0, 16)) + "</td><td>" + nm(esc(t.ticker)) + '</td><td class="' + (t.side === "BUY" ? "up" : "down") + '">' + (t.side === "BUY" ? "매수" : "매도") + "</td><td>" + t.qty + "</td><td>" + usd(t.market_price) + "</td><td>" + usd(t.fill_price) + "</td><td>" + usd(t.amount) + "</td><td>" + usd(t.est_slippage) + "</td><td>" + usd(t.cash_after) + "</td><td>" + (t.realized_pnl ? usd(t.realized_pnl) : "–") + "</td><td>" + esc(t.stop || "–") + " / " + esc(t.target || "–") + '</td><td class="reason">' + esc(t.reason) + "</td></tr>";
        }).join("") + "</table></div>";
    } else h += '<div class="tblwrap"><div class="empty">아직 거래가 없습니다.</div></div>';
    root.innerHTML = h;
  }

  Promise.all([get("portfolio.json"), get("performance.json"), get("trades.csv", true)])
    .then(function (r) { render(r[0], r[1], parseCSV(r[2])); })
    .catch(function (e) { root.innerHTML = '<div class="warn">기록을 불러오지 못했습니다: ' + esc(e.message) + "</div>"; });
})();
