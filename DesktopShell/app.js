'use strict';
/* 影视舱 MediaShell - renderer */
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const MS = window.MediaShell;

const state = {
  config: null,
  sites: [],
  site: null,        // current selected site
  view: 'home',
  typeMap: {},       // siteKey -> {name:id}
  favorites: loadLS('ms_favorites', []),
  history: loadLS('ms_history', []),
  playerHls: null,
  currentPlay: null, // {title, episodes, srcIdx}
};

function loadLS(k, def) { try { return JSON.parse(localStorage.getItem(k)) || def; } catch (e) { return def; } }
function saveLS(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.classList.remove('hidden');
  clearTimeout(t._t); t._t = setTimeout(() => t.classList.add('hidden'), 2200);
}
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function isCMS(site) { return /^https?:\/\//i.test(String(site.api || '')); }

// ---------- config load ----------
async function loadConfig() {
  const raw = await MS.readConfig('YSCSites.json');
  const cfg = JSON.parse(raw);
  state.config = cfg;
  state.sites = cfg.sites || [];
  if (!state.site && state.sites.length) state.site = state.sites[0];
  renderSites();
  $('#siteCount').textContent = '(' + state.sites.length + ')';
  if (state.view === 'home') renderHome();
}

function renderSites() {
  const box = $('#siteList'); box.innerHTML = '';
  state.sites.forEach((s) => {
    const d = document.createElement('div');
    const cms = isCMS(s);
    d.className = 'site-item' + (state.site && s.key === state.site.key ? ' active' : '') + (cms ? '' : ' spider');
    d.innerHTML = esc(s.name || s.key) + '<span class="kind">' + (cms ? '点播 · CMS' : '插件源 (桌面端不可用)') + '</span>';
    d.title = cms ? s.api : '该站需安卓影视仓插件，桌面端不支持';
    d.onclick = () => {
      if (!cms) { toast('该源依赖影视仓插件(jar)，桌面壳无法运行，请用安卓影视仓'); return; }
      state.site = s; renderSites();
      if (state.view === 'home' || state.view === 'search' || state.view === 'favorite' || state.view === 'history') renderHome();
    };
    box.appendChild(d);
  });
}

// ---------- CMS helpers ----------
function apiBase(site) { return String(site.api).replace(/[?&]$/, ''); }
function join(base, params) {
  const q = Object.keys(params).filter((k) => params[k] !== undefined && params[k] !== null)
    .map((k) => encodeURIComponent(k) + '=' + encodeURIComponent(params[k])).join('&');
  return base + (base.indexOf('?') >= 0 ? '&' : '?') + q;
}
async function cmsGet(url, timeout = 15000) {
  const r = await MS.httpGet(url, { 'User-Agent': 'okhttp/3.15', 'Accept': 'application/json,text/plain,*/*' }, timeout);
  if (r.error || !r.body) throw new Error(r.error || '空响应');
  try { return JSON.parse(r.body); }
  catch (e) { throw new Error('接口返回非 JSON：' + r.body.slice(0, 60)); }
}
async function typeMap(site) {
  if (state.typeMap[site.key]) return state.typeMap[site.key];
  const map = {};
  try {
    const d = await cmsGet(join(apiBase(site), { ac: 'list' }), 12000);
    const arr = d.list || d.class || [];
    (Array.isArray(arr) ? arr : Object.values(arr)).forEach((x) => {
      if (x && x.type_name) map[x.type_name] = x.type_id;
    });
  } catch (e) {}
  if (!Object.keys(map).length) {
    try {
      const d = await cmsGet(join(apiBase(site), { ac: 'videolist', pg: 1 }), 12000);
      (d.class || []).forEach((x) => { if (x && x.type_name) map[x.type_name] = x.type_id; });
      (d.list || []).forEach((v) => { if (v && v.type_name) map[v.type_name] = v.type_id; });
    } catch (e) {}
  }
  state.typeMap[site.key] = map;
  return map;
}

// ---------- views ----------
function setView(v) {
  state.view = v;
  $$('.tab').forEach((b) => b.classList.toggle('active', b.dataset.view === v));
  if (v === 'home') renderHome();
  else if (v === 'search') renderSearch();
  else if (v === 'live') renderLive();
  else if (v === 'favorite') renderStore('favorite');
  else if (v === 'history') renderStore('history');
}

// ---------- TV-style home ----------
let bannerTimer = null;
let bannerItems = [];
let bannerIdx = 0;

function renderHome() {
  const s = state.site;
  const c = $('#content');
  if (!s || !isCMS(s)) { c.innerHTML = '<div class="empty">请从左侧选择一个 CMS 采集站</div>'; return; }
  if (bannerTimer) { clearInterval(bannerTimer); bannerTimer = null; }
  const cats = s.categories || [];
  c.innerHTML =
    '<div id="banner" class="banner"><div class="binfo"><div class="btitle"><span class="spinner"></span>正在加载首页…</div></div></div>' +
    '<div id="catBar" class="cat-bar"></div>' +
    '<div id="tvRows"><div class="tv-row"><div class="row-head"><span class="bar"></span><h3>最近更新</h3></div>' +
    '<div class="hscroll"><div class="empty"><span class="spinner"></span>加载中…</div></div></div></div>';
  loadHomeData(s, cats);
}

async function loadHomeData(site, cats) {
  const c = $('#content');
  let first = { list: [] };
  try { first = await cmsGet(join(apiBase(site), { ac: 'videolist', pg: 1 }), 20000); }
  catch (e) {}
  const items = first.list || [];
  buildBanner(site, items.slice(0, 8));
  bindCatBar(site, cats, items, first);
  renderTVRows(site, items, first);
}

function buildBanner(site, items) {
  const box = $('#banner'); if (!box) return;
  if (bannerTimer) { clearInterval(bannerTimer); bannerTimer = null; }
  const picks = items.filter((v) => v.vod_pic && /^https?:/i.test(v.vod_pic)).slice(0, 6);
  if (!picks.length) {
    box.innerHTML = '<div class="binfo"><span class="btag">影视舱</span><div class="btitle">' + esc(site.name) + '</div>' +
      '<div class="bdesc">该站首页暂未返回可展示的横幅图片，可点下方分类或使用搜索找片。</div></div>';
    return;
  }
  bannerItems = picks; bannerIdx = 0;
  box.innerHTML = picks.map((v, i) =>
    '<div class="bslide" data-i="' + i + '" style="position:absolute;inset:0;background-image:url(' + esc(v.vod_pic) + ');' +
    'background-size:cover;background-position:center;opacity:' + (i === 0 ? 1 : 0) + ';transition:opacity .6s;"></div>').join('') +
    '<button class="bnav bprev">‹</button><button class="bnav bnext">›</button>' +
    '<div class="binfo"><span class="btag">热播推荐</span><div class="btitle" id="bTitle"></div><div class="bdesc" id="bDesc"></div><div class="bplay">▶ 立即观看</div></div>' +
    '<div class="bdot" id="bDot">' + picks.map((_, i) => '<i class="' + (i === 0 ? 'on' : '') + '" data-i="' + i + '"></i>').join('') + '</div>';
  function show(i) {
    bannerIdx = (i + picks.length) % picks.length;
    $$('.bslide', box).forEach((el, k) => el.style.opacity = (k === bannerIdx ? 1 : 0));
    $$('#bDot i', box).forEach((el, k) => el.classList.toggle('on', k === bannerIdx));
    const v = picks[bannerIdx];
    $('#bTitle', box).textContent = v.vod_name || '';
    $('#bDesc', box).textContent = (v.vod_content || '').replace(/<[^>]+>/g, '').slice(0, 110) || (v.vod_remarks || '') || v.vod_class || '';
  }
  show(0);
  $('.bprev', box).onclick = (e) => { e.stopPropagation(); show(bannerIdx - 1); };
  $('.bnext', box).onclick = (e) => { e.stopPropagation(); show(bannerIdx + 1); };
  $$('#bDot i', box).forEach((el) => { el.onclick = (e) => { e.stopPropagation(); show(+el.dataset.i); }; });
  box.onclick = () => { const v = picks[bannerIdx]; if (v) openDetail(site, v.vod_id, v.vod_name); };
  bannerTimer = setInterval(() => show(bannerIdx + 1), 5000);
}

function bindCatBar(site, cats, items, first) {
  const bar = $('#catBar'); if (!bar) return;
  const pills = [{ name: '🔥全部', id: null }].concat(cats.map((n) => ({ name: n, id: n })));
  bar.innerHTML = pills.map((p, i) => '<div class="cat-pill' + (i === 0 ? ' on' : '') + '" data-cat="' + esc(p.id || '') + '">' + esc(p.name) + '</div>').join('');
  $$('.cat-pill', bar).forEach((el) => el.onclick = async () => {
    $$('.cat-pill', bar).forEach((x) => x.classList.remove('on'));
    el.classList.add('on');
    const cat = el.dataset.cat;
    if (!cat) { renderTVRows(site, items, first); return; }
    const box = $('#tvRows');
    box.innerHTML = '<div class="tv-row"><div class="row-head"><span class="bar"></span><h3>' + esc(cat) + '</h3>' +
      '<span class="more" id="catMore">更多 ›</span></div><div class="hscroll"><div class="empty"><span class="spinner"></span>加载中…</div></div></div>';
    let tid;
    try { tid = (await typeMap(site))[cat]; } catch (e) {}
    if (!tid) {
      $('.hscroll', box).innerHTML = '<div class="empty">分类「' + esc(cat) + '」未解析到 type_id，可能是空壳父类，请试其它分类或搜索。</div>';
      return;
    }
    try {
      const d = await cmsGet(join(apiBase(site), { ac: 'videolist', t: tid, pg: 1 }), 20000);
      $('.hscroll', box).innerHTML = (d.list || []).map(posterHTML).join('') || '<div class="empty">该分类暂无数据</div>';
      bindPosters($('.hscroll', box), site);
      $('#catMore').onclick = () => openCategory(cat);
      state._catTid = { [cat]: tid };
    } catch (e) { $('.hscroll', box).innerHTML = '<div class="empty">加载失败：' + esc(e.message) + '</div>'; }
  });
}

function renderTVRows(site, items, first) {
  const box = $('#tvRows'); if (!box) return;
  if (!items.length) { box.innerHTML = '<div class="empty">该站首页暂无数据，可尝试其它站或搜索</div>'; return; }
  const hscroll = (arr) => '<div class="hscroll">' + (arr.length ? arr.map(posterHTML).join('') : '<div class="empty">暂无数据</div>') + '</div>';
  box.innerHTML =
    '<div class="tv-row"><div class="row-head"><span class="bar"></span><h3>最近更新</h3>' +
    '<span class="more" data-more="all">更多 ›</span></div>' + hscroll(items.slice(0, 24)) + '</div>' +
    (items.length > 8 ? '<div class="tv-row"><div class="row-head"><span class="bar"></span><h3>为你推荐</h3></div>' + hscroll(items.slice(8, 32)) + '</div>' : '');
  $$('.hscroll', box).forEach((el) => bindPosters(el, site));
  const moreAll = $('[data-more="all"]', box);
  if (moreAll) moreAll.onclick = () => openCategory('__all__');
}

async function loadRecent(site) {
  const box = $('#recent'); if (!box) return;
  try {
    const d = await cmsGet(join(apiBase(site), { ac: 'videolist', pg: 1 }), 20000);
    box.innerHTML = (d.list || []).slice(0, 24).map(posterHTML).join('') || '<div class="empty">暂无数据</div>';
    bindPosters(box, site);
  } catch (e) { box.innerHTML = '<div class="empty">加载失败：' + esc(e.message) + '</div>'; }
}

function posterHTML(v) {
  const pic = v.vod_pic && /^https?:/i.test(v.vod_pic)
    ? '<div class="thumb" style="background-image:url(' + esc(v.vod_pic) + ')">' +
      '<div class="remarks">' + esc(v.vod_remarks || '') + '</div></div>'
    : '<div class="thumb"><span class="ph">▶</span><div class="remarks">' + esc(v.vod_remarks || '') + '</div></div>';
  return '<div class="poster" data-id="' + esc(v.vod_id) + '" data-name="' + esc(v.vod_name) + '">' + pic +
    '<div class="pname">' + esc(v.vod_name) + '</div></div>';
}

function bindPosters(box, site) {
  $$('.poster', box).forEach((el) => el.onclick = () => openDetail(site, el.dataset.id, el.dataset.name));
}

async function openCategory(name) {
  const s = state.site;
  const c = $('#content');
  const isAll = (name === '__all__');
  const title = isAll ? '全部资源' : name;
  c.innerHTML = '<div class="crumb">‹ 返回 ' + esc(s.name) + '</div>' +
    '<div class="section-title">' + esc(title) + ' <small><span class="spinner"></span>加载中…</small></div><div id="catList" class="poster-grid"></div><div id="catPager" class="pager"></div>';
  $('.crumb').onclick = renderHome;
  if (isAll) { await loadCategoryPage(s, undefined, title, 1); return; }
  let tid = (state._catTid || {})[name];
  if (!tid) {
    try { tid = (await typeMap(s))[name]; } catch (e) {}
  }
  if (!tid) {
    $('#catList').innerHTML = '<div class="empty">无法解析分类「' + esc(name) + '」的 type_id。<br>该分类可能是父级空壳，或站点接口暂不可用。<br>可尝试顶部搜索框找片。</div>';
    return;
  }
  await loadCategoryPage(s, tid, name, 1);
}

async function loadCategoryPage(site, tid, name, pg) {
  const listBox = $('#catList'); const pager = $('#catPager');
  if (!listBox) return;
  listBox.innerHTML = '<div class="empty"><span class="spinner"></span>加载中…</div>';
  try {
    const d = await cmsGet(join(apiBase(site), { ac: 'videolist', t: tid, pg }), 20000);
    listBox.innerHTML = (d.list || []).map(posterHTML).join('') || '<div class="empty">该分类暂无数据</div>';
    bindPosters(listBox, site);
    const total = Number(d.pagecount || 1) || 1;
    pager.innerHTML = '<button id="prevPage"' + (pg <= 1 ? ' disabled' : '') + '>‹ 上一页</button>' +
      '<span class="page-info">第 ' + pg + ' / ' + total + ' 页 · 共 ' + (d.total || 0) + ' 部</span>' +
      '<button id="nextPage"' + (pg >= total ? ' disabled' : '') + '>下一页 ›</button>';
    const pv = $('#prevPage'), nv = $('#nextPage');
    if (pv) pv.onclick = () => loadCategoryPage(site, tid, name, pg - 1);
    if (nv) nv.onclick = () => loadCategoryPage(site, tid, name, pg + 1);
    const st = $('.section-title small', $('#content'));
    if (st) st.textContent = tid ? ('分类ID ' + tid) : ('共 ' + (d.total || 0) + ' 部');
  } catch (e) { listBox.innerHTML = '<div class="empty">加载失败：' + esc(e.message) + '</div>'; }
}

async function openDetail(site, id, fallbackName) {
  const c = $('#content');
  c.innerHTML = '<div class="empty"><span class="spinner"></span>加载详情…</div>';
  let v;
  try {
    const d = await cmsGet(join(apiBase(site), { ac: 'videolist', id }), 20000);
    v = (d.list || [])[0];
  } catch (e) {}
  if (!v) v = { vod_id: id, vod_name: fallbackName };
  const playFrom = String(v.vod_play_from || '').split('$$$').filter(Boolean);
  const playUrl = String(v.vod_play_url || '').split('$$$').filter(Boolean);
  const sources = (playUrl.length ? playUrl : ['']).map((blk, i) => ({
    name: playFrom[i] || ('线路' + (i + 1)),
    eps: blk.split('#').map((seg) => {
      const p = seg.indexOf('$');
      return p > 0 ? { name: seg.slice(0, p), url: seg.slice(p + 1) } : { name: '第' + (i + 1) + '集', url: seg };
    }).filter((e) => /^https?:\/\//i.test(e.url) || /\.m3u8?/i.test(e.url)),
  }));
  const pic = v.vod_pic && /^https?:/i.test(v.vod_pic)
    ? ' style="background-image:url(' + esc(v.vod_pic) + ')"' : '';
  c.innerHTML = '<div class="crumb">‹ 返回列表</div><div class="detail">' +
    '<div class="cover"' + pic + '></div><div class="info">' +
    '<h2>' + esc(v.vod_name || fallbackName) + '</h2>' +
    '<div class="meta">分类：<b>' + esc(v.vod_class || '-') + '</b>　年份：' + esc(v.vod_year || '-') +
    '　主演：' + esc((v.vod_actor || '').slice(0, 80) || '-') + '<br>来源站：<b>' + esc(site.name) + '</b>　备注：' + esc(v.vod_remarks || '-') + '</div>' +
    '<div class="desc">' + esc((v.vod_content || '').replace(/<[^>]+>/g, '').slice(0, 300) || '暂无简介') + '</div>' +
    '<button class="playbtn" id="btnPlayFirst">▶ 立即播放</button>' +
    '<div id="srcTabs" class="src-tabs"></div><div id="epGrid" class="ep-grid"></div>' +
    '</div></div>';
  $('.crumb').onclick = () => { if (state.view === 'search') renderSearch(); else renderHome(); };
  const srcTabs = $('#srcTabs'), epGrid = $('#epGrid');
  let cur = 0;
  function renderEps() {
    srcTabs.innerHTML = sources.map((s, i) => '<div class="src-tab' + (i === cur ? ' active' : '') + '" data-i="' + i + '">' + esc(s.name) + '</div>').join('');
    $$('.src-tab', srcTabs).forEach((el) => el.onclick = () => { cur = +el.dataset.i; renderEps(); });
    epGrid.innerHTML = (sources[cur] ? sources[cur].eps : []).map((e, i) =>
      '<div class="ep" data-i="' + i + '">' + esc(e.name) + '</div>').join('') || '<div class="muted">未解析到可播放地址</div>';
    $$('.ep', epGrid).forEach((el) => el.onclick = () => {
      $$('.ep', epGrid).forEach((x) => x.classList.remove('active'));
      el.classList.add('active');
      const ep = sources[cur].eps[+el.dataset.i];
      openPlayer(v.vod_name || fallbackName, [ep], 0, { site: site.name, id });
    });
  }
  renderEps();
  $('#btnPlayFirst').onclick = () => {
    const eps = sources[cur] ? sources[cur].eps : [];
    if (!eps.length) { toast('没有可播放地址'); return; }
    openPlayer(v.vod_name || fallbackName, eps, 0, { site: site.name, id });
  };
  addHistory({ name: v.vod_name || fallbackName, id, site: site.name, pic: v.vod_pic, type: 'vod' });
}

// ---------- player ----------
function openPlayer(title, episodes, idx, meta) {
  state.currentPlay = { title, episodes, idx };
  $('#player').classList.remove('hidden');
  $('#playerTitle').textContent = title + (episodes.length > 1 ? ' · ' + (episodes[idx] ? episodes[idx].name : '') : '');
  const list = $('#episodeList');
  list.innerHTML = episodes.map((e, i) => '<div class="ep' + (i === idx ? ' active' : '') + '" data-i="' + i + '">' + esc(e.name) + '</div>').join('');
  $('#episodeCount').textContent = '(' + episodes.length + ')';
  $$('.ep', list).forEach((el) => el.onclick = () => {
    $$('.ep', list).forEach((x) => x.classList.remove('active'));
    el.classList.add('active');
    idx = +el.dataset.i;
    if (state.currentPlay) state.currentPlay.idx = idx;
    $('#playerTitle').textContent = title + (episodes.length > 1 ? ' · ' + (episodes[idx] ? episodes[idx].name : '') : '');
    playEpisode(episodes[idx], title);
  });
  $('#btnExternal').onclick = () => {
    const ep = episodes[state.currentPlay ? state.currentPlay.idx : idx];
    if (!ep) return;
    MS.openWithPlayer(ep.url, title + '_' + ep.name).then((r) => toast(r && r.error ? '调用失败' : '已用系统播放器打开'));
  };
  playEpisode(episodes[idx], title);
}
function playEpisode(ep, title) {
  if (!ep || !ep.url) return;
  const video = $('#video'); const msg = $('#playerMsg');
  msg.classList.add('hidden');
  if (state.playerHls) { state.playerHls.destroy(); state.playerHls = null; }
  video.pause();
  const url = ep.url;
  const isHls = /\.m3u8?(\?|$)/i.test(url);
  if (isHls && window.Hls && window.Hls.isSupported()) {
    const hls = new window.Hls({ enableWorker: true, lowLatencyMode: false });
    hls.loadSource(url); hls.attachMedia(video);
    hls.on(window.Hls.Events.ERROR, (_e, data) => {
      if (data.fatal) {
        msg.textContent = '播放出错（' + data.type + '）。可点右上角「系统播放器」重试。';
        msg.classList.remove('hidden');
      }
    });
    state.playerHls = hls;
    video.play().catch(() => {});
  } else if (/^https?:\/\//i.test(url)) {
    video.src = url; video.play().catch(() => {});
  } else {
    msg.textContent = '无法识别的播放地址：' + url.slice(0, 80);
    msg.classList.remove('hidden');
  }
}
$('#btnPlayerClose').onclick = () => {
  const v = $('#video'); v.pause(); v.removeAttribute('src'); v.load();
  if (state.playerHls) { state.playerHls.destroy(); state.playerHls = null; }
  $('#player').classList.add('hidden');
};

// ---------- search ----------
function renderSearch() {
  $('#content').innerHTML = '<div class="section-title">搜索 <small>在当前站点内搜索；逐个站点可切换</small></div>' +
    '<div class="empty">在顶部搜索框输入关键词并回车，例如「短剧」「仙侠」</div>';
}
async function doSearch(kw) {
  const s = state.site;
  if (!s || !isCMS(s)) { toast('请先选择一个 CMS 站点'); return; }
  setView('search');
  const c = $('#content');
  c.innerHTML = '<div class="crumb">‹ 返回</div><div class="section-title">搜索「' + esc(kw) + '」<small>' + esc(s.name) + ' · <span class="spinner"></span>搜索中…</small></div><div id="searchList" class="poster-grid"></div>';
  $('.crumb').onclick = renderSearch;
  try {
    const d = await cmsGet(join(apiBase(s), { ac: 'videolist', wd: kw, pg: 1 }), 20000);
    const box = $('#searchList');
    box.innerHTML = (d.list || []).map(posterHTML).join('') || '<div class="empty">没有找到相关资源</div>';
    bindPosters(box, s);
    $('.section-title small').innerHTML = esc(s.name) + ' · 共 ' + (d.total || 0) + ' 条';
  } catch (e) { $('#searchList').innerHTML = '<div class="empty">搜索失败：' + esc(e.message) + '</div>'; }
}

// ---------- live ----------
let liveCache = null;
function parseTVLines(text) {
  const groups = []; let cur = null;
  text.split(/\r?\n/).forEach((line) => {
    line = line.trim(); if (!line) return;
    if (/#genre#\s*$/.test(line)) {
      const name = line.replace(/,#genre#\s*$/, '').trim();
      cur = { name, items: [] }; groups.push(cur); return;
    }
    const idx = line.indexOf(',');
    if (idx > 0 && cur) {
      const name = line.slice(0, idx).trim();
      const urls = line.slice(idx + 1).split(',').map((u) => u.trim()).filter((u) => /^https?:\/\//i.test(u));
      if (name && urls.length) cur.items.push({ name, urls });
    }
  });
  return groups.filter((g) => g.items.length);
}
function parseM3U(text) {
  const groups = [{ name: '频道', items: [] }]; let pending = null;
  text.split(/\r?\n/).forEach((line) => {
    line = line.trim();
    if (/^#EXTINF:/i.test(line)) { pending = line.replace(/^#EXTINF:[^,]*,/i, '').trim(); }
    else if (line && !/^#/.test(line) && /^https?:\/\//i.test(line)) {
      groups[0].items.push({ name: pending || ('频道' + (groups[0].items.length + 1)), urls: [line] }); pending = null;
    } else if (/^#EXTGRP:/i.test(line)) { /* ignore group tag */ }
  });
  return groups.filter((g) => g.items.length);
}
async function renderLive() {
  const c = $('#content');
  c.innerHTML = '<div class="section-title">直播 <small>IPTV / 平台直播 / 赛事</small></div><div class="empty"><span class="spinner"></span>加载直播列表…</div>';
  if (!liveCache) {
    liveCache = {};
    for (const name of ['TVLives.txt', 'PlatformLive.txt', 'BiliLive.txt']) {
      try { liveCache[name] = parseTVLines(await MS.readConfig(name)); } catch (e) { liveCache[name] = []; }
    }
    // 赛事直播为远程 m3u
    const m3us = [
      { name: '⚽赛事直播·虎牙', url: 'https://sub.ottiptv.cc/huyayqk.m3u' },
      { name: '🏀赛事直播·斗鱼', url: 'https://sub.ottiptv.cc/douyuyqk.m3u' },
      { name: '🎮平台轮播·歪歪', url: 'https://sub.ottiptv.cc/yylunbo.m3u' },
    ];
    for (const m of m3us) {
      try {
        const r = await MS.httpGet(m.url, { 'User-Agent': 'okHttp/Mod-1.5.0.0' }, 20000);
        if (r.body) liveCache[m.name] = parseM3U(r.body);
      } catch (e) {}
    }
  }
  let html = '';
  Object.keys(liveCache).forEach((key) => {
    const groups = liveCache[key]; if (!groups || !groups.length) return;
    html += '<div class="live-group"><h3>' + esc(key) + '</h3>';
    groups.forEach((g) => {
      html += '<div class="muted" style="margin:8px 0 6px">' + esc(g.name) + ' (' + g.items.length + ')</div><div class="live-grid">';
      g.items.forEach((it, gi) => {
        html += '<div class="live-item" data-key="' + esc(key) + '" data-g="' + esc(g.name) + '" data-i="' + gi + '" title="' + esc(it.urls[0]) + '">' + esc(it.name) + '</div>';
      });
      html += '</div>';
    });
    html += '</div>';
  });
  c.innerHTML = '<div class="section-title">直播 <small>点击频道播放 · 每条为独立线路</small></div>' + (html || '<div class="empty">直播列表为空</div>');
  $$('.live-item', c).forEach((el) => el.onclick = () => {
    const groups = liveCache[el.dataset.key];
    const g = groups.find((x) => x.name === el.dataset.g);
    const it = g.items[+el.dataset.i];
    openPlayer(it.name, it.urls.map((u, i) => ({ name: '线路' + (i + 1), url: u })), 0, { live: true });
  });
}

// ---------- favorite / history ----------
function renderStore(kind) {
  const arr = kind === 'favorite' ? state.favorites : state.history;
  const c = $('#content');
  c.innerHTML = '<div class="section-title">' + (kind === 'favorite' ? '我的收藏' : '观看历史') + ' <small>' + arr.length + ' 条</small></div>' +
    (arr.length ? '<div class="row-list">' + arr.map((x, i) =>
      '<div class="row-item" data-i="' + i + '"><div class="rthumb"' + (x.pic && /^https?:/i.test(x.pic) ? ' style="background-image:url(' + esc(x.pic) + ')"' : '') + '></div>' +
      '<div class="rinfo"><b>' + esc(x.name) + '</b><span>' + esc(x.site || '') + ' · ' + esc(x.type === 'live' ? '直播' : '点播') + '</span></div>' +
      '<button class="del" data-del="' + i + '">✕</button></div>').join('') + '</div>'
      : '<div class="empty">' + (kind === 'favorite' ? '还没有收藏，播放时可加入收藏' : '还没有观看记录') + '</div>');
  $$('.del', c).forEach((b) => b.onclick = (ev) => {
    ev.stopPropagation(); const i = +b.dataset.del; arr.splice(i, 1);
    if (kind === 'favorite') { state.favorites = arr; saveLS('ms_favorites', arr); } else { state.history = arr; saveLS('ms_history', arr); }
    renderStore(kind);
  });
}
function addHistory(item) {
  state.history = state.history.filter((x) => !(x.id === item.id && x.site === item.site));
  state.history.unshift(item); state.history = state.history.slice(0, 60);
  saveLS('ms_history', state.history);
}

// ---------- events ----------
$$('.tab').forEach((b) => b.onclick = () => setView(b.dataset.view));
$('#quickSearch').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { const kw = e.target.value.trim(); if (kw) doSearch(kw); }
});
$('#btnReload').onclick = async () => { await loadConfig(); state.typeMap = {}; liveCache = null; toast('配置已重新加载'); };
$('#btnImport').onclick = () => $('#importDialog').classList.remove('hidden');
$('#btnImportCancel').onclick = () => $('#importDialog').classList.add('hidden');
$('#btnImportOk').onclick = async () => {
  const url = $('#importUrl').value.trim(); const msg = $('#importMsg');
  if (!/^https?:\/\//i.test(url)) { msg.textContent = '请输入有效的 http(s) 地址'; return; }
  msg.textContent = '正在拉取…';
  try {
    const r = await MS.httpGet(url, { 'User-Agent': 'okhttp/3.15' }, 25000);
    const cfg = JSON.parse(r.body);
    if (!Array.isArray(cfg.sites) || !cfg.sites.length) throw new Error('配置中没有 sites');
    await MS.saveConfig('YSCSites.json', JSON.stringify(cfg, null, 2));
    await loadConfig();
    $('#importDialog').classList.add('hidden');
    toast('已导入 ' + cfg.sites.length + ' 个站点');
  } catch (e) { msg.textContent = '导入失败：' + e.message; }
};

(async function init() {
  try { $('#version').textContent = 'v' + (await MS.appVersion()); } catch (e) {}
  try { await loadConfig(); document.title = '影视舱 MediaShell · ' + state.sites.length + '站'; }
  catch (e) { $('#content').innerHTML = '<div class="empty">配置加载失败：' + esc(e.message) + '</div>'; }
})();
