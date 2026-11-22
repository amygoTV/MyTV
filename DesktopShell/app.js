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
  bootReady: false,   // 启动测速完成标记
  typeMap: {},       // siteKey -> {name:id}
  catList: {},       // siteKey -> [{id,name,pid}] 站点真实分类(来自 ac=list 的 class 字段)
  favorites: loadLS('ms_favorites', []),
  history: loadLS('ms_history', []),
  playerHls: null,
  currentPlay: null, // {title, episodes, srcIdx}
  settings: {},      // 用户设置（主题/弹幕等），由主进程持久化
  shellMode: true,   // 空壳模式：还没导入任何影视接口
};

function loadLS(k, def) { try { return JSON.parse(localStorage.getItem(k)) || def; } catch (e) { return def; } }
function saveLS(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.classList.remove('hidden');
  clearTimeout(t._t); t._t = setTimeout(() => t.classList.add('hidden'), 2200);
}
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function isCMS(site) { return /^https?:\/\//i.test(String(site.api || '')); }

// ---------- 设置（主题 / 弹幕）----------
function applyTheme(theme) {
  const t = theme === 'light' ? 'light' : 'dark';
  document.body.classList.toggle('light', t === 'light');
  document.body.classList.toggle('dark', t !== 'light');
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', t === 'light' ? '#f4f6fa' : '#0d0f14');
}
async function saveSettings(patch) {
  try { state.settings = await MS.saveSettings(patch) || Object.assign({}, state.settings, patch); }
  catch (e) { state.settings = Object.assign({}, state.settings, patch); }
  return state.settings;
}

// ---------- config load ----------
async function loadConfig() {
  // 订阅来自用户存储（导入一次即持久化，重开自动加载）；不再读应用内置资源
  let cfg = null;
  try { cfg = await MS.getSubscription(); } catch (e) { cfg = null; }
  if (!cfg || !Array.isArray(cfg.sites) || !cfg.sites.length) {
    state.shellMode = true;
    state.config = null;
    state.sites = [];
    state.site = null;
    renderShell();
    return;
  }
  state.shellMode = false;
  state.config = cfg;
  state.sites = cfg.sites || [];
  if (!state.site) {
    // 记住上次成功使用的站；若它已失效则回退到第一个 CMS 站
    const last = state.settings.lastSite || loadLS('ms_last_site', '');
    const byKey = state.sites.find((s) => s.key === last);
    state.site = (byKey && isCMS(byKey)) ? byKey : (state.sites.find(isCMS) || state.sites[0]);
  }
  renderSites();
  $('#siteCount').textContent = '(' + state.sites.length + ')';
  if (state.view === 'home') renderHome();
}

// 空壳引导页：首次启动没有任何影视资源，引导用户导入订阅
function renderShell() {
  $('#siteCount').textContent = '(0)';
  $('#siteList').innerHTML = '<div class="empty" style="font-size:12px;padding:10px 6px;">尚未导入影视接口</div>';
  const c = $('#content');
  c.innerHTML =
    '<div class="shell-hero">' +
      '<div class="sh-logo">▶</div>' +
      '<h2>欢迎使用影视舱 MediaShell</h2>' +
      '<p>本应用不内置任何影视资源。<br>请先导入影视仓 / TVBox 的 JSON 接口配置，之后本机会自动保存，下次打开直接使用。</p>' +
      '<div class="shell-steps">' +
        '<div><span class="num">1</span>准备一个 <b>影视仓 / TVBox 配置地址</b>（JSON 格式，含 sites 字段）</div>' +
        '<div><span class="num">2</span>点击下方 <b>导入订阅</b> 粘贴该地址</div>' +
        '<div><span class="num">3</span>导入成功后 <b>分类与资源自动适配</b> 该接口提供的站点</div>' +
      '</div>' +
      '<div class="shell-actions">' +
        '<button id="btnShellImport" class="primary-btn">＋ 导入订阅</button>' +
        '<button id="btnShellBackup" class="ghost-btn">⬆ 导入配置备份</button>' +
      '</div>' +
    '</div>';
  const bi = $('#btnShellImport'); if (bi) bi.onclick = () => $('#importDialog').classList.remove('hidden');
  const bb = $('#btnShellBackup'); if (bb) bb.onclick = importBackupFile;
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
    const d = await cmsGet(join(apiBase(site), { ac: 'list' }), 6000);
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
      const d = await cmsGet(join(apiBase(site), { ac: 'videolist', pg: 1 }), 6000);
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
  if (state.shellMode && v !== 'home') {
    $('#content').innerHTML = '<div class="empty">尚未导入影视接口。<br>请点击左下角「导入订阅」后即可使用' +
      esc({ search: '搜索', live: '直播', favorite: '收藏', history: '历史' }[v] || '该功能') + '。</div>';
    return;
  }
  if (v === 'home') renderHome();
  else if (v === 'search') renderSearch();
  else if (v === 'live') renderLive();
  else if (v === 'favorite') renderStore('favorite');
  else if (v === 'history') renderStore('history');
}

// 并发探测所有 CMS 站点，返回按响应速度排序的可用站点列表
// 整体加 8 秒上限：个别站挂起时不能拖住整个测速（主进程重试会让单次最长 15s）
async function probeAllSites(excludeKey) {
  const cands = state.sites.filter((s) => isCMS(s) && (!excludeKey || s.key !== excludeKey));
  const out = [];
  await Promise.race([
    Promise.all(cands.map(async (s) => {
      const t0 = Date.now();
      try {
        const d = await cmsGet(join(apiBase(s), { ac: 'videolist', pg: 1 }), 5000);
        if (d && (d.list || []).length) out.push({ site: s, ms: Date.now() - t0, n: (d.list || []).length });
      } catch (e) {}
    })),
    new Promise((r) => setTimeout(r, 8000)),
  ]);
  out.sort((a, b) => a.ms - b.ms);
  return out;
}

// 找一个健康的备用站（当前站失效时用）
async function findHealthySite(currentSite) {
  try {
    const list = await probeAllSites(currentSite && currentSite.key);
    return list[0] || null;
  } catch (e) { return null; }
}

// 多站竞速：选出参与竞速的站点（当前站优先，再按配置顺序补 2 个）
const RACE_MAX = 3;
function pickRacers(currentSite) {
  const list = [];
  if (currentSite && isCMS(currentSite)) list.push(currentSite);
  for (const s of state.sites) {
    if (list.length >= RACE_MAX) break;
    if (!isCMS(s)) continue;
    if (list.some((x) => x.key === s.key)) continue;
    list.push(s);
  }
  return list;
}

// 竞速：返回第一个「成功且有数据」的结果
// 注意：早期版本在 6s 就放弃并丢弃了已发出的请求，导致本来 7s 就能成功的站
// 被丢掉、进而走「降级→重新探测→重新加载」的冗长路径（实测 12s+）。
// 现在改为：超时时间与单站请求超时对齐（12s），期间任何站先回先用。
function raceFirst(entries, timeoutMs) {
  return new Promise((resolve) => {
    let settled = false;
    let pending = entries.length;
    let lastFail = null;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      resolve(lastFail || { ok: false, slow: true });
    }, timeoutMs);
    entries.forEach((e) => {
      e.p.then((r) => {
        if (settled) return;
        if (r && r.ok && r.d && (r.d.list || []).length) {
          settled = true;
          clearTimeout(timer);
          resolve(r);
          return;
        }
        lastFail = r || lastFail;
      }).catch(() => {});
    });
    // 全部失败时立即返回失败结果，不必等满 timeout
    const check = () => {
      if (settled) return;
      pending--;
      if (pending <= 0) {
        settled = true;
        clearTimeout(timer);
        resolve(lastFail || { ok: false, slow: true });
      }
    };
    entries.forEach((e) => e.p.then(check, check));
  });
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
  if (state.shellMode) { renderShell(); return; }
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
async function loadHomeData(siteParam, catsParam) {
  let site = siteParam;
  let cats = catsParam;
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

  let base = apiBase(site);
  // 第一步：只等视频列表，先把海报行渲染出来（用户马上能看到内容）
  // 采集站普遍不稳定（实测同一站 0.4s~14s 波动），因此并发请求 2~3 个候选站，
  // 谁先返回就用谁 —— 相当于「多站竞速」，避免被单个慢站拖住。
  const racers = pickRacers(site);          // [当前站, 备选站...]
  const listPromise = raceFirst(racers.map((s) => ({
    site: s,
    p: cmsGet(join(apiBase(s), { ac: 'videolist', pg: 1 }), 8000)
      .then((d) => ({ ok: true, d, site: s })).catch((e) => ({ ok: false, e, site: s })),
  // 硬超时必须 >= 单站请求的最坏耗时（cmsGet 10s + 主进程重试二次 5s = 15s），
// 否则会把「已经发出、只是慢」的站白白丢弃，再走一遍降级流程（实测 12s → 18s）。
})), 10000);
  const listRes = await listPromise;

  // 若最终用的是备选站，把当前站也切过去（保持界面与数据一致）
  if (listRes && listRes.ok && listRes.site && listRes.site.key !== site.key) {
    state.site = listRes.site;
    site = listRes.site;
    cats = site.categories || [];
    base = apiBase(site);
    renderSites();
    toast('「' + listRes.site.name + '」响应更快，已自动切换');
  }

  // 第二步：分类并发拉取。实测部分站点 ac=list 会挂起到 12s+，
  // 因此给分类单独设较短超时，失败也不影响首页内容展示。
  const catPromise = cmsGet(join(apiBase(site), { ac: 'list' }), 5000)
    .then((d) => d).catch(() => null);

  if (token !== homeToken) return;   // 用户已切换站点，丢弃本次结果

  const first = { list: [] };
  if (listRes && listRes.ok) {
    first.list = listRes.d.list || [];
    first.total = listRes.d.total;
  }
  const items = first.list || [];
  if (!items.length && listRes && !listRes.ok) {
    // 站点故障或响应过慢：先自动探测其它站点能否用，直接切到可用的
    $('#tvRows').innerHTML = '<div class="empty"><span class="spinner"></span>正在探测其它可用采集站…</div>';
    $('#catBar').innerHTML = '';
    const alt = await findHealthySite(site);
    if (alt && alt.site && alt.site.key !== site.key) {
      state.site = alt.site;
      renderSites();
      renderHome();
      toast('「' + site.name + '」不可用，已自动切换到 ' + alt.site.name + '（' + alt.ms + 'ms）');
      return;
    }
    // 所有站都不可用：给出可操作提示
    const slow = listRes.slow;
    $('#tvRows').innerHTML = '<div class="empty">' + (slow ? '「' + esc(site.name) + '」响应较慢，已等待 8 秒仍未返回内容'
      : '「' + esc(site.name) + '」加载失败：' + esc(listRes.e && listRes.e.message || '网络异常')) +
      '<br><span class="muted">当前所有采集站都暂时不可用，可稍后重试</span>' +
      '<br><button id="btnRetryHome" class="mini-btn" style="margin-top:12px;margin-right:8px">↻ 重试本站</button>' +
      '<button id="btnAutoSite" class="mini-btn" style="margin-top:12px">🔄 重新探测可用站点</button></div>';
    $('#catBar').innerHTML = '';
    const rb = $('#btnRetryHome');
    if (rb) rb.onclick = () => { delete homeCache[site.key]; renderHome(); };
    const ab = $('#btnAutoSite');
    if (ab) ab.onclick = () => autoPickSite();
    return;
  }
  homeCache[site.key] = { items, first, at: Date.now() };
  saveLS('ms_last_site', site.key);   // 记住成功加载的站，下次启动直接用
  if (state.settings) saveSettings({ lastSite: site.key });
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
      const retry = await cmsGet(join(base, { ac: 'list' }), 6000);
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
    const d = await cmsGet(join(base, { ac: 'videolist', pg: 1 }), 8000);
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
  // 横幅图同样可能超时，加失败降级
  $$('.bslide', box).forEach((el) => {
    const url = (el.style.backgroundImage || '').replace(/^url\(["']?/, '').replace(/["']?\)$/, '');
    if (!url) return;
    const probe = new Image();
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return; settled = true;
      el.classList.add('img-bad'); el.style.backgroundImage = '';
    }, 8000);
    probe.onload = () => { if (!settled) { settled = true; clearTimeout(timer); } };
    probe.onerror = () => { if (!settled) { settled = true; clearTimeout(timer); el.classList.add('img-bad'); el.style.backgroundImage = ''; } };
    probe.src = url;
  });
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
  // 分类自适应：以站点 ac=list 返回的真实分类（class 字段）为准。
  // 配置里写死的 categories 只作排序参考，绝不直接当分类名展示 —— 名字与站点
  // 的 type_name 不一致时会出现「点了没数据」的死标签。
  const real = state.catList[site.key] || [];
  if (!real.length) {
    bar.innerHTML = '<div class="muted" style="padding:10px">该站未返回可展示分类，可用顶部搜索找片</div>';
    return;
  }

  // 1) 父类（有子类的）在前，无子类的在后；同级保持站点返回顺序
  const hasChild = (c) => real.some((x) => String(x.pid) === String(c.id));
  const parents = real.filter((c) => hasChild(c));
  const leaves = real.filter((c) => !hasChild(c));
  // 2) 配置里声明的分类优先（按配置顺序），其余按站点顺序
  const prefer = (cats || []).map((n) => real.find((c) => c.name === n)).filter(Boolean);
  const ordered = [];
  const push = (c) => { if (c && !ordered.some((x) => String(x.id) === String(c.id))) ordered.push(c); };
  prefer.forEach(push);
  parents.forEach(push);
  leaves.forEach(push);

  // 常用分类：用户点名的几类 + 配置里声明的分类，保证「全部/电影/连续剧/综艺/动漫/短剧」都在
  const COMMON = ['全部', '电影', '连续剧', '电视剧', '综艺', '动漫', '短剧', '纪录片', '体育赛事'];
  const common = [];
  const pushC = (c) => { if (c && !common.some((x) => String(x.id) === String(c.id))) common.push(c); };
  COMMON.forEach((n) => {
    if (n === '全部') { pushC({ id: null, name: '全部' }); return; }
    // 优先精确匹配站点真实分类名；找不到就用归组表反查（父类名一致即可）
    const hit = real.find((c) => c.name === n);
    if (hit) pushC(hit);
  });
  prefer.forEach(pushC);
  // 再补齐其余真实分类（用户可展开查看）
  ordered.forEach((c) => pushC(c));

  const COMMON_MAX = 12;
  const shown = common.slice(0, COMMON_MAX);
  const rest = common.slice(COMMON_MAX);
  state.catExpanded = false;

  const pillHTML = (p, i) =>
    '<div class="cat-pill' + (p.name === '全部' ? ' on' : '') + '" data-cat="' + esc(p.name === '全部' ? '' : p.name) +
    '" data-tid="' + esc(p.id || '') + '"' + (p.name === '全部' ? ' data-all="1"' : '') + '>' +
    (p.name === '全部' ? '🔥' : '') + esc(p.name) + '</div>';

  bar.innerHTML = shown.map(pillHTML).join('') +
    (rest.length ? '<div class="cat-pill more" id="catMoreToggle">更多 ' + rest.length + ' 个 ⌄</div>' : '');
  if (rest.length) {
    $('#catMoreToggle', bar).onclick = () => {
      state.catExpanded = !state.catExpanded;
      if (state.catExpanded) {
        bar.innerHTML = common.map(pillHTML).join('') +
          '<div class="cat-pill more" id="catMoreToggle">收起 ⌃</div>';
      } else {
        bar.innerHTML = shown.map(pillHTML).join('') +
          '<div class="cat-pill more" id="catMoreToggle">更多 ' + rest.length + ' 个 ⌄</div>';
      }
      bindCatPills(site, cats, items, first);
    };
  }
  bindCatPills(site, cats, items, first);
}

// 绑定分类标签点击（展开/收起后需要重新绑定）
function bindCatPills(site, cats, items, first) {
  const bar = $('#catBar'); if (!bar) return;
  $$('.cat-pill', bar).forEach((el) => {
    if (el.classList.contains('more')) return;   // 「更多」只负责展开/收起
    el.onclick = async () => {
    $$('.cat-pill', bar).forEach((x) => x.classList.remove('on'));
    el.classList.add('on');
    const cat = el.dataset.cat;
    if (!cat) {
      // 「全部」：有首页数据就平铺展示；没有就直接进入完整的全部资源列表
      if (items && items.length) { renderTVRows(site, items, first); return; }
      openCategory('__all__');
      return;
    }
    const box = $('#tvRows');
    box.innerHTML = '<div class="tv-row"><div class="row-head"><span class="bar"></span><h3>' + esc(cat) + '</h3>' +
      '<span class="more" id="catMore">更多 ›</span></div><div class="hscroll"><div class="empty"><span class="spinner"></span>加载中…</div></div></div>';
    const tid = el.dataset.tid || resolveTid(site, cat);
    try {
      // 用按名聚合的方式取：父类自身无数据时自动展开子类（不影响原有精确匹配）
      const list = await fetchCategoryByName(site, cat, tid);
      if (!list.length && tid == null) {
        $('.hscroll', box).innerHTML = '<div class="empty">分类「' + esc(cat) + '」在当前站点无对应 type_id，请换其它分类或使用搜索。</div>';
        return;
      }
      $('.hscroll', box).innerHTML = list.length
        ? list.map(posterHTML).join('')
        : '<div class="empty">该分类暂无数据<br><span class="muted" style="font-size:12px">可试试其它站点或用搜索</span></div>';
      bindPosters($('.hscroll', box), site);
      $('#catMore').onclick = () => openCategory(cat, tid);
    } catch (e) { $('.hscroll', box).innerHTML = '<div class="empty">加载失败：' + esc(e.message) + '</div>'; }
    };
  });
}

// ---- 父类语义归组表 ----------------------------------------------------
// 苹果 CMS 站点的「电影/连续剧/综艺/动漫/短剧」是**父类**，用 t=<父类id> 查询
// 自身 total 恒为 0，真实内容全在子类里。要让这几个入口有资源，必须把父类
// 展开成一组语义相关的子类再聚合。
// 注意：这是**叠加**机制 —— 站点若真的给父类返回数据，仍优先用父类自己的数据。
const PARENT_GROUPS = [
  { parent: '连续剧', kids: ['国产剧', '大陆剧', '港澳剧', '香港剧', '台剧', '台湾剧', '日剧', '韩剧', '泰剧', '欧美剧', '欧美', '古装仙侠', '仙侠', '现代都市', '都市', '穿越年代', '穿越', '言情总裁', '重生民国', '反转爽剧', '脑洞悬疑', '悬疑', '战争', '军旅', '职场', '校园', '剧情', '连续剧'] },
  { parent: '电影', kids: ['动作片', '喜剧片', '爱情片', '科幻片', '科幻', '恐怖片', '剧情片', '战争片', '纪录片', '伦理片', '犯罪片', '悬疑片', '动画片', '国语片', '粤语片', '电影'] },
  { parent: '综艺', kids: ['大陆综艺', '日韩综艺', '港台综艺', '欧美综艺', '综艺'] },
  { parent: '动漫', kids: ['中国动漫', '日本动漫', '欧美动漫', '动漫电影', '国漫', '日漫', '欧美漫', '动画', '动漫'] },
  { parent: '动漫电影', kids: ['动漫电影', '动画', '国漫', '日漫'] },
  { parent: '短剧', kids: ['短剧', '爽文短剧', '擦边短剧', '逆袭短剧', '都市短剧', '甜宠短剧', '漫剧', 'AI漫剧', 'AI短剧'] },
  { parent: '漫剧', kids: ['漫剧', 'AI漫剧', '动态漫', '动漫短剧'] },
  { parent: '纪录片', kids: ['纪录片', '记录片', '纪实', '人文'] },
  { parent: '体育赛事', kids: ['体育赛事', '足球', '篮球', '台球', '网球', '羽毛球', '其他赛事'] },
  { parent: '预告片', kids: ['预告片'] },
];

// 把某分类名解析成「要聚合的 type_id 列表」
function resolveCatTids(site, name, ownTid) {
  const real = state.catList[site.key] || [];
  const grp = PARENT_GROUPS.find((g) => g.parent === name);
  if (!grp) return ownTid != null ? [ownTid] : [];
  const kids = [];
  grp.kids.forEach((k) => {
    real.forEach((c) => {
      if (String(c.name) === k && !kids.some((x) => String(x) === String(c.id))) kids.push(c.id);
    });
  });
  // 父类自身有数据时优先用它，否则用子类聚合
  if (ownTid != null) return [ownTid].concat(kids.filter((k) => String(k) !== String(ownTid)));
  return kids;
}

// 取分类资源：父类(type_pid=0且有子类)本身常无数据，聚合其子类；否则直接取该 type_id
async function fetchCategoryList(site, tid, pg) {
  pg = pg || 1;
  const d = await cmsGet(join(apiBase(site), { ac: 'videolist', t: tid, pg }), 9000);
  let list = d.list || [];
  if (list.length) return list;
  const children = (state.catList[site.key] || []).filter((c) => String(c.pid) === String(tid));
  if (children.length) {
    const parts = await Promise.all(children.slice(0, 20).map((c) =>
      cmsGet(join(apiBase(site), { ac: 'videolist', t: c.id, pg: 1 }), 6000).then((x) => x.list || []).catch(() => [])
    ));
    list = parts.reduce((a, b) => a.concat(b), []);
  }
  return list;
}

// 按分类名取资源：父类自身无数据时，自动展开成语义相关的子类并聚合。
// 这是对「精确匹配」机制的**叠加**，不改变原有匹配规则：
//   1) 先按站点的真实 type_id 精确查（父类自身有数据就用它）
//   2) 查不到 → 用 resolveCatTids 展开的子类列表并发取，合并去重
async function fetchCategoryByName(site, name, ownTid, limit) {
  limit = limit || 60;
  // 1) 原有精确匹配路径
  if (ownTid != null) {
    try {
      const list = await fetchCategoryList(site, ownTid, 1);
      if (list && list.length) return list.slice(0, limit);
    } catch (e) {}
  }
  // 2) 父类子类聚合路径
  const tids = resolveCatTids(site, name, ownTid);
  if (!tids.length) return [];
  const parts = await Promise.all(tids.slice(0, 24).map((id) =>
    cmsGet(join(apiBase(site), { ac: 'videolist', t: id, pg: 1 }), 7000)
      .then((x) => x.list || []).catch(() => [])
  ));
  const seen = new Set();
  const out = [];
  for (const arr of parts) {
    for (const v of arr) {
      const k = (v.vod_id != null ? v.vod_id : '') + '|' + (v.vod_name || '');
      if (seen.has(k)) continue;
      seen.add(k);
      out.push(v);
      if (out.length >= limit) return out;
    }
  }
  return out;
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
    const d = await cmsGet(join(apiBase(site), { ac: 'videolist', pg: 1 }), 9000);
    box.innerHTML = (d.list || []).slice(0, 24).map(posterHTML).join('') || '<div class="empty">暂无数据</div>';
    bindPosters(box, site);
  } catch (e) { box.innerHTML = '<div class="empty">加载失败：' + esc(e.message) + '</div>'; }
}

function posterHTML(v) {
  const pic = v.vod_pic && /^https?:/i.test(v.vod_pic)
    ? '<div class="thumb" data-img="1" style="background-image:url(' + esc(v.vod_pic) + ')">' +
      '<div class="remarks">' + esc(v.vod_remarks || '') + '</div>' +
      '<span class="imgfail">加载失败</span></div>'
    : '<div class="thumb"><span class="ph">▶</span><div class="remarks">' + esc(v.vod_remarks || '') + '</div></div>';
  return '<div class="poster" data-id="' + esc(v.vod_id) + '" data-name="' + esc(v.vod_name) + '">' + pic +
    '<div class="pname">' + esc(v.vod_name) + '</div></div>';
}

// 图片容错：海报图 CDN 常有慢速/失效链接（实测单张可达 16s 超时），
// 一张坏图会拖住整页观感。这里给每张图加超时与失败提示，超时后自动降级为占位。
const IMG_FAIL_MS = 6000;
function watchImages(box) {
  const imgs = $$('.thumb[data-img]', box);
  if (!imgs.length) return;
  let done = 0;
  const finish = (el, ok) => {
    if (el._imgDone) return;
    el._imgDone = true;
    done++;
    if (!ok) el.classList.add('img-bad');
    if (done >= imgs.length) $$('.thumb[data-img]', box).forEach((e) => e.classList.remove('imgloading'));
  };
  imgs.forEach((el) => {
    el.classList.add('imgloading');
    const url = (el.style.backgroundImage || '').replace(/^url\(["']?/, '').replace(/["']?\)$/, '');
    if (!url) { finish(el, false); return; }
    const probe = new Image();
    let settled = false;
    const timer = setTimeout(() => { if (!settled) { settled = true; finish(el, false); } }, IMG_FAIL_MS);
    probe.onload = () => { if (!settled) { settled = true; clearTimeout(timer); finish(el, true); } };
    probe.onerror = () => { if (!settled) { settled = true; clearTimeout(timer); finish(el, false); } };
    probe.src = url;
  });
}

function bindPosters(box, site) {
  $$('.poster', box).forEach((el) => {
    el.onclick = () => openDetail(site, el.dataset.id, el.dataset.name);
    // 悬停即预取详情，点开时基本秒出
    el.onmouseenter = () => prefetchDetail(site, el.dataset.id);
  });
  watchImages(box);
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
  // 父类（连续剧/综艺/动漫/短剧…）自身无数据时，展开子类聚合后再展示
  const isParent = PARENT_GROUPS.some((g) => g.parent === name);
  if (!tid && !isParent) {
    $('#catList').innerHTML = '<div class="empty">无法解析分类「' + esc(name) + '」的 type_id。<br>该分类在当前站点不存在或接口暂不可用。<br>可尝试顶部搜索框找片。</div>';
    return;
  }
  if (isParent) {
    const list = await fetchCategoryByName(s, name, tid, 120);
    $('#catList').innerHTML = list.length
      ? list.map(posterHTML).join('')
      : '<div class="empty">该分类暂无数据<br><span class="muted" style="font-size:12px">可试试其它站点或用搜索</span></div>';
    bindPosters($('#catList'), s);
    $('#catPager').innerHTML = '';
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
      const d = await cmsGet(join(apiBase(site), { ac: 'videolist', pg }), 9000);
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

// 详情缓存：实测详情接口需 2~3.2s（站点返回 146KB/20 条），是链路最慢的一环。
// 用「悬停预取 + 缓存」把点击到出详情的等待降到接近 0。
const detailCache = new Map();   // siteKey|vodId -> {v, at}
const DETAIL_TTL = 10 * 60 * 1000;

async function fetchDetail(site, id) {
  const key = site.key + '|' + id;
  const hit = detailCache.get(key);
  if (hit && Date.now() - hit.at < DETAIL_TTL) return hit.v;
  try {
    const d = await cmsGet(join(apiBase(site), { ac: 'videolist', id }), 8000);
    const v = (d.list || [])[0];
    if (v) detailCache.set(key, { v, at: Date.now() });
    return v;
  } catch (e) { return null; }
}

// 悬停海报时后台预取详情（节流 220ms，避免划过时打爆接口）
let prefetchTimer = null;
function prefetchDetail(site, id) {
  clearTimeout(prefetchTimer);
  prefetchTimer = setTimeout(() => { fetchDetail(site, id); }, 220);
}

async function openDetail(site, id, fallbackName) {
  const c = $('#content');
  const cached = detailCache.get(site.key + '|' + id);
  if (cached && Date.now() - cached.at < DETAIL_TTL) {
    renderDetail(site, cached.v, fallbackName, id);
    return;
  }
  c.innerHTML = '<div class="empty"><span class="spinner"></span>加载详情…</div>';
  const v = (await fetchDetail(site, id)) || { vod_id: id, vod_name: fallbackName };
  renderDetail(site, v, fallbackName, id);
}

function renderDetail(site, v, fallbackName, id) {
  const c = $('#content');
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
  addHistory({ name: v.vod_name || fallbackName, id, site: site.name, siteKey: site.key, pic: v.vod_pic, type: 'vod' });
}

// ---------- player ----------
// 交互要点（对齐影视仓习惯）：
//  · 单击画面 = 暂停/恢复；不再有常驻的中央播放按钮（仅暂停/恢复时短暂显示图标）
//  · 双击画面 = 全屏
//  · 独立按钮：全屏 / 小窗(画中画) / 弹幕开关 / 系统播放器
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
    $('#playerTitle').textContent = title + ' · ' + (episodes[idx] ? episodes[idx].name : '');
    playEpisode(episodes[idx], title);
  });
  $('#btnExternal').onclick = () => {
    const ep = episodes[state.currentPlay ? state.currentPlay.idx : idx];
    if (!ep) return;
    MS.openWithPlayer(ep.url, title + '_' + ep.name).then((r) => toast(r && r.error ? '调用失败' : '已用系统播放器打开'));
  };
  syncDanmakuButton();
  playEpisode(episodes[idx], title);
}

function fmtTime(sec) {
  if (!isFinite(sec) || sec < 0) sec = 0;
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
  const mm = h ? String(m).padStart(2, '0') : String(m);
  return (h ? h + ':' : '') + mm + ':' + String(s).padStart(2, '0');
}

function playEpisode(ep, title) {
  if (!ep || !ep.url) return;
  const video = $('#video'); const msg = $('#playerMsg');
  msg.classList.add('hidden');
  if (state.playerHls) { state.playerHls.destroy(); state.playerHls = null; }
  video.pause();
  danmakuStop();
  const url = ep.url;
  // 记录当前源，弹幕开关按源记忆状态
  state.currentPlay = state.currentPlay || {};
  state.currentPlay.source = url;
  state.currentPlay.title = title;
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

// ---- 播放 / 暂停 ----
function togglePlay() {
  const v = $('#video');
  if (!v) return;
  if (v.paused) { v.play().catch(() => {}); showPlayIcon(false); }
  else { v.pause(); showPlayIcon(true); }
}
function showPlayIcon(paused) {
  const ov = $('#playOverlay');
  if (!ov) return;
  const icon = ov.querySelector('.po-icon');
  if (icon) icon.textContent = paused ? '▶' : '⏸';
  ov.classList.remove('hidden');
  ov.classList.add('show');
  clearTimeout(ov._t);
  ov._t = setTimeout(() => { ov.classList.remove('show'); }, paused ? 900 : 420);
}

// ---- 全屏 / 小窗 ----
function toggleFullscreen() {
  const stage = $('#playerStage');
  if (!stage) return;
  try {
    if (document.fullscreenElement) document.exitFullscreen();
    else if (stage.requestFullscreen) stage.requestFullscreen();
    else toast('当前环境不支持全屏');
  } catch (e) { toast('全屏切换失败：' + (e && e.message || e)); }
}
async function togglePiP() {
  const v = $('#video');
  if (!v) return;
  try {
    if (document.pictureInPictureElement) { await document.exitPictureInPicture(); return; }
    if (!document.pictureInPictureEnabled) { toast('当前环境不支持小窗播放'); return; }
    await v.requestPictureInPicture();
  } catch (e) { toast('小窗播放失败：' + (e && e.message || e)); }
}

// ---- 播放器控制条绑定 ----
function bindPlayerControls() {
  const video = $('#video');
  const stage = $('#playerStage');
  if (!video || !stage) return;

  // 单击画面：暂停/恢复（点控制条不触发）
  stage.addEventListener('click', (e) => {
    if (e.target.closest('.player-controls')) return;
    togglePlay();
  });
  // 双击画面：全屏
  stage.addEventListener('dblclick', (e) => {
    if (e.target.closest('.player-controls')) return;
    toggleFullscreen();
  });

  $('#btnPP').onclick = () => togglePlay();
  $('#btnFullscreen').onclick = () => toggleFullscreen();
  $('#btnPiP').onclick = () => togglePiP();
  $('#btnDanmaku').onclick = () => toggleDanmaku();

  $('#pcVol').onclick = () => {
    video.muted = !video.muted;
    $('#pcVol').textContent = video.muted ? '🔇' : '🔊';
  };
  $('#pcRate').onchange = (e) => { video.playbackRate = parseFloat(e.target.value) || 1; };
  $('#pcSeek').oninput = (e) => {
    if (!video.duration || !isFinite(video.duration)) return;
    video.currentTime = (e.target.value / 1000) * video.duration;
  };
  video.addEventListener('timeupdate', () => {
    const cur = $('#pcTime'); const seek = $('#pcSeek');
    if (cur) cur.textContent = fmtTime(video.currentTime) + ' / ' + fmtTime(video.duration);
    if (seek && video.duration && isFinite(video.duration)) {
      seek.value = Math.round((video.currentTime / video.duration) * 1000);
    }
    // 观看进度写回历史（节流：每 5 秒一次）
    const now = Date.now();
    if (now - (video._lastProg || 0) > 5000) {
      video._lastProg = now;
      const ep = state.currentPlay && state.currentPlay.episodes && state.currentPlay.idx != null
        ? (state.currentPlay.episodes[state.currentPlay.idx] || {}).name : '';
      updateHistoryProgress(state.currentPlay && state.currentPlay.title, video.currentTime, ep);
    }
  });
  video.addEventListener('play', () => { const b = $('#btnPP'); if (b) b.textContent = '⏸'; });
  video.addEventListener('pause', () => { const b = $('#btnPP'); if (b) b.textContent = '▶'; });
}

$('#btnPlayerClose').onclick = () => {
  const v = $('#video'); v.pause(); v.removeAttribute('src'); v.load();
  if (state.playerHls) { state.playerHls.destroy(); state.playerHls = null; }
  danmakuStop();
  $('#player').classList.add('hidden');
};

// ---------- 弹幕 ----------
// 设计（对齐影视仓习惯）：
//  · 总开关在设置面板；播放器右上角的「弹」按钮是当前播放源的独立开关
//  · 每个源的开关状态单独记忆（按源 URL 哈希存本地），切源自动切换
//  · 弹幕数据源：优先用配置里的 danmaku 字段；否则尝试常见的公开弹幕接口
//    （https://api.danmu.icu/?title=片名 或第三方弹幕接口），失败静默降级
const DANMAKU_APIS = [
  (name) => 'https://api.danmu.icu/?title=' + encodeURIComponent(name),
];
const danmakuState = {
  enabled: false,
  timer: null,
  items: [],
  idx: 0,
  layer: null,
  loadedFor: '',
};

function danmakuSourceKey(url) {
  const s = String(url || '');
  let h = 0;
  for (let i = 0; i < s.length; i++) { h = ((h << 5) - h + s.charCodeAt(i)) | 0; }
  return 'dm_' + (h >>> 0).toString(36);
}

// 每个源单独记忆开关状态
function danmakuPerSource() { return loadLS('ms_danmaku_sources', {}); }
function isDanmakuOnFor(url) {
  const map = danmakuPerSource();
  if (Object.prototype.hasOwnProperty.call(map, danmakuSourceKey(url))) return !!map[danmakuSourceKey(url)];
  return !!(state.settings && state.settings.danmaku);
}
function setDanmakuForSource(url, on) {
  const map = danmakuPerSource();
  map[danmakuSourceKey(url)] = !!on;
  saveLS('ms_danmaku_sources', map);
}
function syncDanmakuButton() {
  const btn = $('#btnDanmaku');
  if (!btn) return;
  const url = state.currentPlay && state.currentPlay.source;
  const on = !!url && isDanmakuOnFor(url);
  btn.classList.toggle('on', on);
  btn.textContent = on ? '弹 开' : '弹 关';
  btn.title = on ? '关闭当前片源的弹幕' : '开启当前片源的弹幕';
}
function toggleDanmaku() {
  const url = state.currentPlay && state.currentPlay.source;
  if (!url) { toast('尚未开始播放'); return; }
  const now = !isDanmakuOnFor(url);
  setDanmakuForSource(url, now);
  syncDanmakuButton();
  if (now) danmakuStart(url); else danmakuStop();
  toast(now ? '已开启弹幕' : '已关闭弹幕');
}

function danmakuStop() {
  if (danmakuState.timer) { clearInterval(danmakuState.timer); danmakuState.timer = null; }
  danmakuState.items = [];
  danmakuState.idx = 0;
  const layer = $('#danmakuLayer');
  if (layer) layer.innerHTML = '';
}

async function danmakuStart(url) {
  danmakuStop();
  const title = (state.currentPlay && state.currentPlay.title) || '';
  if (!title) return;
  const layer = $('#danmakuLayer');
  if (!layer) return;
  danmakuState.layer = layer;

  let list = [];
  // 1) 配置里显式指定的弹幕接口
  const cfgDm = state.config && state.config.danmaku;
  if (cfgDm && typeof cfgDm === 'string') {
    try {
      const r = await MS.httpGet(cfgDm.replace('{title}', encodeURIComponent(title)), { 'User-Agent': 'okhttp/3.15' }, 8000);
      const j = JSON.parse(r.body);
      list = (j.danmu || j.comments || j.data || []).map((d) => d.text || d.content || d.m || '').filter(Boolean);
    } catch (e) {}
  }
  // 2) 兜底：公开弹幕接口
  if (!list.length) {
    for (const mk of DANMAKU_APIS) {
      try {
        const r = await MS.httpGet(mk(title), { 'User-Agent': 'okhttp/3.15' }, 8000);
        const j = JSON.parse(r.body);
        list = (j.danmu || j.comments || j.data || []).map((d) => d.text || d.content || d.m || '').filter(Boolean);
        if (list.length) break;
      } catch (e) {}
    }
  }
  if (!list.length) { toast('未获取到弹幕数据'); syncDanmakuButton(); return; }

  danmakuState.items = list;
  danmakuState.loadedFor = url;
  const speed = Math.max(2, (state.settings && state.settings.danmakuSpeed) || 8);
  danmakuState.timer = setInterval(() => {
    if (danmakuState.idx >= danmakuState.items.length) danmakuState.idx = 0;
    danmakuEmit(danmakuState.items[danmakuState.idx++], speed);
  }, 900);
}

function danmakuEmit(text, speed) {
  const layer = danmakuState.layer || $('#danmakuLayer');
  if (!layer || !text) return;
  const s = state.settings || {};
  const stage = $('#playerStage');
  const W = stage ? stage.clientWidth : 900;
  const H = stage ? stage.clientHeight : 500;
  const el = document.createElement('div');
  el.className = 'danmaku-item';
  el.textContent = text;
  el.style.fontSize = (s.danmakuFontSize || 22) + 'px';
  el.style.opacity = String(s.danmakuOpacity != null ? s.danmakuOpacity : 0.85);
  const area = s.danmakuArea != null ? s.danmakuArea : 0.5;
  const top = 8 + Math.random() * Math.max(0, (H * area - 40));
  el.style.top = top + 'px';
  el.style.left = W + 'px';
  layer.appendChild(el);
  const dur = (W + 260) / (speed * 12);
  el.style.transition = 'transform ' + dur + 's linear';
  requestAnimationFrame(() => { el.style.transform = 'translateX(-' + (W + 260) + 'px)'; });
  setTimeout(() => { if (el.parentNode) el.parentNode.removeChild(el); }, dur * 1000 + 400);
}

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
    const d = await cmsGet(join(apiBase(s), { ac: 'videolist', wd: kw, pg: 1 }), 9000);
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
  chMap: null,     // id → 频道 索引（渲染 O(1) 查找）
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
  expanded: {},     // 分组是否已「展开其余」
  filter: '',
};
function saveLiveSettings() {
  saveLS('ms_live_timeout', liveState.timeoutSec);
  saveLS('ms_live_decoder', liveState.decoder);
  saveLS('ms_live_player', liveState.player);
  saveLS('ms_live_collapsed', liveState.collapsed);
  // 同步到主进程设置，跨重启保留
  saveSettings({
    liveTimeout: liveState.timeoutSec,
    liveDecoder: liveState.decoder,
    livePlayer: liveState.player,
  });
}

function parseTVLines(text) {
  // 影视仓/TVBox 标准 TXT：分组行「组名,#genre#」+ 一行一条线路，同名频道会重复出现。
  // 必须按频道名合并成「一个频道多条线路」，否则列表里会出现几十个重名频道。
  const groups = []; let cur = null;
  const body = (text || '').replace(/^\uFEFF/, '');
  body.split(/\r?\n/).forEach((line) => {
    line = line.trim(); if (!line) return;
    if (/#genre#\s*$/.test(line)) {
      const name = line.replace(/,#genre#\s*$/, '').trim();
      cur = { name, items: [], _m: new Map() }; groups.push(cur); return;
    }
    const idx = line.indexOf(',');
    if (idx > 0 && cur) {
      const name = line.slice(0, idx).trim();
      const urls = line.slice(idx + 1).split(/[,#]/).map((u) => u.trim()).filter((u) => /^https?:\/\//i.test(u));
      if (!name || !urls.length) return;
      let it = cur._m.get(name);
      if (!it) { it = { name, urls: [] }; cur._m.set(name, it); cur.items.push(it); }
      urls.forEach((u) => { if (it.urls.indexOf(u) < 0) it.urls.push(u); });
    }
  });
  groups.forEach((g) => { delete g._m; });
  return groups.filter((g) => g.items.length);
}
function parseM3U(text) {
  // M3U 标准：一个 #EXTINF 后面可跟多条 URL（= 同一频道的多条线路）。
  // 必须把连续 URL 归到同一频道，否则同名频道被拆成多条、无法在左下角切换线路。
  // 同时按 group-title / #EXTGRP 建组，避免全部塞进一个「赛事轮播」。
  const groupMap = new Map();
  const groups = [];
  let pending = null;       // 当前频道的显示名
  let pendingGroup = null;  // 当前频道的分组名
  let curItem = null;       // 当前频道对象（连续 URL 都加进它的 urls）
  const getGroup = (name) => {
    let nm = name || '默认';
    // 上游 M3U 偶发某行字节截断，中文变 \uFFFD（如「影视轮⧉⧉⧉」）→ 按前缀并回正常组
    if (/\uFFFD/.test(nm)) {
      const clean = nm.replace(/\uFFFD/g, '');
      // 正常组名已存在时：畸形串去掉坏字节后与它互为包含关系即并回
      const hit = clean && Array.from(groupMap.keys()).find((k) => k !== nm && clean.length >= 2 && (k.indexOf(clean) >= 0 || clean.indexOf(k) >= 0));
      if (hit) nm = hit;
    }
    let g = groupMap.get(nm);
    if (!g) { g = { name: nm, items: [], _m: new Map() }; groupMap.set(nm, g); groups.push(g); }
    return g;
  };
  (text || '').replace(/^\uFEFF/, '').split(/\r?\n/).forEach((line) => {
    line = line.trim();
    if (/^#EXTGRP:/i.test(line)) { pendingGroup = line.replace(/^#EXTGRP:/i, '').trim(); return; }
    if (/^#EXTINF:/i.test(line)) {
      const mm = line.match(/group-title="([^"]*)"/i);
      pendingGroup = mm ? mm[1].trim() : pendingGroup;
      pending = line.replace(/^#EXTINF:[^,]*,/i, '').trim();
      curItem = null;   // 下一个频道，URL 不能并入上一个
      return;
    }
    if (line && !/^#/.test(line) && /^https?:\/\//i.test(line)) {
      const g = getGroup(pendingGroup);
      const name = (pendingGroup && pending && pending.indexOf(pendingGroup) >= 0)
        ? pending : (pending || ('频道' + (g.items.length + 1)));
      let it = g._m.get(name);
      if (!it) { it = { name, urls: [] }; g._m.set(name, it); g.items.push(it); }
      if (it.urls.indexOf(line) < 0) it.urls.push(line);
      curItem = it;
    }
  });
  groups.forEach((g) => { delete g._m; });
  return groups.filter((g) => g.items.length);
}
function normChannel(name) {
  return String(name || '').toUpperCase().replace(/[\s\-_—]/g, '')
    .replace(/(高清|超清|蓝光|HD|4K|1080P|720P)$/i, '').trim();
}

// 构建频道目录：同名频道只保留一个名字，多个源/分组的 URL 合并为“线路”
// 性能：分组内用 Set 去重（原来 channelIds.indexOf 在上千条分组里是 O(n²)）
function buildLiveCatalog() {
  const byName = new Map();
  const cats = [];
  Object.keys(liveCache || {}).forEach((src) => {
    (liveCache[src] || []).forEach((g) => {
      const cat = { source: src, name: g.name, channelIds: [], id: src + '|' + g.name };
      const seen = new Set();
      g.items.forEach((it) => {
        const key = normChannel(it.name);
        if (!key) return;
        let ch = byName.get(key);
        if (!ch) {
          ch = { id: 'ch' + byName.size, name: it.name, key, urls: [] };
          byName.set(key, ch);
        }
        it.urls.forEach((u) => { if (ch.urls.indexOf(u) < 0) ch.urls.push(u); });
        if (!seen.has(ch.id)) { seen.add(ch.id); cat.channelIds.push(ch.id); }
      });
      if (cat.channelIds.length) cats.push(cat);
    });
  });
  liveState.channels = Array.from(byName.values());
  liveState.cats = cats;
  // id → 频道 的索引，供渲染时 O(1) 查找
  const chMap = new Map();
  liveState.channels.forEach((c) => chMap.set(c.id, c));
  liveState.chMap = chMap;
}

async function ensureLiveData() {
  if (liveCache) return;
  const pending = {};

  // 直播源来自订阅配置的 lives（type=0 + url 指向 TXT / M3U 地址）。
  // 应用不再内置任何直播资源文件，因此必须从订阅里取；取不到就如实提示。
  const lives = (state.config && Array.isArray(state.config.lives)) ? state.config.lives : [];
  const tasks = [];
  lives.forEach((lv) => {
    if (!lv || !lv.url) return;
    if (lv.type != null && Number(lv.type) !== 0) return;   // 只有 type=0 的 TXT 直播源
    tasks.push((async () => {
      try {
        const r = await MS.httpGet(lv.url, { 'User-Agent': 'okhttp/3.15' }, 20000);
        if (!r || !r.body) return;
        const text = r.body;
        let groups = [];
        if (/^﻿?\s*#EXTM3U/i.test(text) || text.indexOf('#EXTINF') >= 0) groups = parseM3U(text);
        else groups = parseTVLines(text);
        if (groups.length) {
          pending[lv.name || lv.url] = groups;
        }
      } catch (e) {
        console.warn('[live] 拉取失败', lv.name || lv.url, e && e.message);
      }
    })());
  });

  if (tasks.length) await Promise.all(tasks);

  // 订阅里没有 lives 或全部拉取失败时，退回本地 config 目录（若用户手动放了文件）
  if (!Object.keys(pending).length) {
    for (const name of ['TVLives.txt', 'BiliLive.txt', 'LiveSports.txt']) {
      try {
        const txt = await MS.readConfig(name);
        const g = parseTVLines(txt);
        if (g.length) pending[name] = g;
      } catch (e) {}
    }
  }

  liveCache = pending;
  buildLiveCatalog();
  try { liveState.players = await MS.detectPlayers(); } catch (e) { liveState.players = {}; }
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

// 直播树渲染：频道量可达数千，需避免 O(n²) 查找与全量 DOM 构建
// 1) 用 Map 做 id→频道 索引（原来 channels.find() 每次 O(n)，嵌套后 O(n²)）
// 2) 事件委托替代逐个绑定 onclick（原来要给 3000+ 个节点挂监听器）
// 3) 每个分组默认只渲染前 N 个，其余折叠为「展开其余 X 个」，按需渲染
const LIVE_PAGE_SIZE = 60;

function renderLiveTree() {
  const box = $('#liveTree'); if (!box) return;
  const kw = normChannel(liveState.filter);
  const chMap = liveState.chMap || new Map();
  const matches = (ch) => !ch || !kw || normChannel(ch.name).indexOf(kw) >= 0;
  const expanded = liveState.expanded || (liveState.expanded = {});
  let html = '';
  liveState.cats.forEach((cat) => {
    const ids = [];
    for (let i = 0; i < cat.channelIds.length; i++) {
      const ch = chMap.get(cat.channelIds[i]);
      if (matches(ch)) ids.push(ch);
    }
    if (!ids.length) return;
    const collapsed = !!liveState.collapsed[cat.id];
    html += '<div class="live-cat"><div class="live-cat-head" data-cat="' + esc(cat.id) + '">' +
      '<span class="caret">' + (collapsed ? '▸' : '▾') + '</span>' + esc(cat.name) +
      '<small>(' + ids.length + ')</small></div>';
    if (!collapsed) {
      const isAll = !!expanded[cat.id] || !!kw;   // 搜索时直接全量显示结果
      // 搜索结果过多时也要限量，避免一次渲染上万个节点
      const cap = kw ? 300 : LIVE_PAGE_SIZE;
      const show = isAll ? ids.slice(0, cap) : ids.slice(0, LIVE_PAGE_SIZE);
      html += '<div class="live-ch-list">';
      show.forEach((ch) => {
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
      if (!isAll && ids.length > LIVE_PAGE_SIZE) {
        html += '<div class="live-more" data-more="' + esc(cat.id) + '">展开其余 ' + (ids.length - LIVE_PAGE_SIZE) + ' 个 ›</div>';
      } else if (kw && ids.length > cap) {
        html += '<div class="live-more muted" title="结果过多，仅显示前 ' + cap + ' 个">仅显示前 ' + cap + ' 个（共 ' + ids.length + '）</div>';
      }
      html += '</div>';
    }
    html += '</div>';
  });
  box.innerHTML = html || (liveState.cats.length
    ? '<div class="empty">无匹配频道</div>'
    : '<div class="empty" style="line-height:2">当前订阅未提供直播源。<br>可在影视仓配置中增加 <b>lives</b>（type=0，url 指向 TXT/M3U 直播列表）。</div>');

  // 事件委托：只绑 3 个监听器，而不是给每个频道节点单独绑
  box.onclick = (e) => {
    const head = e.target.closest('.live-cat-head');
    if (head) {
      const id = head.dataset.cat;
      liveState.collapsed[id] = !liveState.collapsed[id];
      saveLiveSettings(); renderLiveTree();
      return;
    }
    const more = e.target.closest('.live-more');
    if (more) {
      liveState.expanded[more.dataset.more] = true;
      renderLiveTree();
      return;
    }
    const el = e.target.closest('.live-ch');
    if (!el) return;
    const ch = chMap.get(el.dataset.id);
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
  };
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
  const isFav = kind === 'favorite';
  c.innerHTML = '<div class="section-title">' + (isFav ? '我的收藏' : '观看历史') + ' <small>' + arr.length + ' 条</small></div>' +
    (arr.length ? '<div class="row-list">' + arr.map((x, i) => {
      const live = x.type === 'live';
      const badge = live ? '<span class="badge live">直播</span>' : '<span class="badge">点播</span>';
      const time = x.at ? ' · ' + new Date(x.at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '';
      const prog = (!live && x.pos) ? ' · 已看到 ' + fmtTime(x.pos) : '';
      const ep = x.ep ? ' · 第 ' + esc(String(x.ep)) + ' 集' : '';
      return '<div class="row-item" data-i="' + i + '">' +
        '<div class="rthumb"' + (x.pic && /^https?:/i.test(x.pic) ? ' style="background-image:url(' + esc(x.pic) + ')"' : '') + '></div>' +
        '<div class="rinfo"><b>' + esc(x.name) + '</b><span>' + esc(x.site || '') + badge + esc(time) + esc(prog) + esc(ep) + '</span></div>' +
        '<button class="del" data-del="' + i + '">✕</button></div>';
    }).join('') + '</div>'
      : '<div class="empty">' + (isFav ? '还没有收藏，播放时可加入收藏' : '还没有观看记录') + '</div>');

  // 点播记录：点击可重新打开详情并续播（影视仓习惯）
  $$('.row-item', c).forEach((row) => {
    const item = arr[+row.dataset.i];
    if (!item || item.type === 'live') return;
    row.onclick = () => {
      const site = state.sites.find((s) => s.name === item.site || s.key === item.siteKey);
      if (!site) { toast('原站点已不在当前订阅中'); return; }
      state.site = site; renderSites();
      openDetail(site, item.id, item.name);
    };
  });

  $$('.del', c).forEach((b) => b.onclick = (ev) => {
    ev.stopPropagation(); const i = +b.dataset.del; arr.splice(i, 1);
    if (isFav) { state.favorites = arr; saveLS('ms_favorites', arr); } else { state.history = arr; saveLS('ms_history', arr); }
    renderStore(kind);
  });
}
function addHistory(item) {
  item.at = Date.now();
  state.history = state.history.filter((x) => !(x.id === item.id && x.site === item.site));
  state.history.unshift(item); state.history = state.history.slice(0, 60);
  saveLS('ms_history', state.history);
}

// 播放进度写入历史（供历史页显示"已看到 xx:xx"）
function updateHistoryProgress(title, pos, epName) {
  const key = state.currentPlay && state.currentPlay.title;
  if (!key) return;
  const h = state.history.find((x) => x.name === key);
  if (!h) return;
  h.pos = pos; if (epName) h.ep = epName; h.at = Date.now();
  saveLS('ms_history', state.history);
}

// ---------- events ----------
$$('.tab').forEach((b) => b.onclick = () => setView(b.dataset.view));
$('#quickSearch').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { const kw = e.target.value.trim(); if (kw) doSearch(kw); }
});

// ---- 主题切换 ----
$('#btnTheme').onclick = () => {
  const next = (state.settings.theme === 'light') ? 'dark' : 'light';
  applyTheme(next);
  saveSettings({ theme: next });
  toast(next === 'light' ? '已切换到浅色主题' : '已切换到深色主题');
};

// ---- 设置面板 ----
function openSettings() {
  const s = state.settings || {};
  $('#segTheme').querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.theme === (s.theme || 'dark')));
  $('#swDanmaku').checked = !!s.danmaku;
  $('#rgDanmakuOpacity').value = s.danmakuOpacity != null ? Math.round(s.danmakuOpacity * 100) : 85;
  $('#vlDanmakuOpacity').textContent = Math.round((s.danmakuOpacity != null ? s.danmakuOpacity : 0.85) * 100) + '%';
  $('#rgDanmakuFont').value = s.danmakuFontSize || 22;
  $('#vlDanmakuFont').textContent = (s.danmakuFontSize || 22) + 'px';
  $('#rgDanmakuArea').value = Math.round((s.danmakuArea != null ? s.danmakuArea : 0.5) * 100);
  $('#vlDanmakuArea').textContent = Math.round((s.danmakuArea != null ? s.danmakuArea : 0.5) * 100) + '%';
  $('#rgDanmakuSpeed').value = s.danmakuSpeed || 8;
  $('#vlDanmakuSpeed').textContent = String(s.danmakuSpeed || 8);
  $('#settingsMsg').textContent = '';
  $('#settingsDialog').classList.remove('hidden');
  MS.storeInfo().then((i) => { if (i && i.dir) $('#setPath').textContent = i.dir; }).catch(() => {});
}
$('#btnSettings').onclick = openSettings;
$('#btnSettingsCancel').onclick = () => $('#settingsDialog').classList.add('hidden');
$('#segTheme').querySelectorAll('button').forEach((b) => b.onclick = () => {
  $('#segTheme').querySelectorAll('button').forEach((x) => x.classList.remove('on'));
  b.classList.add('on');
});
const bindRange = (id, valId, fmt, scale) => {
  const el = $(id); if (!el) return;
  el.oninput = () => { $(valId).textContent = fmt(el.value, scale); };
};
bindRange('#rgDanmakuOpacity', '#vlDanmakuOpacity', (v) => v + '%');
bindRange('#rgDanmakuFont', '#vlDanmakuFont', (v) => v + 'px');
bindRange('#rgDanmakuArea', '#vlDanmakuArea', (v) => v + '%');
bindRange('#rgDanmakuSpeed', '#vlDanmakuSpeed', (v) => v);

$('#btnSettingsOk').onclick = async () => {
  const theme = ($('#segTheme').querySelector('button.on') || {}).dataset
    ? $('#segTheme').querySelector('button.on').dataset.theme : 'dark';
  const patch = {
    theme: theme,
    danmaku: $('#swDanmaku').checked,
    danmakuOpacity: parseInt($('#rgDanmakuOpacity').value, 10) / 100,
    danmakuFontSize: parseInt($('#rgDanmakuFont').value, 10),
    danmakuArea: parseInt($('#rgDanmakuArea').value, 10) / 100,
    danmakuSpeed: parseInt($('#rgDanmakuSpeed').value, 10),
  };
  applyTheme(patch.theme);
  await saveSettings(patch);
  $('#settingsDialog').classList.add('hidden');
  toast('设置已保存');
};

// ---- 导出 / 导入备份 ----
$('#btnExport').onclick = async () => {
  try {
    const r = await MS.exportBackup(null);
    if (r && r.canceled) return;
    if (r && r.error) { $('#settingsMsg').textContent = '导出失败：' + r.error; return; }
    toast('已导出备份：' + (r && r.file ? r.file : ''));
  } catch (e) { $('#settingsMsg').textContent = '导出失败：' + e.message; }
};
$('#btnImportCfg').onclick = () => importBackupFile();

async function importBackupFile() {
  try {
    const r = await MS.importBackup();
    if (r && r.canceled) return;
    if (r && r.error) { toast('导入失败：' + r.error); return; }
    // 恢复设置并重载订阅
    state.settings = await MS.getSettings();
    applyTheme(state.settings.theme);
    state.site = null; state.typeMap = {}; state.catList = {}; state._catTid = {}; homeCache = {};
    liveCache = null; liveState.channels = []; liveState.cats = []; liveState.current = null;
    await loadConfig();
    $('#settingsDialog').classList.add('hidden');
    toast('配置已导入');
  } catch (e) { toast('导入失败：' + (e && e.message || e)); }
}

// ---- 重置（弹框确认，选否则不做任何操作）----
$('#btnReset').onclick = () => {
  $('#settingsDialog').classList.add('hidden');
  $('#resetDialog').classList.remove('hidden');
};
$('#btnResetNo').onclick = () => { $('#resetDialog').classList.add('hidden'); };
$('#btnResetYes').onclick = async () => {
  $('#resetDialog').classList.add('hidden');
  try {
    await MS.resetUserData();
    // 清空本地缓存并回到空壳状态
    ['ms_favorites', 'ms_history', 'ms_last_site', 'ms_danmaku_sources', 'ms_live_collapsed'].forEach((k) => {
      try { localStorage.removeItem(k); } catch (e) {}
    });
    state.favorites = []; state.history = []; state.site = null;
    state.typeMap = {}; state.catList = {}; state._catTid = {}; homeCache = {};
    liveCache = null; liveState.channels = []; liveState.cats = []; liveState.current = null;
    state.settings = await MS.getSettings();
    applyTheme(state.settings.theme);
    state.shellMode = true;
    renderShell();
    setView('home');
    toast('已清除全部配置，恢复到初始状态');
  } catch (e) { toast('重置失败：' + (e && e.message || e)); }
};

// ---- 采集站 ----
$('#btnReload').onclick = async () => {
  if (state.shellMode) { toast('尚未导入订阅'); return; }
  state.typeMap = {}; state.catList = {}; state._catTid = {}; homeCache = {};
  await loadConfig();
  liveCache = null; liveState.channels = []; liveState.cats = []; liveState.current = null;
  if (state.view === 'live') renderLive();
  toast('配置与分类已重新加载');
};
const bas = $('#btnAutoSite');
if (bas) bas.onclick = async () => {
  if (state.shellMode) { toast('尚未导入订阅'); return; }
  bas.disabled = true; bas.textContent = '检测中…';
  try { await autoPickSite(); }
  finally { bas.disabled = false; bas.textContent = '⚡ 自动选站'; }
};
const bsl = $('#btnSwitchLine');
if (bsl) bsl.onclick = () => {
  if (state.shellMode) { toast('尚未导入订阅'); return; }
  switchLine();
};
const bsl2 = $('#btnSwitchLineSet');
if (bsl2) bsl2.onclick = () => {
  $('#settingsDialog').classList.add('hidden');
  setTimeout(() => { if (!state.shellMode) switchLine(); else toast('尚未导入订阅'); }, 120);
};

// ---- 影视仓多级索引展开 ----
// 影视仓配置有三种形态，导入时统一展开成含 sites 的扁平配置：
//   1) 站点配置: { sites:[...], lives:[...] }         —— 直接用
//   2) 多仓索引: { storeHouse:[{sourceUrl}, ...] }    —— 逐个尝试，取第一个可达仓库
//   3) 多线路:   { urls:[{url,name}, ...] }           —— 并发探测，取最快可用线路
// 影视仓 App 是逐级让用户选，壳这里自动选最快的一条线路（站点数可控，不会几百站拖垮启动测速）。
// 展开只在导入时执行一次，结果持久化；启动 loadConfig 直接读缓存，不再展开。
const EXPAND_UA = { 'User-Agent': 'okhttp/3.15' };
async function fetchJsonCfg(u, timeout) {
  const r = await MS.httpGet(u, EXPAND_UA, timeout || 12000);
  if (r.error || !r.body) return null;
  try { return JSON.parse(r.body); } catch (e) { return null; }
}
// 选线质量标准：sites 数量为主（空壳垂直线路只有 1 站），直播源有效为辅，速度只作最后参考。
// 实测教训：曾纯按响应速度排序，结果 sites=1 的短剧/课堂/赛事空壳线路（体积小、CDN 命中快，
// ~180ms）总比主线路（~280ms）快而被选中 —— 表现为站点几乎为空、直播源指向失效的
// PlatformLive.txt / 旧 TXT，用户看到「多仓解析混乱 + 直播无法播放」。
function compareLineQuality(a, b) {
  if (b.sites !== a.sites) return b.sites - a.sites;
  if (b.goodLives !== a.goodLives) return b.goodLives - a.goodLives;
  return a.ms - b.ms;
}
// 并发探测一组候选（storeHouse / urls 通用），返回每个候选的元数据 + 配置体。
// ok=命中含 sites 的末级；next=指向下一级索引（storeHouse/urls）；两者都不是=无效线路。
async function probeCandidates(items) {
  return await Promise.all((items || []).map(async (item) => {
    const u = item && (item.url || item.sourceUrl);
    const entry = {
      name: (item && item.name) || '', url: u || '', cfg: null,
      ms: 0, sites: 0, goodLives: 0, livesTotal: 0, next: '', ok: false,
    };
    if (!u || !/^https?:\/\//i.test(u)) return entry;
    const t0 = Date.now();
    const c = await fetchJsonCfg(u, 12000);
    entry.ms = Date.now() - t0;
    if (!c) return entry;
    entry.cfg = c;
    if (Array.isArray(c.sites) && c.sites.length) {
      entry.ok = true;
      entry.sites = c.sites.length;
      const lives = Array.isArray(c.lives) ? c.lives : [];
      entry.livesTotal = lives.length;
      // 有效直播源：url 指向 m3u8/m3u/txt 且不是已知失效的 PlatformLive
      entry.goodLives = lives.filter((l) => {
        const lu = l && l.url;
        return lu && /\.(m3u8?|txt)(\?|$)/i.test(lu) && !/PlatformLive/i.test(lu);
      }).length;
    } else if (Array.isArray(c.storeHouse) && c.storeHouse.length) entry.next = 'storeHouse';
    else if (Array.isArray(c.urls) && c.urls.length) entry.next = 'urls';
    return entry;
  }));
}
async function pickBestLine(urls) {
  const ok = (await probeCandidates(urls)).filter((x) => x.ok);
  if (!ok.length) throw new Error('所有线路均不可用（配置可能已失效）');
  ok.sort(compareLineQuality);
  return ok[0].cfg;
}

// 影视仓式「自己选线路」：逐级展开，遇到 storeHouse / urls 就回调 choose 让用户挑。
// choose({kind, candidates}) -> 索引 | 'auto'(自动选质量最好) | null(取消)
// 返回 { cfg, trail }；trail 记录每级选择，供持久化与「切换线路」复用。
async function expandInteractive(url, rootCfg, choose) {
  let cur = rootCfg;
  const visited = Object.create(null);
  if (url) visited[url] = 1;
  const trail = [];
  for (let depth = 0; depth < 6; depth++) {
    if (!cur || typeof cur !== 'object') break;
    if (Array.isArray(cur.sites) && cur.sites.length) return { cfg: cur, trail };
    let items = null; let kind = '';
    if (Array.isArray(cur.storeHouse) && cur.storeHouse.length) { items = cur.storeHouse; kind = 'storeHouse'; }
    else if (Array.isArray(cur.urls) && cur.urls.length) { items = cur.urls; kind = 'urls'; }
    else break;
    const cands = await probeCandidates(items.map((i) => {
      const iu = i && (i.url || i.sourceUrl);
      return iu && visited[iu] ? Object.assign({}, i, { _visited: true }) : i;
    }));
    const pick = await choose({ kind: kind, candidates: cands });
    if (pick == null) throw new Error('已取消选线');
    let chosen;
    if (pick === 'auto') {
      const avail = cands.filter((c) => !c._visited && (c.ok || c.next));
      // 优先末级站点配置（按质量排序）；全是中间索引时取第一条继续往下展开
      const leaves = avail.filter((c) => c.ok).sort(compareLineQuality);
      const pool = leaves.length ? leaves : avail.filter((c) => c.next);
      if (!pool.length) throw new Error('没有可用的线路');
      chosen = pool[0];
    } else {
      chosen = cands[pick];
      if (!chosen || !chosen.url) throw new Error('无效的选择');
      if (!chosen.ok && !chosen.next) throw new Error('该线路不可用');
    }
    visited[chosen.url] = 1;
    trail.push({ kind: kind, url: chosen.url, name: chosen.name });
    if (!chosen.cfg) throw new Error('线路无有效内容');
    cur = chosen.cfg;
  }
  if (cur && Array.isArray(cur.sites) && cur.sites.length) return { cfg: cur, trail: trail };
  throw new Error('无法从该配置展开出站点（sites）');
}

// ---- 线路选择弹窗 ----
function shortHost(u) {
  try {
    const x = new URL(u);
    return x.hostname.replace(/^www\./, '') + (x.pathname && x.pathname !== '/' ? x.pathname.slice(0, 22) : '');
  } catch (e) { return String(u || '').slice(0, 34); }
}
// 返回 Promise：用户点某行=该行索引，点「自动选最优」='auto'，点取消=null
function showLineDialog(kind, candidates, currentUrl) {
  return new Promise((resolve) => {
    const dlg = $('#lineDialog');
    const list = $('#lineList');
    $('#lineDialogTitle').textContent = kind === 'storeHouse' ? '选择仓库' : '选择线路';
    $('#lineDialogTip').textContent = kind === 'storeHouse'
      ? '检测到多个仓库，请选择要使用的仓库：'
      : '检测到多条线路，选站点多、直播源全的通常更完整：';
    list.innerHTML = '';
    const bestSites = Math.max.apply(null, [0].concat(candidates.map((c) => c.sites || 0)));
    const order = candidates.map((c, i) => ({ c: c, i: i })).sort((a, b) => {
      if (a.c.ok !== b.c.ok) return a.c.ok ? -1 : 1;
      if (!!a.c.next !== !!b.c.next) return a.c.next ? -1 : 1;
      if (a.c.ok && b.c.ok) return compareLineQuality(a.c, b.c);
      return a.i - b.i;
    });
    const cleanup = () => {
      dlg.classList.add('hidden');
      $('#btnLineAuto').onclick = null;
      $('#btnLineCancel').onclick = null;
    };
    order.forEach((o) => {
      const c = o.c; const i = o.i;
      let badge = '失效'; let cls = 'bad';
      if (c._visited) { badge = '已访问'; }
      else if (currentUrl && c.url === currentUrl) { badge = '当前'; cls = 'cur'; }
      else if (c.ok && c.sites === bestSites && bestSites > 0) { badge = '推荐'; cls = 'best'; }
      else if (c.ok) { badge = '可用'; cls = 'ok'; }
      else if (c.next) { badge = '下级索引'; cls = 'next'; }
      const row = document.createElement('div');
      row.className = 'line-row' + (c.ok || c.next ? '' : ' disabled');
      row.innerHTML =
        '<div class="line-row-main"><span class="line-name">' + esc(c.name || shortHost(c.url)) + '</span>' +
        '<span class="line-badge ' + cls + '">' + badge + '</span></div>' +
        '<div class="line-row-sub"><span>站点 ' + (c.sites || 0) + '</span>' +
        '<span>直播源 ' + (c.goodLives || 0) + (c.livesTotal ? '/' + c.livesTotal : '') + '</span>' +
        '<span>' + (c.ms || 0) + 'ms</span>' +
        '<span class="line-url" title="' + esc(c.url) + '">' + esc(shortHost(c.url)) + '</span></div>';
      row.onclick = () => { cleanup(); resolve(i); };
      list.appendChild(row);
    });
    $('#btnLineAuto').onclick = () => { cleanup(); resolve('auto'); };
    $('#btnLineCancel').onclick = () => { cleanup(); resolve(null); };
    dlg.classList.remove('hidden');
  });
}
// 供「切换线路」复用：重新拉取原始订阅地址，弹窗让用户另选一条
async function switchLine() {
  const url = state.settings.subscriptionUrl;
  if (!url) { toast('当前订阅未记录源地址，请重新导入一次订阅'); return; }
  try {
    const r = await MS.httpGet(url, { 'User-Agent': 'okhttp/3.15' }, 25000);
    if (r.error || !r.body) throw new Error(r.error || '空响应');
    const root = JSON.parse(r.body);
    const trail = state.settings.lineTrail || [];
    const curUrl = trail.length ? trail[trail.length - 1].url : '';
    let cfg; let newTrail = [];
    if (!Array.isArray(root.sites) && (Array.isArray(root.storeHouse) || Array.isArray(root.urls))) {
      const res = await expandInteractive(url, root, (d) => showLineDialog(d.kind, d.candidates, curUrl));
      cfg = res.cfg; newTrail = res.trail;
    } else { cfg = root; }
    if (!Array.isArray(cfg.sites) || !cfg.sites.length) throw new Error('配置中没有 sites');
    await MS.saveSubscription(cfg);
    await saveSettings({ lineTrail: newTrail });
    state.site = null; state.typeMap = {}; state.catList = {}; state._catTid = {}; homeCache = {};
    liveCache = null; liveState.channels = []; liveState.cats = []; liveState.current = null;
    await loadConfig();
    setView('home');
    toast('线路已切换：' + cfg.sites.length + ' 个站点');
  } catch (e) {
    if (e && e.message === '已取消选线') return;
    toast('切换失败：' + (e && e.message || e));
  }
}
async function expandSubscription(url, rootCfg) {
  let cur = rootCfg;
  const visited = Object.create(null);
  if (url) visited[url] = 1;
  for (let depth = 0; depth < 5; depth++) {
    if (!cur || typeof cur !== 'object') break;
    if (Array.isArray(cur.sites) && cur.sites.length) return cur; // 末级站点配置
    if (Array.isArray(cur.storeHouse) && cur.storeHouse.length) {
      let advanced = false;
      for (const h of cur.storeHouse) {
        const u = h && (h.sourceUrl || h.url);
        if (!u || visited[u] || !/^https?:\/\//i.test(u)) continue;
        visited[u] = 1;
        const c = await fetchJsonCfg(u, 15000);
        if (c) { cur = c; advanced = true; break; }
      }
      if (!advanced) break;
      continue;
    }
    if (Array.isArray(cur.urls) && cur.urls.length) {
      cur = await pickBestLine(cur.urls);
      continue;
    }
    break; // 既无 sites 也无下一级索引
  }
  if (cur && Array.isArray(cur.sites) && cur.sites.length) return cur;
  throw new Error('无法从该配置展开出站点（sites）');
}

// ---- 导入订阅 ----
$('#btnImport').onclick = () => $('#importDialog').classList.remove('hidden');
$('#btnImportCancel').onclick = () => $('#importDialog').classList.add('hidden');
$('#btnImportOk').onclick = async () => {
  const url = $('#importUrl').value.trim(); const msg = $('#importMsg');
  if (!/^https?:\/\//i.test(url)) { msg.textContent = '请输入有效的 http(s) 地址'; return; }
  msg.textContent = '正在拉取配置…';
  try {
    const r = await MS.httpGet(url, { 'User-Agent': 'okhttp/3.15' }, 25000);
    if (r.error || !r.body) throw new Error(r.error || '空响应');
    let root;
    try { root = JSON.parse(r.body); } catch (e) { throw new Error('配置不是合法 JSON'); }
    // 影视仓多级索引（storeHouse / urls）：先探测各级候选，弹窗让用户自己选线路
    const isIndex = !Array.isArray(root.sites) && (Array.isArray(root.storeHouse) || Array.isArray(root.urls));
    let cfg; let trail = [];
    if (isIndex) {
      msg.textContent = '检测到多仓/多线路索引，正在探测各线路质量（约 10 秒）…';
      const res = await expandInteractive(url, root, (d) => showLineDialog(d.kind, d.candidates, null));
      cfg = res.cfg; trail = res.trail;
    } else {
      cfg = root;
    }
    if (!Array.isArray(cfg.sites) || !cfg.sites.length) throw new Error('配置中没有 sites');
    // 记住源地址与选线路径，供「切换线路」随时重选
    await saveSettings({ subscriptionUrl: url, lineTrail: trail });
    await MS.saveSubscription(cfg);
    // 重置站点选择，让新配置生效
    state.site = null; state.typeMap = {}; state.catList = {}; state._catTid = {}; homeCache = {};
    liveCache = null; liveState.channels = []; liveState.cats = []; liveState.current = null;
    await loadConfig();
    $('#importDialog').classList.add('hidden');
    $('#importUrl').value = '';
    setView('home');
    toast('已导入 ' + cfg.sites.length + ' 个站点');
  } catch (e) { msg.textContent = '导入失败：' + e.message; }
};

(async function init() {
  try { $('#version').textContent = 'v' + (await MS.appVersion()); } catch (e) {}

  // 先加载用户设置（主题等），保证首屏就是用户上次的主题
  try {
    state.settings = await MS.getSettings();
    applyTheme(state.settings.theme);
  } catch (e) {
    state.settings = {};
    applyTheme('dark');
  }

  // 设置加载完成后再套用到直播偏好（liveState 在模块期初始化，那时还没有设置）
  if (state.settings.liveTimeout) liveState.timeoutSec = state.settings.liveTimeout;
  if (state.settings.liveDecoder) liveState.decoder = state.settings.liveDecoder;
  if (state.settings.livePlayer) liveState.player = state.settings.livePlayer;

  bindPlayerControls();

  // 加载订阅：没有就是空壳（首次启动或已重置）
  try {
    await loadConfig();
    document.title = state.shellMode
      ? '影视舱 MediaShell'
      : '影视舱 MediaShell · ' + state.sites.length + '站';
  } catch (e) {
    state.shellMode = true;
    renderShell();
  }

  if (state.shellMode) {
    state.bootReady = true;
    return;   // 空壳不做任何网络请求
  }

  // 启动后立刻并发测速所有 CMS 站，把最快可用的站设为当前站。
  // 背景：实测默认站光速 api.guangsuapi.com 会 302 跳到博彩域名（已被安全拦截），
  // 虎牙/量子同样失效。不做这步的话用户打开应用先看到 8~25 秒的等待与错误页。
  if (state.settings.autoSite === false) { state.bootReady = true; return; }
  try {
    const list = await probeAllSites();
    console.log('[boot] 站点测速:', list.map((x) => x.site.name + '=' + x.ms + 'ms').join(', '));
    if (list.length) {
      const best = list[0].site;
      // 只有当前站不可用/明显更慢时才切换，避免打断用户正在浏览的内容
      const curUsable = list.find((x) => x.site.key === (state.site && state.site.key));
      console.log('[boot] 当前站=', state.site && state.site.name, '可用=', !!curUsable, '最快=', best.name, list[0].ms + 'ms');
      if (!curUsable || list[0].ms + 600 < curUsable.ms) {
        state.site = best;
        renderSites();
        if (state.view === 'home') renderHome();
        if (!curUsable) toast('已自动选择可用站点：' + best.name + '（' + list[0].ms + 'ms）');
      }
    }
  } catch (e) { console.log('[boot] 自动选站异常:', e && e.message); }
  state.bootReady = true;   // 启动测速完成标记（自检用）
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
  renderLiveTree: renderLiveTree,
  openDetail: openDetail,
  cmsGet: cmsGet,
  renderShell: renderShell,
  applyTheme: applyTheme,
  saveSettings: saveSettings,
  togglePlay: togglePlay,
  toggleFullscreen: toggleFullscreen,
  togglePiP: togglePiP,
  toggleDanmaku: toggleDanmaku,
  isDanmakuOnFor: isDanmakuOnFor,
  setDanmakuForSource: setDanmakuForSource,
  loadConfig: loadConfig,
  pickBestLine: pickBestLine,
  probeCandidates: probeCandidates,
  compareLineQuality: compareLineQuality,
  expandInteractive: expandInteractive,
  expandSubscription: expandSubscription,
  parseTVLines: parseTVLines,
  parseM3U: parseM3U,
  addHistory: addHistory,
  renderStore: renderStore,
  fmtTime: fmtTime,
};
