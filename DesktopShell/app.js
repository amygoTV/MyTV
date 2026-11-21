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
  catList: {},       // siteKey -> [{id,name,pid}] 站点真实分类(来自 ac=list 的 class 字段)
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
// 苹果CMS ac=list 同时返回 list(视频)与 class(分类)。分类在 class，绝不能用 list 当分类。
// 返回 { map: {name:id}, cats: [{id,name,pid}] }
async function fetchCats(site) {
  if (state.catList[site.key]) return state.catList[site.key];
  let cats = [];
  try {
    const d = await cmsGet(join(apiBase(site), { ac: 'list' }), 12000);
    const arr = d.class || d.type || [];
    (Array.isArray(arr) ? arr : Object.values(arr)).forEach((x) => {
      if (x && x.type_name != null && x.type_id != null) {
        cats.push({ id: x.type_id, name: String(x.type_name), pid: x.type_pid != null ? x.type_pid : 0 });
      }
    });
  } catch (e) {}
  // 兜底：部分站点 class 为空，则从 videolist 的 list 里去重 type_name/type_id
  if (!cats.length) {
    try {
      const d = await cmsGet(join(apiBase(site), { ac: 'videolist', pg: 1 }), 12000);
      const seen = {};
      (d.list || []).forEach((v) => {
        if (v && v.type_name != null && v.type_id != null && !seen[v.type_name]) {
          seen[v.type_name] = 1;
          cats.push({ id: v.type_id, name: String(v.type_name), pid: v.type_id_1 != null ? v.type_id_1 : 0 });
        }
      });
    } catch (e) {}
  }
  state.catList[site.key] = cats;
  return cats;
}

async function typeMap(site) {
  if (state.typeMap[site.key]) return state.typeMap[site.key];
  const map = {};
  const cats = await fetchCats(site);
  cats.forEach((c) => { map[c.name] = c.id; });
  state.typeMap[site.key] = map;
  return map;
}

// 取某分类的 type_id：优先用配置 categories 里的名字精确匹配，再尝试别名/包含匹配
function resolveTid(site, name) {
  const cats = state.catList[site.key] || [];
  let c = cats.find((x) => x.name === name);
  if (c) return c.id;
  // 去括号与空白后再匹配
  const norm = (s) => String(s).replace(/[（(].*?[)）]/g, '').replace(/\s+/g, '').trim();
  c = cats.find((x) => norm(x.name) === norm(name));
  if (c) return c.id;
  c = cats.find((x) => norm(x.name).indexOf(norm(name)) >= 0 || norm(name).indexOf(norm(x.name)) >= 0);
  return c ? c.id : null;
}

// ---------- views ----------
function setView(v) {
  if (state.view === 'live' && v !== 'live') { try { liveStop(); } catch (e) {} }
  state.view = v;
  $$('.tab').forEach((b) => b.classList.toggle('active', b.dataset.view === v));
  if (v === 'home') renderHome();
  else if (v === 'search') renderSearch();
  else if (v === 'live') renderLive();
  else if (v === 'favorite') renderStore('favorite');
  else if (v === 'history') renderStore('history');
}

// 并发探测所有 CMS 站点，返回按响应速度排序的可用站点列表
async function probeAllSites() {
  const cands = state.sites.filter(isCMS);
  const out = [];
  await Promise.all(cands.map(async (s) => {
    const t0 = Date.now();
    try {
      const d = await cmsGet(join(apiBase(s), { ac: 'videolist', pg: 1 }), 9000);
      if (d && (d.list || []).length) out.push({ site: s, ms: Date.now() - t0, n: (d.list || []).length });
    } catch (e) {}
  }));
  out.sort((a, b) => a.ms - b.ms);
  return out;
}

// 自动挑一个最快的可用站点并切换过去
async function autoPickSite() {
  const btn = $('#btnAutoSite');
  if (btn) { btn.disabled = true; btn.textContent = '检测中…'; }
  const list = await probeAllSites();
  if (!list.length) {
    toast('所有采集站当前都不可用，请稍后重试');
    if (btn) { btn.disabled = false; btn.textContent = '🔄 自动切换可用站点'; }
    return;
  }
  const best = list[0].site;
  state.site = best;
  renderSites();
  renderHome();
  toast('已切换到 ' + best.name + '（' + list[0].ms + 'ms）');
}

// ---------- TV-style home ----------
let bannerTimer = null;
let bannerItems = [];
let bannerIdx = 0;
let homeToken = 0;          // 防止切换站点时旧请求回写覆盖新页面
let homeCache = {};         // siteKey -> {items, at} 首页内容缓存（减少重复请求）

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

// 首页：分类与视频列表并发拉取（ac=list 一次即可同时拿到 class + list），
// 避免原来“先 videolist 再 ac=list”的两次串行等待。
async function loadHomeData(site, cats) {
  const token = ++homeToken;
  const c = $('#content');
  const cached = homeCache[site.key];
  // 缓存 5 分钟内直接秒开，后台静默刷新
  if (cached && Date.now() - cached.at < 5 * 60 * 1000) {
    buildBanner(site, cached.items.slice(0, 8));
    bindCatBar(site, cats, cached.items, cached.first);
    renderTVRows(site, cached.items, cached.first);
    refreshHomeInBackground(site, cats, token);
    return;
  }
  // 骨架屏：立刻给出视觉反馈，不让用户盯空白
  $('#tvRows').innerHTML = '<div class="tv-row"><div class="row-head"><span class="bar"></span><h3>最近更新</h3></div>' +
    '<div class="hscroll"><div class="skel-grid">' +
    Array.from({ length: 8 }, () => '<div class="skel-card"><div class="skel-img"></div><div class="skel-line"></div></div>').join('') +
    '</div></div></div>';
  $('#catBar').innerHTML = '<div class="cat-pill on">🔥全部</div>' +
    Array.from({ length: 7 }, () => '<div class="cat-pill skel-pill"></div>').join('');

  const base = apiBase(site);
  // 第一步：只等视频列表，先把海报行渲染出来（用户马上能看到内容）
  const listRes = await Promise.race([
    cmsGet(join(base, { ac: 'videolist', pg: 1 }), 12000).then((d) => ({ ok: true, d })).catch((e) => ({ ok: false, e })),
    new Promise((r) => setTimeout(() => r({ ok: false, slow: true }), 8000)),
  ]);

  // 第二步：分类并发拉取。实测部分站点 ac=list 会挂起到 12s+，
  // 因此给分类单独设较短超时，失败也不影响首页内容展示。
  const catPromise = cmsGet(join(base, { ac: 'list' }), 7000)
    .then((d) => d).catch(() => null);

  if (token !== homeToken) return;   // 用户已切换站点，丢弃本次结果

  const first = { list: [] };
  if (listRes && listRes.ok) {
    first.list = listRes.d.list || [];
    first.total = listRes.d.total;
  }
  const items = first.list || [];
  if (!items.length && listRes && !listRes.ok && !listRes.slow) {
    // 站点故障：给出可操作提示，并提供"自动换一个可用站点"
    $('#tvRows').innerHTML = '<div class="empty">「' + esc(site.name) + '」加载失败：' +
      esc(listRes.e && listRes.e.message || '网络异常') +
      '<br><span class="muted">该站点可能暂时不可用，可点击下方按钮自动切换到可用站点</span>' +
      '<br><button id="btnAutoSite" class="mini-btn" style="margin-top:12px">🔄 自动切换可用站点</button></div>';
    $('#catBar').innerHTML = '';
    const ab = $('#btnAutoSite');
    if (ab) ab.onclick = () => autoPickSite();
    return;
  }
  homeCache[site.key] = { items, first, at: Date.now() };
  buildBanner(site, items.slice(0, 8));
  renderTVRows(site, items, first);
  // 分类栏先给占位，拿到后填充
  $('#catBar').innerHTML = '<div class="cat-pill on">🔥全部</div>' +
    Array.from({ length: 7 }, () => '<div class="cat-pill skel-pill"></div>').join('');

  const catRes = await catPromise;
  if (token !== homeToken) return;
  let cats2 = [];
  if (catRes) {
    const arr = catRes.class || catRes.type || [];
    (Array.isArray(arr) ? arr : Object.values(arr)).forEach((x) => {
      if (x && x.type_name != null && x.type_id != null) {
        cats2.push({ id: x.type_id, name: String(x.type_name), pid: x.type_pid != null ? x.type_pid : 0 });
      }
    });
  }
  // 分类是核心功能，首轮失败再补一次（部分站点首包会挂起）
  if (!cats2.length) {
    try {
      const retry = await cmsGet(join(base, { ac: 'list' }), 8000);
      const arr = retry.class || retry.type || [];
      (Array.isArray(arr) ? arr : Object.values(arr)).forEach((x) => {
        if (x && x.type_name != null && x.type_id != null) {
          cats2.push({ id: x.type_id, name: String(x.type_name), pid: x.type_pid != null ? x.type_pid : 0 });
        }
      });
    } catch (e) {}
  }
  // 兜底：从视频列表里的 type_name/type_id 反推
  if (!cats2.length && items.length) {
    const seen = {};
    items.forEach((v) => {
      if (v && v.type_name != null && v.type_id != null && !seen[v.type_name]) {
        seen[v.type_name] = 1;
        cats2.push({ id: v.type_id, name: String(v.type_name), pid: v.type_id_1 != null ? v.type_id_1 : 0 });
      }
    });
  }
  state.catList[site.key] = cats2;
  const map = {};
  cats2.forEach((x) => { map[x.name] = x.id; });
  state.typeMap[site.key] = map;
  bindCatBar(site, cats, items, first);
}

// 后台静默刷新缓存，不打断当前界面
async function refreshHomeInBackground(site, cats, token) {
  try {
    const base = apiBase(site);
    const d = await cmsGet(join(base, { ac: 'videolist', pg: 1 }), 14000);
    if (token !== homeToken) return;
    const items = d.list || [];
    if (items.length) homeCache[site.key] = { items, first: d, at: Date.now() };
  } catch (e) {}
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

async function bindCatBar(site, cats, items, first) {
  const bar = $('#catBar'); if (!bar) return;
  // 分类已在 loadHomeData 中并发取回，直接用；避免二次请求造成等待
  const real = state.catList[site.key] || [];
  const ordered = [];
  (cats || []).forEach((n) => {
    const tid = resolveTid(site, n);
    if (tid != null && !ordered.some((x) => String(x.id) === String(tid))) {
      const rc = real.find((c) => String(c.id) === String(tid));
      ordered.push({ id: tid, name: rc ? rc.name : n });
    }
  });
  real.forEach((c) => {
    if (!ordered.some((x) => String(x.id) === String(c.id))) ordered.push({ id: c.id, name: c.name });
  });
  const pills = [{ name: '🔥全部', id: null }].concat(ordered);
  bar.innerHTML = pills.map((p, i) => '<div class="cat-pill' + (i === 0 ? ' on' : '') + '" data-cat="' + esc(p.name) + '" data-tid="' + esc(p.id || '') + '">' + esc(p.name) + '</div>').join('') ||
    '<div class="muted" style="padding:10px">该站未返回可展示分类，可用顶部搜索找片</div>';
  $$('.cat-pill', bar).forEach((el) => el.onclick = async () => {
    $$('.cat-pill', bar).forEach((x) => x.classList.remove('on'));
    el.classList.add('on');
    const cat = el.dataset.cat;
    if (!cat) { renderTVRows(site, items, first); return; }
    const box = $('#tvRows');
    box.innerHTML = '<div class="tv-row"><div class="row-head"><span class="bar"></span><h3>' + esc(cat) + '</h3>' +
      '<span class="more" id="catMore">更多 ›</span></div><div class="hscroll"><div class="empty"><span class="spinner"></span>加载中…</div></div></div>';
    const tid = el.dataset.tid || resolveTid(site, cat);
    if (!tid) {
      $('.hscroll', box).innerHTML = '<div class="empty">分类「' + esc(cat) + '」在当前站点无对应 type_id，请换其它分类或使用搜索。</div>';
      return;
    }
    try {
      const list = await fetchCategoryList(site, tid);
      $('.hscroll', box).innerHTML = list.length ? list.map(posterHTML).join('') : '<div class="empty">该分类暂无数据</div>';
      bindPosters($('.hscroll', box), site);
      $('#catMore').onclick = () => openCategory(cat, tid);
    } catch (e) { $('.hscroll', box).innerHTML = '<div class="empty">加载失败：' + esc(e.message) + '</div>'; }
  });
}

// 取分类资源：父类(type_pid=0且有子类)本身常无数据，聚合其子类；否则直接取该 type_id
async function fetchCategoryList(site, tid, pg) {
  pg = pg || 1;
  const d = await cmsGet(join(apiBase(site), { ac: 'videolist', t: tid, pg }), 20000);
  let list = d.list || [];
  if (list.length) return list;
  const children = (state.catList[site.key] || []).filter((c) => String(c.pid) === String(tid));
  if (children.length) {
    const parts = await Promise.all(children.slice(0, 20).map((c) =>
      cmsGet(join(apiBase(site), { ac: 'videolist', t: c.id, pg: 1 }), 15000).then((x) => x.list || []).catch(() => [])
    ));
    list = parts.reduce((a, b) => a.concat(b), []);
  }
  return list;
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

async function openCategory(name, tidHint) {
  const s = state.site;
  const c = $('#content');
  const isAll = (name === '__all__');
  const title = isAll ? '全部资源' : name;
  c.innerHTML = '<div class="crumb">‹ 返回 ' + esc(s.name) + '</div>' +
    '<div class="section-title">' + esc(title) + ' <small><span class="spinner"></span>加载中…</small></div><div id="catList" class="poster-grid"></div><div id="catPager" class="pager"></div>';
  $('.crumb').onclick = renderHome;
  if (isAll) { await loadCategoryPage(s, undefined, title, 1); return; }
  let tid = tidHint || resolveTid(s, name);
  if (!tid) {
    $('#catList').innerHTML = '<div class="empty">无法解析分类「' + esc(name) + '」的 type_id。<br>该分类在当前站点不存在或接口暂不可用。<br>可尝试顶部搜索框找片。</div>';
    return;
  }
  await loadCategoryPage(s, tid, name, 1);
}

async function loadCategoryPage(site, tid, name, pg) {
  const listBox = $('#catList'); const pager = $('#catPager');
  if (!listBox) return;
  listBox.innerHTML = '<div class="empty"><span class="spinner"></span>加载中…</div>';
  try {
    if (tid == null) {
      // 全部：直接 videolist
      const d = await cmsGet(join(apiBase(site), { ac: 'videolist', pg }), 20000);
      const list = d.list || [];
      listBox.innerHTML = list.map(posterHTML).join('') || '<div class="empty">暂无数据</div>';
      bindPosters(listBox, site);
      const total = Number(d.pagecount || 1) || 1;
      pager.innerHTML = '<button id="prevPage"' + (pg <= 1 ? ' disabled' : '') + '>‹ 上一页</button>' +
        '<span class="page-info">第 ' + pg + ' / ' + total + ' 页 · 共 ' + (d.total || 0) + ' 部</span>' +
        '<button id="nextPage"' + (pg >= total ? ' disabled' : '') + '>下一页 ›</button>';
      const pv = $('#prevPage'), nv = $('#nextPage');
      if (pv) pv.onclick = () => loadCategoryPage(site, tid, name, pg - 1);
      if (nv) nv.onclick = () => loadCategoryPage(site, tid, name, pg + 1);
      return;
    }
    const list = await fetchCategoryList(site, tid, pg);
    listBox.innerHTML = list.length ? list.map(posterHTML).join('') : '<div class="empty">该分类暂无数据</div>';
    bindPosters(listBox, site);
    const children = (state.catList[site.key] || []).filter((c) => String(c.pid) === String(tid));
    pager.innerHTML = '<div class="muted">分类ID ' + tid + (children.length ? '（父类，已聚合 ' + children.length + ' 个子类）' : '') + ' · 本页 ' + list.length + ' 部</div>';
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
let liveState = {
  channels: [],     // 全部频道(已按名称去重、合并线路)
  cats: [],         // [{source,name,channelIds:[]}]
  current: null,    // 当前频道对象
  lineIdx: 0,
  timeoutSec: +loadLS('ms_live_timeout', 8),
  decoder: loadLS('ms_live_decoder', 'hardware'),   // hardware | software | auto
  player: loadLS('ms_live_player', 'builtin'),      // builtin | mpv | vlc | potplayer
  players: {},      // 检测到的外部播放器路径
  hls: null,
  timer: null,
  playing: false,
  collapsed: loadLS('ms_live_collapsed', {}),
  filter: '',
};
function saveLiveSettings() {
  saveLS('ms_live_timeout', liveState.timeoutSec);
  saveLS('ms_live_decoder', liveState.decoder);
  saveLS('ms_live_player', liveState.player);
  saveLS('ms_live_collapsed', liveState.collapsed);
}

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
  const groups = [{ name: '赛事轮播', items: [] }]; let pending = null; let gname = null;
  text.split(/\r?\n/).forEach((line) => {
    line = line.trim();
    if (/^#EXTGRP:/i.test(line)) { gname = line.replace(/^#EXTGRP:/i, '').trim(); return; }
    if (/^#EXTINF:/i.test(line)) { pending = line.replace(/^#EXTINF:[^,]*,/i, '').trim(); return; }
    if (line && !/^#/.test(line) && /^https?:\/\//i.test(line)) {
      const g = groups[0];
      g.items.push({ name: (gname ? gname + '·' : '') + (pending || ('频道' + (g.items.length + 1))), urls: [line] });
      pending = null; gname = null;
    }
  });
  return groups.filter((g) => g.items.length);
}
function normChannel(name) {
  return String(name || '').toUpperCase().replace(/[\s\-_—]/g, '')
    .replace(/(高清|超清|蓝光|HD|4K|1080P|720P)$/i, '').trim();
}

// 构建频道目录：同名频道只保留一个名字，多个源/分组的 URL 合并为“线路”
function buildLiveCatalog() {
  const byName = new Map();
  const cats = [];
  Object.keys(liveCache || {}).forEach((src) => {
    (liveCache[src] || []).forEach((g) => {
      const cat = { source: src, name: g.name, channelIds: [], id: src + '|' + g.name };
      g.items.forEach((it) => {
        const key = normChannel(it.name);
        if (!key) return;
        let ch = byName.get(key);
        if (!ch) {
          ch = { id: 'ch' + byName.size, name: it.name, key, urls: [] };
          byName.set(key, ch);
        }
        it.urls.forEach((u) => { if (ch.urls.indexOf(u) < 0) ch.urls.push(u); });
        if (cat.channelIds.indexOf(ch.id) < 0) cat.channelIds.push(ch.id);
      });
      if (cat.channelIds.length) cats.push(cat);
    });
  });
  liveState.channels = Array.from(byName.values());
  liveState.cats = cats;
}

async function ensureLiveData() {
  if (liveCache) return;
  const pending = {};
  // 本地源文件（已内置验证过的可播线路）
  for (const name of ['TVLives.txt', 'PlatformLive.txt', 'BiliLive.txt']) {
    try {
      const txt = await MS.readConfig(name);
      const g = parseTVLines(txt);
      pending[name] = g;
      if (!g.length) console.warn('[live] ' + name + ' 解析出 0 个分组，原始长度=' + (txt || '').length);
    } catch (e) {
      console.warn('[live] 读取 ' + name + ' 失败: ' + (e && e.message || e));
      pending[name] = [];
    }
  }
  // 远程赛事/平台轮播 m3u（并发拉取，单个失败不阻塞；总时限 12s）
  const m3us = [
    { name: '⚽赛事直播·虎牙', url: 'https://peterhchina.github.io/iptv/huyayqk.m3u' },
    { name: '🏀赛事直播·斗鱼', url: 'https://peterhchina.github.io/iptv/douyuyqk.m3u' },
    { name: '🎮平台轮播·歪歪', url: 'https://peterhchina.github.io/iptv/yylunbo.m3u' },
    { name: '📺直播大合集', url: 'https://peterhchina.github.io/iptv/Live.m3u' },
  ];
  await Promise.all(m3us.map(async (m) => {
    try {
      const r = await MS.httpGet(m.url, { 'User-Agent': 'okHttp/Mursor-1.4.0.0' }, 12000);
      if (r && r.body && r.body.indexOf('#EXTM3U') >= 0) {
        const g = parseM3U(r.body);
        if (g.length) pending[m.name] = g;
      }
    } catch (e) {}
  }));
  try { liveState.players = await MS.detectPlayers(); } catch (e) { liveState.players = {}; }
  // 全部成功后再赋值：保证下次进入直播页还能重试
  liveCache = pending;
  buildLiveCatalog();
}

// 线路健康探测：并发抽测每条线路，标记可用/失效，播放时优先走可用线路
async function probeLiveLines() {
  const all = [];
  liveState.channels.forEach((ch) => ch.urls.forEach((u) => all.push({ ch, u })));
  if (!all.length) return;
  liveState.probing = true;
  const CONC = 8;
  let idx = 0;
  const worker = async () => {
    while (idx < all.length) {
      const item = all[idx++];
      let ok = false;
      try {
        const r = await MS.probeStream(item.u);
        ok = !!(r && r.ok && !r.is404 && !r.isHtml);
      } catch (e) { ok = false; }
      item.ch.good = item.ch.good || {};
      item.ch.good[item.u] = ok;
    }
  };
  await Promise.all(Array.from({ length: CONC }, worker));
  liveState.probing = false;
  renderLiveTree();
}

function renderLive() {
  const c = $('#content');
  c.innerHTML =
    '<div class="live-wrap">' +
      '<aside class="live-cats">' +
        '<div class="live-cats-head">📺 频道分类 <small id="liveChCount"></small></div>' +
        '<input id="liveFilter" class="live-filter" placeholder="搜索频道名…" autocomplete="off">' +
        '<div id="liveTree" class="live-tree"></div>' +
      '</aside>' +
      '<section class="live-main">' +
        '<div class="live-bar">' +
          '<div class="live-now" id="liveNow">选择一个频道开始观看</div>' +
          '<div class="live-settings">' +
            '<label>超时 <select id="setTimeout" class="mini-sel">' +
              [4, 6, 8, 10, 15, 20].map((n) => '<option value="' + n + '"' + (n === liveState.timeoutSec ? ' selected' : '') + '>' + n + 's</option>').join('') +
            '</select></label>' +
            '<label>解码 <select id="setDecoder" class="mini-sel">' +
              '<option value="hardware"' + (liveState.decoder === 'hardware' ? ' selected' : '') + '>硬件优先</option>' +
              '<option value="software"' + (liveState.decoder === 'software' ? ' selected' : '') + '>软件兼容</option>' +
              '<option value="auto"' + (liveState.decoder === 'auto' ? ' selected' : '') + '>自动</option>' +
            '</select></label>' +
            '<label>播放器 <select id="setPlayer" class="mini-sel">' +
              '<option value="builtin"' + (liveState.player === 'builtin' ? ' selected' : '') + '>内置</option>' +
              (liveState.players.mpv ? '<option value="mpv"' + (liveState.player === 'mpv' ? ' selected' : '') + '>mpv(轻快)</option>' : '') +
              (liveState.players.vlc ? '<option value="vlc"' + (liveState.player === 'vlc' ? ' selected' : '') + '>VLC</option>' : '') +
              (liveState.players.potplayer ? '<option value="potplayer"' + (liveState.player === 'potplayer' ? ' selected' : '') + '>PotPlayer</option>' : '') +
            '</select></label>' +
            '<button id="btnProbe" class="mini-btn" title="并发探测每条线路是否可播">🔍 检测线路</button>' +
          '</div>' +
        '</div>' +
        '<div class="live-screen" id="liveScreen">' +
          '<video id="liveVideo" playsinline></video>' +
          '<div class="live-msg hidden" id="liveMsg"></div>' +
          '<div class="live-lines" id="liveLines"></div>' +
          '<div class="live-center-play" id="liveCenterPlay">▶</div>' +
        '</div>' +
        '<div class="live-hint" id="liveHint">同名频道只显示一次，所有线路在画面左下角切换；超时自动跳下一条线路。</div>' +
      '</section>' +
    '</div>';
  $('#liveChCount').textContent = '(' + liveState.channels.length + ')';
  renderLiveTree();

  $('#liveFilter').addEventListener('input', (e) => { liveState.filter = e.target.value.trim(); renderLiveTree(); });
  $('#setTimeout').onchange = (e) => { liveState.timeoutSec = +e.target.value; saveLiveSettings(); toast('换线超时设为 ' + liveState.timeoutSec + ' 秒'); };
  $('#setDecoder').onchange = (e) => { liveState.decoder = e.target.value; saveLiveSettings(); toast('解码方式：' + e.target.selectedOptions[0].text); if (liveState.current) livePlay(liveState.lineIdx); };
  $('#setPlayer').onchange = (e) => { liveState.player = e.target.value; saveLiveSettings(); toast('播放器：' + e.target.selectedOptions[0].text); if (liveState.current) livePlay(liveState.lineIdx); };
  const bp = $('#btnProbe');
  if (bp) bp.onclick = async () => {
    if (liveState.probing) return;
    bp.disabled = true; bp.textContent = '检测中…';
    await probeLiveLines();
    bp.disabled = false; bp.textContent = '🔍 检测线路';
    const total = liveState.channels.reduce((a, c) => a + c.urls.length, 0);
    let ok = 0;
    liveState.channels.forEach((c) => c.urls.forEach((u) => { if (c.good && c.good[u]) ok++; }));
    toast('检测完成：' + ok + '/' + total + ' 条线路可播');
  };
  $('#liveCenterPlay').onclick = () => { const v = $('#liveVideo'); if (v && v.src) { v.play().catch(() => {}); $('#liveCenterPlay').classList.add('hidden'); } };

  (async () => {
    const box = $('#liveTree');
    // 注意：不能用「box.children.length」判断是否已加载 —— renderLiveTree() 早已写入
    // 「无匹配频道」占位符，会让该条件恒为 false，导致 ensureLiveData() 永远不执行
    // （表现为直播列表匹配不到任何资源）。这里改用 liveCache 是否已初始化来判断。
    if (box && !liveCache) {
      box.innerHTML = '<div class="empty"><span class="spinner"></span>加载直播列表…</div>';
      await ensureLiveData();
      $('#liveChCount').textContent = '(' + liveState.channels.length + ')';
      renderLiveTree();
    }
  })();
}

function renderLiveTree() {
  const box = $('#liveTree'); if (!box) return;
  const kw = normChannel(liveState.filter);
  const matches = (ch) => !kw || normChannel(ch.name).indexOf(kw) >= 0;
  let html = '';
  liveState.cats.forEach((cat, ci) => {
    const ids = cat.channelIds.filter((id) => matches(liveState.channels.find((x) => x.id === id)));
    if (!ids.length) return;
    const collapsed = !!liveState.collapsed[cat.id];
    html += '<div class="live-cat"><div class="live-cat-head" data-cat="' + esc(cat.id) + '">' +
      '<span class="caret">' + (collapsed ? '▸' : '▾') + '</span>' + esc(cat.name) +
      '<small>(' + ids.length + ')</small></div>';
    if (!collapsed) {
      html += '<div class="live-ch-list">';
      ids.forEach((id) => {
        const ch = liveState.channels.find((x) => x.id === id);
        if (!ch) return;
        const active = liveState.current && liveState.current.id === ch.id;
        // 探测后显示可用线路数
        let badge = ch.urls.length + '路';
        if (ch.good) {
          const okN = ch.urls.filter((u) => ch.good[u]).length;
          badge = okN + '/' + ch.urls.length + '路';
        }
        const dead = ch.good && ch.urls.every((u) => !ch.good[u]);
        html += '<div class="live-ch' + (active ? ' active' : '') + (dead ? ' dead' : '') + '" data-id="' + ch.id + '" title="' + esc(ch.urls[0] || '') + '">' +
          esc(ch.name) + '<small>' + badge + '</small></div>';
      });
      html += '</div>';
    }
    html += '</div>';
  });
  box.innerHTML = html || '<div class="empty">无匹配频道</div>';
  $$('.live-cat-head', box).forEach((el) => el.onclick = () => {
    const id = el.dataset.cat;
    liveState.collapsed[id] = !liveState.collapsed[id];
    saveLiveSettings(); renderLiveTree();
  });
  $$('.live-ch', box).forEach((el) => el.onclick = () => {
    const ch = liveState.channels.find((x) => x.id === el.dataset.id);
    if (!ch) return;
    liveStop();
    // 已探测过：优先挑第一条可用线路
    let idx = 0;
    if (ch.good) {
      const goodIdx = ch.urls.findIndex((u) => ch.good[u]);
      if (goodIdx >= 0) idx = goodIdx;
    }
    livePlayChannel(ch, idx);
    renderLiveTree();
  });
}

function livePlay(lineIdx) {
  if (liveState.current) livePlayChannel(liveState.current, lineIdx);
}
function liveStop() {
  clearTimeout(liveState.timer); liveState.timer = null;
  const v = $('#liveVideo');
  if (v) { try { v.pause(); v.removeAttribute('src'); v.load(); } catch (e) {} }
  if (liveState.hls) { try { liveState.hls.destroy(); } catch (e) {} liveState.hls = null; }
  liveState.playing = false;
  const msg = $('#liveMsg'); if (msg) msg.classList.add('hidden');
  const cp = $('#liveCenterPlay'); if (cp) cp.classList.add('hidden');
}
function liveShowMsg(text) {
  const msg = $('#liveMsg'); if (!msg) return;
  msg.textContent = text; msg.classList.remove('hidden');
}
function livePlayChannel(ch, lineIdx) {
  liveStop();
  liveState.current = ch;
  liveState.lineIdx = lineIdx;
  const now = $('#liveNow'); if (now) now.textContent = ch.name;
  const linesBox = $('#liveLines');
  if (linesBox) {
    linesBox.innerHTML = ch.urls.map((u, i) =>
      '<div class="live-line' + (i === lineIdx ? ' active' : '') + (ch.good && ch.good[u] === false ? ' bad' : '') +
      '" data-i="' + i + '" title="' + esc(u) + '">' + '线路' + (i + 1) + (ch.good && ch.good[u] === false ? ' ✕' : '') + '</div>').join('');
    $$('.live-line', linesBox).forEach((el) => el.onclick = (e) => { e.stopPropagation(); livePlayChannel(ch, +el.dataset.i); });
  }
  const rawUrl = ch.urls[lineIdx];
  if (!rawUrl) { liveShowMsg('该频道无可用线路'); return; }
  // 外部轻量播放器：交给 mpv/VLC/PotPlayer 硬件解码（直连原地址，不经代理）
  if (liveState.player !== 'builtin') {
    MS.playExternal(liveState.player, rawUrl, liveState.decoder).then((r) => {
      if (r && r.error) liveShowMsg('调用失败：' + r.error + '（可切回内置播放器）');
      else liveShowMsg('已在 ' + liveState.player + ' 中打开（硬解优先）');
    });
    return;
  }
  // 内置播放器：经主进程代理取流，绕过 IPTV 源普遍缺失的 CORS 头
  const v = $('#liveVideo'); if (!v) return;
  const isHls = /\.m3u8?(\?|$)/i.test(rawUrl);
  const armWatchdog = () => {
    clearTimeout(liveState.timer);
    liveState.timer = setTimeout(() => {
      if (!liveState.playing && ch.urls.length > 1) {
        liveShowMsg('线路' + (lineIdx + 1) + ' 超时，自动切换下一条…');
        livePlayChannel(ch, (lineIdx + 1) % ch.urls.length);
      }
    }, liveState.timeoutSec * 1000);
  };
  liveState.playing = false;
  v.onplaying = () => { liveState.playing = true; clearTimeout(liveState.timer); const cp = $('#liveCenterPlay'); if (cp) cp.classList.add('hidden'); };
  v.onerror = () => { if (ch.urls.length > 1) { liveShowMsg('线路' + (lineIdx + 1) + ' 出错，切换下一条…'); livePlayChannel(ch, (lineIdx + 1) % ch.urls.length); } };
  MS.proxyUrl(rawUrl).then((url) => {
    if (window.Hls && window.Hls.isSupported() && isHls) {
      const hls = new window.Hls({
        enableWorker: liveState.decoder !== 'software',
        lowLatencyMode: true,
        backBufferLength: 20,
        maxBufferLength: 12,
        maxMaxBufferLength: 30,
        manifestLoadingMaxRetry: 1,
        levelLoadingMaxRetry: 2,
        fragLoadingMaxRetry: 2,
        // 关键：把 hls.js 内部的清单/分片请求也改写到本地代理，
        // 否则 m3u8 里的分片相对路径仍会直连远端并被 CORS 拦截
        xhrSetup: function (xhr, u) {
          try { xhr.open('GET', MS.localProxy(u), true); } catch (e) {}
        },
      });
      hls.loadSource(url); hls.attachMedia(v);
      hls.on(window.Hls.Events.ERROR, (_e, data) => {
        if (data && data.fatal && ch.urls.length > 1) {
          liveShowMsg('线路' + (lineIdx + 1) + ' 播放失败，切换下一条…');
          livePlayChannel(ch, (lineIdx + 1) % ch.urls.length);
        }
      });
      liveState.hls = hls;
      v.play().catch(() => {});
    } else {
      // 非 m3u8（flv / 无扩展名流 / mp4）：先按原生方式尝试，
      // flv 在 Chromium 不支持，失败后交给外部播放器（mpv/VLC）处理
      v.src = url; v.play().catch(() => {
        liveShowMsg('该线路为 FLV 等格式，浏览器无法直接播放，请把「播放器」切换为 mpv/VLC');
      });
    }
  }).catch(() => {
    v.src = rawUrl; v.play().catch(() => {});
  });
  armWatchdog();
  const cp = $('#liveCenterPlay'); if (cp) cp.classList.remove('hidden');
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
$('#btnReload').onclick = async () => {
  state.typeMap = {}; state.catList = {}; state._catTid = {}; homeCache = {};
  await loadConfig();
  liveCache = null; liveState.channels = []; liveState.cats = []; liveState.current = null;
  if (state.view === 'live') renderLive();
  toast('配置与分类已重新加载');
};
const bas = $('#btnAutoSite');
if (bas) bas.onclick = async () => {
  bas.disabled = true; bas.textContent = '检测中…';
  try {
    await autoPickSite();
  } finally {
    bas.disabled = false; bas.textContent = '⚡ 自动选站';
  }
};
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

// 自动化自检钩子：供主进程 executeJavaScript 调用（仅自检模式使用）
window.__msSelfTest = {
  state: state,
  liveState: liveState,
  getLiveCache: () => liveCache,
  renderSites: renderSites,
  renderHome: renderHome,
  setView: setView,
  isCMS: isCMS,
  apiBase: apiBase,
  join: join,
  probeAllSites: probeAllSites,
  autoPickSite: autoPickSite,
};
