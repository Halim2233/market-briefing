/* 마크다운으로 만들어진 평평한 HTML을 카드/타일/목차로 다듬는다.
   각 단계는 독립적이고, 실패해도 원문(일반 텍스트)이 그대로 남는다. */
(function () {
  function safe(fn) { try { fn(); } catch (e) { if (window.console) console.error(e); } }

  function run() {
    var root = document.querySelector('.report-body');
    if (!root) return;
    safe(function () { snapshotTiles(root); });
    safe(function () { issueCards(root); });
    safe(function () { toneItems(root); });
    safe(function () { buildToc(root); });
    safe(function () { foldSources(root); });
    safe(function () { colorize(root); });
    safe(openHash);
  }

  function nextEl(el) { var n = el.nextElementSibling; return n; }
  function h2With(root, word) {
    var hs = root.querySelectorAll('h2');
    for (var i = 0; i < hs.length; i++) if (hs[i].textContent.indexOf(word) !== -1) return hs[i];
    return null;
  }

  /* 1) 시장 스냅샷 → 타일 */
  function snapshotTiles(root) {
    var h = h2With(root, '시장 스냅샷');
    if (!h) return;
    var ul = nextEl(h);
    if (!ul || ul.tagName !== 'UL') return;
    var re = /^(.+?)\s+(-?[\d,]+(?:\.\d+)?)\s*\(\s*[^\d+\-−]*\s*([+\-−]?\d+(?:\.\d+)?)%\s*\)/;
    var grid = document.createElement('div');
    grid.className = 'tiles';
    var items = ul.querySelectorAll(':scope > li');
    for (var i = 0; i < items.length; i++) {
      var m = re.exec(items[i].textContent.replace(/\s+/g, ' ').trim());
      if (!m) return; // 하나라도 형식이 다르면 원래 목록 유지
      var pct = parseFloat(m[3].replace('−', '-'));
      var cls = pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat';
      var t = document.createElement('div');
      t.className = 'tile';
      t.innerHTML = '<div class="n"></div><div class="v"></div><span class="p ' + cls + '"></span>';
      t.querySelector('.n').textContent = m[1];
      t.querySelector('.v').textContent = m[2];
      t.querySelector('.p').textContent = (pct > 0 ? '▲ ' : pct < 0 ? '▼ ' : '– ') + Math.abs(pct).toFixed(2) + '%';
      grid.appendChild(t);
    }
    ul.parentNode.replaceChild(grid, ul);
  }

  /* 2) 굵은 제목 한 줄 + 목록 → 카드 */
  function issueCards(root) {
    var kids = Array.prototype.slice.call(root.children);
    kids.forEach(function (p) {
      if (p.tagName !== 'P' || p.children.length !== 1 || p.firstElementChild.tagName !== 'STRONG') return;
      if (p.textContent.trim() !== p.firstElementChild.textContent.trim()) return;
      var ul = nextEl(p);
      if (!ul || ul.tagName !== 'UL') return;
      var card = document.createElement('div');
      card.className = 'item-card';
      var ct = document.createElement('p');
      ct.className = 'ct';
      ct.textContent = p.textContent.trim();
      p.parentNode.insertBefore(card, p);
      card.appendChild(ct);
      card.appendChild(ul);
      p.parentNode.removeChild(p);
    });
  }

  /* 3) "확신도"가 들어간 결론 항목 → 강세/약세/중립 색 */
  function toneItems(root) {
    var lis = root.querySelectorAll('li');
    for (var i = 0; i < lis.length; i++) {
      var ss = lis[i].querySelectorAll('strong');
      if (!ss.length) continue;
      var last = ss[ss.length - 1].textContent;
      if (last.indexOf('확신도') === -1) continue;
      var bull = /강세/.test(last), bear = /약세/.test(last);
      lis[i].className += ' tone ' + (bull && !bear ? 'bull' : bear && !bull ? 'bear' : 'neutral');
    }
  }

  /* 4) 상단 목차 칩 */
  function buildToc(root) {
    var hs = root.querySelectorAll('h2');
    if (hs.length < 3) return;
    var nav = document.createElement('nav');
    nav.className = 'toc';
    nav.setAttribute('aria-label', '목차');
    for (var i = 0; i < hs.length; i++) {
      var id = 'sec-' + i;
      hs[i].id = id;
      var a = document.createElement('a');
      a.href = '#' + id;
      a.textContent = hs[i].textContent.replace(/\s*\(.*?\)\s*/g, '').trim();
      a.addEventListener('click', function (ev) {
        var t = document.getElementById(this.getAttribute('href').slice(1));
        if (t && t.tagName === 'DETAILS') t.open = true;
      });
      nav.appendChild(a);
    }
    root.parentNode.insertBefore(nav, root);

    if (!('IntersectionObserver' in window)) return;
    var links = nav.querySelectorAll('a');
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        for (var k = 0; k < links.length; k++) {
          var on = links[k].getAttribute('href') === '#' + en.target.id;
          links[k].className = on ? 'on' : '';
          if (on && nav.scrollTo) nav.scrollTo({ left: links[k].offsetLeft - 24, behavior: 'smooth' });
        }
      });
    }, { rootMargin: '-120px 0px -70% 0px' });
    for (var j = 0; j < hs.length; j++) io.observe(hs[j]);
  }

  /* 5) 뉴스 출처는 접어 둔다 */
  function foldSources(root) {
    var h = h2With(root, '뉴스 출처');
    if (!h) return;
    var d = document.createElement('details');
    d.className = 'fold';
    d.id = h.id;
    var s = document.createElement('summary');
    s.textContent = h.textContent.trim();
    d.appendChild(s);
    var n = h.nextSibling;
    while (n) { var nx = n.nextSibling; d.appendChild(n); n = nx; }
    h.parentNode.replaceChild(d, h);
  }

  /* 6) +1.23% / -4.56% 색칠 */
  function colorize(root) {
    var re = /([+\-−]\d+(?:\.\d+)?%)/g;
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var targets = [], n;
    while ((n = walker.nextNode())) {
      if (!re.test(n.nodeValue)) { re.lastIndex = 0; continue; }
      re.lastIndex = 0;
      var skip = n.parentNode.closest && n.parentNode.closest('a, code, .tile, summary');
      if (!skip) targets.push(n);
    }
    targets.forEach(function (node) {
      var frag = document.createDocumentFragment();
      node.nodeValue.split(re).forEach(function (part) {
        if (!part) return;
        if (re.test(part)) {
          re.lastIndex = 0;
          var sp = document.createElement('span');
          sp.className = part.charAt(0) === '+' ? 'up' : 'down';
          sp.textContent = part;
          frag.appendChild(sp);
        } else {
          re.lastIndex = 0;
          frag.appendChild(document.createTextNode(part));
        }
      });
      node.parentNode.replaceChild(frag, node);
    });
  }

  function openHash() {
    if (!location.hash) return;
    var t = document.getElementById(location.hash.slice(1));
    if (t && t.tagName === 'DETAILS') t.open = true;
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run);
  else run();
})();
