// 공통 상단 내비게이션 — 모든 페이지에서 카테고리 드롭다운으로 바로 이동
(function () {
  const MENUS = [
    { t: '시장', items: [
      ['/', '🏠 섹터 대시보드', '11개 GICS 섹터 실시간 시세'],
      ['/pbr.html', '📐 시장 PBR·PER', '코스피·코스닥·미국 밸류에이션'],
      ['/leaders.html', '🏆 주도 업종', '일·주·월·연 업종 수익률 순위'],
      ['/defense.html', '🛡️ 방산 맵', '무기 밸류체인·방산 기업 지도'],
      ['/semi.html', '💠 반도체 소부장 맵', '8대공정별 기업·제품 사진 지도'],
    ]},
    { t: '실적', items: [
      ['/screener.html', '📊 실적 스크리닝', '성장·연속증가·흑자전환 + 잠정 반영'],
      ['/flash.html', '⚡ 잠정실적 속보', '실적 공시 실시간 피드'],
      ['/insider.html', '💰 내부자 매수', '임원·대주주 1억↑ 장내매수'],
    ]},
    { t: '종목분석', items: [
      ['/valuefilter.html', '🎯 밸류 필터', 'PBR·PER·배당 조건 검색 + 엑셀'],
      ['/bands.html', '📉 밴드·V차트', 'PER·PBR·PSR 밴드 + V차트 + 비용구조'],
      ['/deep.html', '🔬 종목 딥다이브', '품목별 매출·판가·물량·가동률·수주'],
      ['/notes.html', '📝 종목 특장점', '산업별 강점·매출비중 노트'],
      ['/ir.html', '🎤 IR 노트', '탐방·컨콜·인터뷰 + 내 메모'],
    ]},
    { t: '트렌드', items: [
      ['/trends.html', '📈 트렌드 · 뷰티', '검색·수출·브랜드 순위·레딧'],
      ['/trends.html#channels', '🛒 채널별 순위', '올리브영·아마존·화해·네이버'],
    ]},
    { t: '리서치', items: [
      ['/reports.html', '📑 리포트', '산업·종목·해외(번역) 리서치'],
      ['/blog.html', '📓 블로그', '구독 블로거 글 자동 수집'],
    ]},
  ];

  const css = `
  #gnav { position:sticky; top:0; z-index:40; background:#fff; border-bottom:1px solid #e8eaef;
    font-family:-apple-system,"Segoe UI","Malgun Gothic",sans-serif; box-shadow:0 1px 3px rgba(20,30,60,.05); }
  #gnav .in { max-width:1140px; margin:0 auto; display:flex; align-items:center; gap:2px; padding:0 12px; height:46px; }
  #gnav .brand { font-weight:900; font-size:14px; color:#1a2a4a; text-decoration:none; margin-right:10px; white-space:nowrap; }
  #gnav .cat { position:relative; }
  #gnav .cat > button { border:none; background:none; font:inherit; font-size:13.5px; font-weight:700; color:#374151;
    padding:0 13px; height:46px; cursor:pointer; border-bottom:2.5px solid transparent; white-space:nowrap; }
  #gnav .cat > button:hover { color:#2f6df6; }
  #gnav .cat.cur > button { color:#2f6df6; border-bottom-color:#2f6df6; }
  #gnav .dd { display:none; position:absolute; left:0; top:46px; background:#fff; border:1px solid #e5e8ee;
    border-radius:0 0 12px 12px; box-shadow:0 10px 24px rgba(20,30,60,.12); min-width:250px; padding:8px; }
  #gnav .cat.open .dd { display:block; }
  #gnav .dd a { display:block; padding:9px 11px; border-radius:8px; text-decoration:none; }
  #gnav .dd a:hover { background:#f2f6fe; }
  #gnav .dd a.on { background:#eef4ff; }
  #gnav .dd .n { font-size:13px; font-weight:800; color:#1a1f2e; }
  #gnav .dd a.on .n { color:#2f6df6; }
  #gnav .dd .d { font-size:11px; color:#8a93a2; margin-top:1px; }
  #gnav .sp { flex:1; }
  @media (max-width:760px) {
    #gnav .in { overflow-x:auto; -webkit-overflow-scrolling:touch; scrollbar-width:none; }
    #gnav .in::-webkit-scrollbar { display:none; }
    #gnav .brand { font-size:13px; }
    #gnav .cat > button { padding:0 10px; font-size:13px; }
    #gnav .dd { position:fixed; left:8px; right:8px; top:46px; min-width:0; border-radius:12px; }
  }`;

  const path = location.pathname === '/index.html' ? '/' : location.pathname;
  const isCur = h => h.split('#')[0] === path;

  const el = document.createElement('nav');
  el.id = 'gnav';
  el.innerHTML = '<style>' + css + '</style><div class="in">' +
    '<a class="brand" href="/">📊 대시보드</a>' +
    MENUS.map((m, i) => {
      const cur = m.items.some(it => isCur(it[0]));
      return `<div class="cat ${cur ? 'cur' : ''}" data-i="${i}">
        <button type="button">${m.t} ▾</button>
        <div class="dd">${m.items.map(it =>
          `<a href="${it[0]}" class="${isCur(it[0]) && (location.hash ? it[0].includes(location.hash) : !it[0].includes('#')) ? 'on' : ''}">
             <div class="n">${it[1]}</div><div class="d">${it[2]}</div></a>`).join('')}</div>
      </div>`;
    }).join('') + '<span class="sp"></span></div>';

  document.body.prepend(el);

  // 카테고리 클릭으로 열고 닫기 (모바일 대응), 바깥 클릭 시 닫기
  el.querySelectorAll('.cat > button').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const cat = btn.parentElement;
      const was = cat.classList.contains('open');
      el.querySelectorAll('.cat.open').forEach(c => c.classList.remove('open'));
      if (!was) cat.classList.add('open');
    });
  });
  // 데스크톱 호버 오픈
  if (matchMedia('(hover:hover) and (min-width:761px)').matches) {
    el.querySelectorAll('.cat').forEach(cat => {
      cat.addEventListener('mouseenter', () => {
        el.querySelectorAll('.cat.open').forEach(c => c.classList.remove('open'));
        cat.classList.add('open');
      });
      cat.addEventListener('mouseleave', () => cat.classList.remove('open'));
    });
  }
  document.addEventListener('click', () => el.querySelectorAll('.cat.open').forEach(c => c.classList.remove('open')));
  // 같은 페이지 내 해시 링크(트렌드 → 채널별 순위) 이동 시 리로드
  el.querySelectorAll('.dd a').forEach(a => {
    a.addEventListener('click', e => {
      const href = a.getAttribute('href');
      if (href.includes('#') && href.split('#')[0] === path) { e.preventDefault(); location.href = href; location.reload(); }
    });
  });
})();
