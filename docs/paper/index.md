---
layout: default
title: 모의투자
---
<link rel="stylesheet" href="{{ '/assets/paper.css' | relative_url }}">
<section class="hero">
  <p class="eyebrow">PAPER TRADING · 가상 거래</p>
  <h1>미국 주식<br>1개월 모의투자</h1>
  <p class="lead">$10,000 가상 자금, 레버리지·공매도·옵션 없음. 실제 계좌 접속이나 주문은 없으며 모든 체결은 가상입니다.</p>
</section>

<nav class="toc" style="position:static">
  <a href="{{ '/paper/daily/' | relative_url }}">일일 보고서</a>
  <a href="{{ '/paper/strategy/' | relative_url }}">투자 전략·변경 이력</a>
  <a href="{{ '/paper/data/trades.csv' | relative_url }}">trades.csv</a>
  <a href="{{ '/paper/data/portfolio.json' | relative_url }}">portfolio.json</a>
  <a href="{{ '/paper/data/performance.json' | relative_url }}">performance.json</a>
</nav>

<div id="paper" data-base="{{ '/paper/data' | relative_url }}">불러오는 중…</div>

<p class="note">시세 출처: Yahoo Finance chart API(지연·비공식 가능). 체결가는 시장가에 슬리피지 0.05%를 반영한 가상 값이며 수수료는 $0 가정입니다. MDD는 기록 시점(스냅샷) 기준이라 장중 변동은 반영하지 않습니다. 투자 권유가 아닙니다.</p>

<script src="{{ '/assets/paper.js' | relative_url }}" defer></script>
