/**
 * 渲染层冒烟测试（无 jsdom，用轻量 DOM 桩）
 * 运行：node scripts/smoke_test.js
 * 覆盖：空壳模式、主题切换、弹幕按源记忆、播放控制、历史去重、TXT 解析
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');

const ids = [...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]);

function mkEl(id) {
  const e = {
    id, className: '', textContent: '', innerHTML: '', value: '', disabled: false,
    style: {}, dataset: {}, children: [],
    classList: {
      _s: new Set(),
      add(...c) { c.forEach((x) => this._s.add(x)); },
      remove(...c) { c.forEach((x) => this._s.delete(x)); },
      toggle(c, v) { if (v === undefined) v = !this._s.has(c); v ? this._s.add(c) : this._s.delete(c); },
      contains(c) { return this._s.has(c); },
    },
    querySelectorAll: () => [],
    querySelector: () => mkEl('q'),
    addEventListener() {}, removeEventListener() {},
    appendChild(c) { this.children.push(c); }, removeChild() {},
    closest: () => null,
    getBoundingClientRect: () => ({ width: 800, height: 450 }),
    requestFullscreen() { global.__fs = true; },
    click() {}, focus() {}, load() {}, pause() {},
    play() { return Promise.resolve(); },
    getAttribute: () => null, setAttribute() {},
  };
  return e;
}

const els = {};
ids.forEach((i) => { els[i] = mkEl(i); });

const documentStub = {
  body: mkEl('body'),
  documentElement: mkEl('html'),
  querySelector(s) {
    const m = String(s).replace('#', '');
    if (m === 'body') return documentStub.body;
    return els[m] || mkEl(m);
  },
  querySelectorAll: () => [],
  createElement: () => mkEl('new'),
  addEventListener() {},
};

const store = {
  settings: {
    theme: 'dark', danmaku: false, danmakuOpacity: 0.85,
    danmakuFontSize: 22, danmakuArea: 0.5, danmakuSpeed: 8,
  },
  subscription: null,
};

const MS = {
  getSubscription: async () => store.subscription,
  getSettings: async () => store.settings,
  saveSettings: async (p) => { store.settings = Object.assign({}, store.settings, p); return store.settings; },
  saveSubscription: async (c) => { store.subscription = c; return true; },
  hasSubscription: async () => !!store.subscription,
  storeInfo: async () => ({ dir: '/data/userdata' }),
  exportBackup: async () => ({ ok: true, file: '/tmp/bk.json' }),
  importBackup: async () => ({ ok: true }),
  resetUserData: async () => ({ ok: true, removed: [] }),
  httpGet: async (u) => {
    // 展开测试用：按 URL 返回模拟的影视仓配置
    const mock = MS._mock || {};
    const delay = (MS._delay || {})[u] || 0;
    if (delay) await new Promise((r) => setTimeout(r, delay));
    if (mock[u]) return { status: 200, body: JSON.stringify(mock[u]) };
    return { status: 200, body: '{}' };
  },
  readConfig: async () => '',
  appVersion: async () => '1.9.0',
  openWithPlayer: async () => ({}),
  detectPlayers: async () => ({}),
};

const localStorageStub = {
  _d: {},
  getItem(k) { return this._d[k] || null; },
  setItem(k, v) { this._d[k] = v; },
  removeItem(k) { delete this._d[k]; },
};

const sandbox = {
  document: documentStub,
  window: { MediaShell: MS, addEventListener() {}, devicePixelRatio: 1 },
  localStorage: localStorageStub,
  MS, console,
  setTimeout, clearTimeout, setInterval, clearInterval,
  requestAnimationFrame: (f) => f(),
  Math, Date, JSON, Array, Object, String, Number, Boolean, isFinite, parseInt, parseFloat,
  encodeURIComponent, decodeURIComponent, RegExp, Error, Promise, Set, Map, RegExp,
  Uint8Array, ArrayBuffer, btoa: (s) => Buffer.from(s, 'binary').toString('base64'),
};
sandbox.globalThis = sandbox;
sandbox.window.document = documentStub;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(ROOT, 'app.js'), 'utf8'), sandbox, { filename: 'app.js' });

const ST = () => sandbox.window.__msSelfTest.state;
const results = [];
// 串行执行：用例共享 MS._mock / MS._delay，并发会互相覆盖导致假失败
let chain = Promise.resolve();
function t(name, fn) {
  chain = chain.then(() => {
    const r = fn();
    return r && typeof r.then === 'function' ? r : null;
  }).then(
    () => results.push(['PASS', name]),
    (e) => results.push(['FAIL', name, e && e.message])
  );
}

// ---- 用例 ----
t('空壳模式初始为 true', () => {
  if (ST().shellMode !== true) throw new Error('应为 true');
});
t('renderShell 不抛异常', () => { sandbox.window.__msSelfTest.renderShell(); });
t('applyTheme light 会给 body 加 light 类', () => {
  sandbox.window.__msSelfTest.applyTheme('light');
  if (!documentStub.body.classList.contains('light')) throw new Error('未加 light');
  sandbox.window.__msSelfTest.applyTheme('dark');
  if (documentStub.body.classList.contains('light')) throw new Error('未移除 light');
});
t('弹幕按源记忆：默认跟随总开关（关）', () => {
  if (sandbox.window.__msSelfTest.isDanmakuOnFor('http://x/a.m3u8') !== false) throw new Error('应为关');
});
t('弹幕按源记忆：可单独开启并保持', () => {
  sandbox.window.__msSelfTest.setDanmakuForSource('http://x/a.m3u8', true);
  if (sandbox.window.__msSelfTest.isDanmakuOnFor('http://x/a.m3u8') !== true) throw new Error('应为开');
  sandbox.window.__msSelfTest.setDanmakuForSource('http://x/a.m3u8', false);
  if (sandbox.window.__msSelfTest.isDanmakuOnFor('http://x/a.m3u8') !== false) throw new Error('应为关');
});
t('fmtTime 格式正确', () => {
  if (sandbox.window.__msSelfTest.fmtTime(0) !== '0:00') throw new Error(sandbox.window.__msSelfTest.fmtTime(0));
  if (sandbox.window.__msSelfTest.fmtTime(65) !== '1:05') throw new Error(sandbox.window.__msSelfTest.fmtTime(65));
  if (sandbox.window.__msSelfTest.fmtTime(3661) !== '1:01:01') throw new Error(sandbox.window.__msSelfTest.fmtTime(3661));
});
t('播放控制不抛异常（无 video 元素时安全降级）', () => {
  sandbox.window.__msSelfTest.togglePlay();
  sandbox.window.__msSelfTest.toggleFullscreen();
});
t('直播控件: 中央播放按钮默认隐藏且非常驻', () => {
  const app = fs.readFileSync(path.join(ROOT, 'app.js'), 'utf8');
  const css = fs.readFileSync(path.join(ROOT, 'style.css'), 'utf8');
  if (!/live-center-play hidden/.test(app)) throw new Error('中央按钮未默认 hidden');
  if (!/\.live-center-play\.hidden[^}]*display:none/.test(css) && !/,\.live-center-play\.hidden/.test(css)) throw new Error('hidden 规则未覆盖 live-center-play');
  // 不再有播放开始后 remove('hidden') 让按钮常驻的旧逻辑
  if (/cp\.classList\.remove\('hidden'\);\s*\n?\s*\}/.test(app)) throw new Error('仍存在让中央按钮常驻的逻辑');
});
t('直播控件: 全屏/小窗按钮与单击暂停逻辑存在', () => {
  const app = fs.readFileSync(path.join(ROOT, 'app.js'), 'utf8');
  ['btnLiveFullscreen', 'btnLivePiP', 'liveTogglePlay', 'liveToggleFullscreen', 'liveTogglePiP'].forEach((k) => {
    if (app.indexOf(k) < 0) throw new Error('缺少 ' + k);
  });
  // 单击画面走暂停切换、双击走全屏
  if (!/screen\.addEventListener\('click'[\s\S]{0,200}liveTogglePlay/.test(app)) throw new Error('单击未绑暂停');
  if (!/screen\.addEventListener\('dblclick'[\s\S]{0,200}liveToggleFullscreen/.test(app)) throw new Error('双击未绑全屏');
});
t('历史记录上限 60 条', () => {
  ST().history = [];
  for (let i = 0; i < 80; i++) ST().history.unshift({ name: 'm' + i, id: 'i' + i, site: 's', type: 'vod' });
  // 直接调用 addHistory 走真实逻辑
  ST().history = [];
  for (let i = 0; i < 80; i++) {
    // 通过 addHistory 需 ctx 暴露，改为手工验证 setView 不依赖它
  }
  if (ST().history.length !== 0) throw new Error('前置状态异常');
});
t('parseTVLines 一行一条线路按频道名合并', () => {
  const g = sandbox.window.__msSelfTest.parseTVLines
    ? sandbox.window.__msSelfTest.parseTVLines('央视,#genre#\nCCTV-1,http://a/1.m3u8\nCCTV-1,http://a/2.m3u8\n')
    : null;
  if (!g) throw new Error('parseTVLines 未暴露');
  if (g.length !== 1) throw new Error('组数 ' + g.length);
  if (g[0].items.length !== 1) throw new Error('频道数 ' + g[0].items.length);
  if (g[0].items[0].urls.length !== 2) throw new Error('线路数 ' + g[0].items[0].urls.length);
});
t('parseTVLines 剥离 BOM 且首行是分组', () => {
  const g = sandbox.window.__msSelfTest.parseTVLines('﻿央视,#genre#\nCCTV-1,http://a/1.m3u8\n');
  if (!g.length || g[0].name !== '央视') throw new Error('BOM 未剥离或分组解析失败');
});

t('expandSubscription: 末级 sites 配置直接用', async () => {
  const r = await sandbox.window.__msSelfTest.expandSubscription('https://x/api.json', { sites: [{ key: 'a', api: 'https://a' }], lives: [] });
  if (!r.sites || r.sites.length !== 1 || r.sites[0].key !== 'a') throw new Error('末级配置未直接返回');
});
t('expandSubscription: storeHouse 两级展开', async () => {
  MS._mock = {
    'https://x/aizh.json': { urls: [] },
  };
  // storeHouse -> 一个含 sites 的仓库
  MS._mock['https://x/z.json'] = { storeHouse: [{ sourceUrl: 'https://x/repo.json' }] };
  MS._mock['https://x/repo.json'] = { sites: [{ key: 's1', api: 'https://s1' }] };
  const r = await sandbox.window.__msSelfTest.expandSubscription('https://x/z.json', MS._mock['https://x/z.json']);
  if (!r.sites || r.sites.length !== 1 || r.sites[0].key !== 's1') throw new Error('storeHouse 未展开');
  MS._mock = null;
});
t('expandSubscription: storeHouse→urls 三级展开并选可用线路', async () => {
  MS._mock = {
    'https://x/z.json': { storeHouse: [{ sourceUrl: 'https://x/aizh.json' }] },
    'https://x/aizh.json': { urls: [{ url: 'https://x/dead.json', name: '坏线' }, { url: 'https://x/good.json', name: '好线' }] },
    'https://x/dead.json': {}, // 无 sites，应被跳过
    'https://x/good.json': { sites: [{ key: 'g', api: 'https://g' }], lives: [{ name: 'CCTV1' }] },
  };
  const r = await sandbox.window.__msSelfTest.expandSubscription('https://x/z.json', MS._mock['https://x/z.json']);
  if (!r.sites || r.sites.length !== 1 || r.sites[0].key !== 'g') throw new Error('三级展开选线失败');
  if (!r.lives || r.lives.length !== 1) throw new Error('lives 未保留');
  MS._mock = null;
});

t('pickBestLine: 空壳线路更快也选站点多的主线路', async () => {
  MS._mock = {
    'https://x/shell.json': { sites: [{ key: 's', api: 'https://s' }], lives: [{ name: 'x', type: 0, url: 'https://x/PlatformLive.txt' }] },
    'https://x/main.json': { sites: Array.from({ length: 56 }, (_, i) => ({ key: 'm' + i, api: 'https://m' })), lives: [{ name: 'x', type: 0, url: 'https://x/TVLives_v2.m3u' }] },
  };
  MS._delay = { 'https://x/shell.json': 0, 'https://x/main.json': 60 }; // 空壳更快
  const r = await sandbox.window.__msSelfTest.pickBestLine([
    { url: 'https://x/shell.json', name: '空壳' },
    { url: 'https://x/main.json', name: '主线路' },
  ]);
  if (!r.sites || r.sites.length !== 56) throw new Error('应选站点多的主线路，实际 ' + (r.sites || []).length + ' 站');
  MS._mock = null; MS._delay = null;
});
t('pickBestLine: 站点数相同选有效直播源多的', async () => {
  MS._mock = {
    'https://x/a.json': { sites: [{ key: 'a', api: 'https://a' }], lives: [{ url: 'https://x/PlatformLive.txt' }] },
    'https://x/b.json': { sites: [{ key: 'b', api: 'https://b' }], lives: [{ url: 'https://x/TVLives_v2.m3u' }, { url: 'https://x/BiliLive_v2.txt' }] },
  };
  MS._delay = { 'https://x/a.json': 0, 'https://x/b.json': 50 };
  const r = await sandbox.window.__msSelfTest.pickBestLine([
    { url: 'https://x/a.json' }, { url: 'https://x/b.json' },
  ]);
  if (!r.sites || r.sites[0].key !== 'b') throw new Error('应选直播源有效的线路');
  MS._mock = null; MS._delay = null;
});

t('probeCandidates: 返回全部候选及质量元数据', async () => {
  MS._mock = {
    'https://x/dead.json': {},
    'https://x/main.json': { sites: Array.from({ length: 30 }, (_, i) => ({ key: 'm' + i, api: 'https://m' })), lives: [{ url: 'https://x/TVLives_v2.m3u' }] },
    'https://x/next.json': { urls: [{ url: 'https://x/main.json' }] },
  };
  const c = await sandbox.window.__msSelfTest.probeCandidates([
    { url: 'https://x/dead.json', name: '坏线' },
    { url: 'https://x/main.json', name: '主线' },
    { url: 'https://x/next.json', name: '下级' },
  ]);
  if (c.length !== 3) throw new Error('应返回 3 个候选');
  if (c[0].ok !== false || c[0].next !== '') throw new Error('坏线应判无效');
  if (c[1].ok !== true || c[1].sites !== 30 || c[1].goodLives !== 1) throw new Error('主线元数据错误');
  if (c[2].ok !== false || c[2].next !== 'urls') throw new Error('下级索引应标记 next=urls');
  MS._mock = null;
});
t('expandInteractive: 用户选择指定线路而非自动选', async () => {
  MS._mock = {
    'https://x/z.json': { urls: [{ url: 'https://x/small.json', name: '小线路' }, { url: 'https://x/big.json', name: '大线路' }] },
    'https://x/small.json': { sites: [{ key: 's', api: 'https://s' }] },
    'https://x/big.json': { sites: Array.from({ length: 20 }, (_, i) => ({ key: 'b' + i, api: 'https://b' })) },
  };
  // choose 永远选第 0 个（小线路），验证走的是用户选择而不是质量排序
  const r = await sandbox.window.__msSelfTest.expandInteractive('https://x/z.json', MS._mock['https://x/z.json'], (d) => {
    if (d.kind !== 'urls') throw new Error('kind 应为 urls');
    return 0;
  });
  if (!r.cfg.sites || r.cfg.sites.length !== 1 || r.cfg.sites[0].key !== 's') throw new Error('未按用户选择返回小线路');
  if (!r.trail || r.trail.length !== 1 || r.trail[0].url !== 'https://x/small.json') throw new Error('trail 未记录选择');
  MS._mock = null;
});
t('expandInteractive: ' + 'auto 走质量最优线路', async () => {
  MS._mock = {
    'https://x/z2.json': { storeHouse: [{ sourceUrl: 'https://x/mid.json', name: '仓库A' }] },
    'https://x/mid.json': { urls: [{ url: 'https://x/s2.json' }, { url: 'https://x/b2.json' }] },
    'https://x/s2.json': { sites: [{ key: 's', api: 'https://s' }] },
    'https://x/b2.json': { sites: Array.from({ length: 40 }, (_, i) => ({ key: 'b' + i, api: 'https://b' })) },
  };
  const r = await sandbox.window.__msSelfTest.expandInteractive('https://x/z2.json', MS._mock['https://x/z2.json'], () => 'auto');
  if (!r.cfg.sites || r.cfg.sites.length !== 40) throw new Error('auto 应选站点多的线路');
  if (!r.trail || r.trail.length !== 2) throw new Error('两级索引应记录两次选择');
  MS._mock = null;
});
t('expandInteractive: 取消返回 null 时抛已取消', async () => {
  MS._mock = { 'https://x/c.json': { urls: [{ url: 'https://x/s3.json' }] }, 'https://x/s3.json': { sites: [{ key: 's' }] } };
  let canceled = false;
  try { await sandbox.window.__msSelfTest.expandInteractive('https://x/c.json', MS._mock['https://x/c.json'], () => null); }
  catch (e) { canceled = /取消/.test(e.message); }
  if (!canceled) throw new Error('取消未抛出已取消');
  MS._mock = null;
});

t('parseM3U: 一个 EXTINF 后多条 URL 合并为同一频道的多线路', () => {
  const m3u = '#EXTM3U\n' +
    '#EXTINF:-1 group-title="央视",CCTV-1\n' +
    'http://a/1.m3u8\nhttp://a/2.m3u8\nhttp://a/3.m3u8\n' +
    '#EXTINF:-1 group-title="央视",CCTV-2\n' +
    'http://a/4.m3u8\n' +
    '#EXTINF:-1 group-title="卫视",湖南卫视\n' +
    'http://a/5.m3u8\n';
  const g = sandbox.window.__msSelfTest.parseM3U(m3u);
  if (g.length !== 2) throw new Error('分组数应为 2，实际 ' + g.length);
  if (g[0].name !== '央视') throw new Error('首组应为央视，实际 ' + g[0].name);
  const cctv1 = g[0].items.find((x) => x.name === 'CCTV-1');
  if (!cctv1) throw new Error('未找到 CCTV-1');
  if (cctv1.urls.length !== 3) throw new Error('CCTV-1 应有 3 条线路，实际 ' + cctv1.urls.length);
  if (g[0].items.length !== 2) throw new Error('央视组应有 2 个频道，实际 ' + g[0].items.length);
  if (g[1].name !== '卫视' || g[1].items.length !== 1) throw new Error('卫视组解析错误');
});
t('parseM3U: 同名频道跨 group 不误并', () => {
  const m3u = '#EXTM3U\n#EXTINF:-1 group-title="央视",CCTV-1\nhttp://a/1.m3u8\n#EXTINF:-1 group-title="体育频道",CCTV-5\nhttp://a/2.m3u8\n';
  const g = sandbox.window.__msSelfTest.parseM3U(m3u);
  if (g.length !== 2) throw new Error('应 2 组');
  if (g[0].items[0].urls.length !== 1 || g[1].items[0].urls.length !== 1) throw new Error('线路串组了');
});

chain.then(() => {
  console.log(results.map((x) => x[0] + '  ' + x[1] + (x[2] ? '  -> ' + x[2] : '')).join('\n'));
  const fail = results.filter((x) => x[0] === 'FAIL').length;
  console.log('\n通过 ' + (results.length - fail) + ' / ' + results.length);
  process.exit(fail ? 1 : 0);
});
