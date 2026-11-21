'use strict';
// 启动诊断（仅自检/排障时启用，不影响正常功能）
try {
  if (process.env.MSHELL_SELFTEST === '1' || process.argv.join(' ').indexOf('selftest') >= 0) {
    require('fs').writeFileSync(
      (process.env.MSHELL_DATA || 'D:/') .replace(/[\\/]+$/, '') + '/_ms_diag.txt',
      'argv=' + JSON.stringify(process.argv) + '\nenv.SELFTEST=' + process.env.MSHELL_SELFTEST + '\n',
      'utf8');
  }
} catch (e) {}
const { app, BrowserWindow, ipcMain, shell, dialog, session, Menu } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const https = require('https');
const { spawn } = require('child_process');
const { URL } = require('url');
const zlib = require('zlib');

// ---- 直播播放性能优化：开启 Chromium 硬件解码/GPU 合成 -------------------
// 手机端直播不卡而电脑卡，多因 Electron 默认未开启硬解、HLS 走 JS 软解。
for (const sw of [
  'enable-gpu', 'enable-gpu-rasterization', 'enable-zero-copy',
  'ignore-gpu-blocklist', 'enable-accelerated-video-decode',
]) { try { app.commandLine.appendSwitch(sw); } catch (e) {} }
try {
  app.commandLine.appendSwitch(
    'enable-features',
    'CanvasOopRasterization,PlatformHEVCDecoderSupport,UseSkiaRenderer'
  );
} catch (e) {}

const APP_DIR = __dirname;
// 持久化数据目录：单文件 EXE 每次解压到临时目录，因此允许用 MSHELL_DATA 环境变量固定到 D 盘；
// 目录版则默认用 APP_DIR 上两级的 userdata。绝不写 %APPDATA%(C 盘)。
const DATA_DIR = process.env.MSHELL_DATA || path.join(APP_DIR, '..', '..', 'userdata');
const CONFIG_DIR = path.join(APP_DIR, 'config');

try { fs.mkdirSync(DATA_DIR, { recursive: true }); } catch (e) {}
app.setPath('userData', DATA_DIR);

// ---- 内置自检：electron.exe --selftest -------------------------------------
// 在主进程内直接复现「首页取数」与「直播目录构建」两条链路，输出真实耗时与可用性。
// 结果写入 <DATA_DIR>/selftest.json，便于自动化回归。
async function runSelfTest() {
  const out = { startedAt: new Date().toISOString(), proxy: {}, home: [], live: {} };
  const write = () => {
    try { fs.writeFileSync(path.join(DATA_DIR, 'selftest.json'), JSON.stringify(out, null, 2), 'utf8'); } catch (e) {}
  };
  try {
    const cfg = JSON.parse(fs.readFileSync(path.join(CONFIG_DIR, 'YSCSites.json'), 'utf8'));
    const sites = (cfg.sites || []).filter((s) => /^https?:\/\//i.test(String(s.api || '')));

    // 1) 首页：复现 loadHomeData 的两步（先列表、分类并发补齐）
    // 并发跑，最多 6 个站点，避免个别坏站拖住整体
    const homeProbe = async (s) => {
      const base = String(s.api).replace(/[?&]$/, '');
      const q = (p) => base + (base.indexOf('?') >= 0 ? '&' : '?') + p;
      const t0 = Date.now();
      let listOk = false, nList = 0;
      try {
        const r = await httpGet(q('ac=videolist&pg=1'), { 'User-Agent': 'okhttp/3.15' }, 12000);
        if (r && r.status) { listOk = true; try { nList = (JSON.parse(r.body).list || []).length; } catch (e) {} }
      } catch (e) {}
      const tList = Date.now() - t0;
      const t1 = Date.now();
      let clsOk = false, nCls = 0;
      try {
        const r = await httpGet(q('ac=list'), { 'User-Agent': 'okhttp/3.15' }, 7000);
        if (r && r.status) { clsOk = true; try { nCls = (JSON.parse(r.body).class || []).length; } catch (e) {} }
      } catch (e) {}
      return {
        site: s.name, tListMs: tList, tClsMs: Date.now() - t1,
        listOk, clsOk, nList, nCls, totalMs: Date.now() - t0,
      };
    };
    const probeTargets = sites.slice(0, 8);
    const settled = await Promise.all(probeTargets.map((s) => homeProbe(s).catch(() => null)));
    settled.filter(Boolean).forEach((h) => out.home.push(h));
    write();

    // 2) 直播目录：解析本地源文件，统计频道与线路
    try {
      const parseTV = (text) => {
        const groups = []; let cur = null;
        text.split(/\r?\n/).forEach((line) => {
          line = line.trim(); if (!line) return;
          if (/#genre#\s*$/.test(line)) { cur = { name: line.replace(/,#genre#\s*$/, '').trim(), items: [] }; groups.push(cur); return; }
          const i = line.indexOf(',');
          if (i > 0 && cur) {
            const name = line.slice(0, i).trim();
            const urls = line.slice(i + 1).split(',').map((u) => u.trim()).filter((u) => /^https?:\/\//i.test(u));
            if (name && urls.length) cur.items.push({ name, urls });
          }
        });
        return groups.filter((g) => g.items.length);
      };
      const byName = new Map(); const cats = [];
      ['TVLives.txt', 'PlatformLive.txt', 'BiliLive.txt'].forEach((fn) => {
        let text = '';
        try { text = fs.readFileSync(path.join(CONFIG_DIR, fn), 'utf8'); } catch (e) {}
        parseTV(text).forEach((g) => {
          const cat = { source: fn, name: g.name, n: 0 };
          g.items.forEach((it) => {
            const key = it.name.toUpperCase().replace(/[\s\-_—]/g, '').replace(/(高清|超清|蓝光|HD|4K|1080P|720P)$/i, '').trim();
            if (!key) return;
            let ch = byName.get(key);
            if (!ch) { ch = { name: it.name, urls: [] }; byName.set(key, ch); }
            it.urls.forEach((u) => { if (ch.urls.indexOf(u) < 0) ch.urls.push(u); });
            cat.n++;
          });
          if (cat.n) cats.push(cat);
        });
      });
      out.live = {
        channels: byName.size,
        urls: Array.from(byName.values()).reduce((a, c) => a + c.urls.length, 0),
        multiLine: Array.from(byName.values()).filter((c) => c.urls.length > 1).length,
        cats: cats,
      };
    } catch (e) { out.live = { error: String(e && e.message || e) }; }

    // 3) 代理可用性：挑几个源实测走代理
    try {
      const samples = [];
      const files = ['TVLives.txt', 'PlatformLive.txt'];
      files.forEach((fn) => {
        let text = '';
        try { text = fs.readFileSync(path.join(CONFIG_DIR, fn), 'utf8'); } catch (e) {}
        text.split(/\r?\n/).forEach((line) => {
          const i = line.indexOf(',');
          if (i > 0) line.slice(i + 1).split(',').forEach((u) => { u = u.trim(); if (/^https?:/i.test(u)) samples.push(u); });
        });
      });
      const pick = [];
      const seen = new Set();
      samples.forEach((u) => {
        const m = u.match(/^https?:\/\/([^/:]+)/);
        const d = m ? m[1] : '?';
        if (!seen.has(d)) { seen.add(d); pick.push(u); }
      });
      const test = pick.slice(0, 6);
      out.proxy.samples = [];
      for (const u of test) {
        const r = await new Promise((resolve) => {
          const req = http.get('http://127.0.0.1:' + PROXY_PORT + '/s?u=' + encodeTarget(u), (resp) => {
            let body = '';
            resp.on('data', (c) => { if (body.length < 3000) body += c; });
            resp.on('end', () => resolve({ status: resp.statusCode, isM3U8: /#EXTM3U/.test(body) }));
          });
          req.on('error', (e) => resolve({ status: 0, error: String(e.message) }));
          req.setTimeout(15000, () => { req.destroy(); resolve({ status: 0, error: 'timeout' }); });
        });
        out.proxy.samples.push({ url: u.slice(0, 70), ...r });
        write();
      }
      out.proxy.ok = out.proxy.samples.filter((s) => s.status === 200 && s.isM3U8).length;
      out.proxy.total = out.proxy.samples.length;
    } catch (e) { out.proxy = { error: String(e && e.message || e) }; }

    out.finishedAt = new Date().toISOString();
    write();
    app.exit(0);
  } catch (e) {
    out.error = String(e && e.message || e);
    write();
    app.exit(1);
  }
}

let win = null;

function createWindow() {
  try{require('fs').appendFileSync('g:/Model/WorkBuddy/AI编程助手/MyTV_work/MediaShellApp/selftest.log','MARK_CREATEWIN '+new Date().toISOString()+'\n');}catch(e){}

  win = new BrowserWindow({
    width: 1360,
    height: 860,
    minWidth: 980,
    minHeight: 640,
    title: '影视舱 MediaShell',
    backgroundColor: '#0d0f14',
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      webSecurity: false,
      allowRunningInsecureContent: true,
      preload: path.join(APP_DIR, 'preload.js'),
    },
  });
  Menu.setApplicationMenu(null);
  win.loadFile(path.join(APP_DIR, 'index.html'));
  win.once('ready-to-show', () => {
    try{require('fs').appendFileSync('g:/Model/WorkBuddy/AI编程助手/MyTV_work/MediaShellApp/selftest.log','MARK_READYTOSHOW '+new Date().toISOString()+'\n');}catch(e){}

    win.show();
    win.focus();
  });
  win.on('closed', () => { win = null; });

  // 自动化自检模式：MSHELL_SELFTEST=1 时，渲染进程把关键耗时写入 userdata/selftest.json
  if (process.env.MSHELL_SELFTEST === '1') {
    const logPath = path.join(DATA_DIR, 'selftest-ui.json');
    const stLog = (m) => {
      try { fs.appendFileSync(path.join(DATA_DIR, 'selftest.log'), '[ST] ' + m + '\n'); } catch (e) {}
    };
    const writeSelfTest = (data) => {
      try { fs.writeFileSync(logPath, JSON.stringify(data, null, 2), 'utf8'); } catch (e) {}
    };
    stLog('selftest mode on, DATA_DIR=' + DATA_DIR);
    win.webContents.on('did-finish-load', () => {
      stLog('did-finish-load');
      // 等首页首屏渲染
      setTimeout(async () => {
        stLog('start probing');
        const out = { startedAt: new Date().toISOString(), home: {}, live: {} };
        try {
          out.home = await win.webContents.executeJavaScript(`(async () => {
            const T = window.__msSelfTest;
            if (!T) return { error: 'no hook' };
            const t0 = performance.now();
            const site = T.state.sites.find(s => T.isCMS(s));
            T.state.site = site; T.renderSites(); T.renderHome();
            await new Promise(res => {
              const iv = setInterval(() => {
                if (document.querySelectorAll('#tvRows .poster').length > 0) { clearInterval(iv); res(); }
              }, 80);
              setTimeout(() => { clearInterval(iv); res(); }, 25000);
            });
            const tPosters = performance.now() - t0;
            const catCount = document.querySelectorAll('#catBar .cat-pill:not(.skel-pill)').length;
            const posterCount = document.querySelectorAll('#tvRows .poster').length;
            const catBarText = document.querySelector('#catBar') ? document.querySelector('#catBar').innerText.slice(0, 200) : '';
            const banner = document.querySelector('#banner .btitle');
            return { site: site && site.name, tPosters: Math.round(tPosters), posterCount, catCount,
                     catBarText, bannerTitle: banner ? banner.textContent.slice(0,40) : '' };
          })()`, true);
          stLog('home done: ' + JSON.stringify(out.home).slice(0, 200));
        } catch (e) { out.home = { error: String(e && e.message || e) }; stLog('home err: ' + out.home.error); }
        try {
          out.live = await win.webContents.executeJavaScript(`(async () => {
            const T = window.__msSelfTest;
            if (!T) return { error: 'no hook' };
            const t0 = performance.now();
            T.setView('live');
            await new Promise(res => {
              const iv = setInterval(() => {
                if (T.liveState.channels && T.liveState.channels.length) { clearInterval(iv); res(); }
              }, 100);
              setTimeout(() => { clearInterval(iv); res(); }, 40000);
            });
            const t = performance.now() - t0;
            const cats = T.liveState.cats.map(c => ({ name: c.name, n: c.channelIds.length }));
            const cache = T.getLiveCache() || {};
            const srcDetail = {};
            Object.keys(cache).forEach(k => { srcDetail[k] = (cache[k]||[]).reduce((a,g)=>a+(g.items||[]).length,0); });
            const cfgTest = {};
            for (const f of ['TVLives.txt','PlatformLive.txt','BiliLive.txt']) {
              try { const tt = await window.MediaShell.readConfig(f); cfgTest[f] = 'OK:' + tt.length; }
              catch (e) { cfgTest[f] = 'ERR:' + (e && e.message || e); }
            }
            return { channels: T.liveState.channels.length, cats: cats.length, tMs: Math.round(t),
                     sources: Object.keys(cache), srcDetail, cfgTest, catList: cats.slice(0, 14) };
          })()`, true);
          stLog('live done: ' + JSON.stringify(out.live).slice(0, 400));
        } catch (e) { out.live = { error: String(e && e.message || e) }; stLog('live err: ' + out.live.error); }
        out.finishedAt = new Date().toISOString();
        writeSelfTest(out);
        stLog('written selftest.json');
        app.quit();
      }, 3000);
    });
  }
}

try{require('fs').appendFileSync('g:/Model/WorkBuddy/AI编程助手/MyTV_work/MediaShellApp/selftest.log','MARK_WHENREADY '+new Date().toISOString()+'\n');}catch(e){}
app.whenReady().then(() => {
  // Disable the default User-Agent reveal where not needed
  startProxy();
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });

// ---- Safe local file reader (config only) --------------------------------
const SAFE_FILES = new Set([
  'YSCSites.json', 'TVBoxDesktop.json', 'aizheteng.json', 'zheteng.json',
  'TVLives.txt', 'PlatformLive.txt', 'BiliLive.txt',
]);
ipcMain.handle('read-config', async (_e, name) => {
  if (!SAFE_FILES.has(name)) throw new Error('blocked file: ' + name);
  const p = path.join(CONFIG_DIR, name);
  return fs.readFileSync(p, 'utf8');
});
ipcMain.handle('list-configs', async () => Array.from(SAFE_FILES));

// ---- HTTP proxy: renderer cannot do cross-origin CMS requests -------------
// 修复要点：
//  1) req.setTimeout 在收到响应头后仍会继续计时，部分服务器（Cloudflare 等）保持
//     keep-alive 不关闭连接，超时会把「已成功返回」的请求误杀 → 表现为接口偶发失败。
//     改为：收到响应头即清除超时，仅在「尚未收到响应头」阶段才算超时。
//  2) 跟随重定向时保留同一个 deadline，避免链式请求无限延长。
//  3) 加上 gzip 解压与浏览器 UA，减小传输量并绕过部分站点的 UA 拦截。
const DEFAULT_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';

function httpGet(rawUrl, headers, timeout, deadline, depth) {
  return new Promise((resolve, reject) => {
    let url;
    try { url = new URL(rawUrl); } catch (e) { return reject(e); }
    const mod = url.protocol === 'https:' ? https : http;
    deadline = deadline || Date.now() + (timeout || 15000);
    depth = depth || 0;
    const left = deadline - Date.now();
    if (left <= 0) return reject(new Error('timeout'));
    const opts = {
      method: 'GET',
      hostname: url.hostname,
      port: url.port || undefined,
      path: url.pathname + url.search,
      headers: Object.assign({
        'User-Agent': DEFAULT_UA,
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'close',
      }, headers || {}),
    };
    let gotHeaders = false;
    const req = mod.request(opts, (res) => {
      gotHeaders = true;
      req.setTimeout(0);           // 已收到响应头，取消 socket 空闲超时
      // follow redirects (max 5)
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location && depth < 5) {
        res.resume();
        let next;
        try { next = new URL(res.headers.location, rawUrl).href; }
        catch (e) { return reject(e); }
        return httpGet(next, headers, timeout, deadline, depth + 1).then(resolve, reject);
      }
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        let buf = Buffer.concat(chunks);
        const enc = String(res.headers['content-encoding'] || '');
        if (/gzip/i.test(enc)) { try { buf = zlib.gunzipSync(buf); } catch (e) {} }
        else if (/deflate/i.test(enc)) { try { buf = zlib.inflateSync(buf); } catch (e) {} }
        let body;
        const ct = String(res.headers['content-type'] || '');
        if (/gb2312|gbk/i.test(ct)) {
          try { body = new TextDecoder('gbk').decode(buf); } catch (e) { body = buf.toString('utf8'); }
        } else {
          body = buf.toString('utf8');
        }
        resolve({ status: res.statusCode, body, headers: res.headers, bytes: buf.length });
      });
      res.on('error', reject);
    });
    req.setTimeout(left, () => {
      if (!gotHeaders) req.destroy(new Error('timeout'));
    });
    req.on('error', reject);
    req.end();
  });
}
ipcMain.handle('http-get', async (_e, url, headers, timeout) => {
  // 部分采集站首包会挂起（实测虎牙/量子/短剧点播），重试一次即可成功。
  // 这里做「快速重试」，把偶发超时从 15s 压到 2~3s，大幅改善首页体感。
  const t0 = Date.now();
  let lastErr = null;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const r = await httpGet(url, headers, timeout);
      if (r && r.status) return r;
      lastErr = new Error(r && r.error || '空响应');
    } catch (err) { lastErr = err; }
    if (attempt === 0) await new Promise((r) => setTimeout(r, 350));
  }
  return { status: 0, body: '', error: String(lastErr && lastErr.message || lastErr), elapsed: Date.now() - t0 };
});

// ---- Open links / external players ---------------------------------------
ipcMain.handle('open-external', async (_e, url) => {
  if (!/^https?:\/\//i.test(url)) return false;
  await shell.openExternal(url);
  return true;
});
// Write a short .m3u next to the app and open it with the system player.
ipcMain.handle('open-with-player', async (_e, streamUrl, title) => {
  const safe = String(title || 'stream').replace(/[\\/:*?"<>|]/g, '_').slice(0, 60);
  const file = path.join(DATA_DIR, safe + '.m3u8');
  fs.writeFileSync(file, '#EXTM3U\n#EXTINF:-1,' + safe + '\n' + streamUrl + '\n', 'utf8');
  try { await shell.openPath(file); return file; }
  catch (e) { return { error: String(e) }; }
});

// ---- Playlist import: user can drop a subscription URL --------------------
ipcMain.handle('save-config', async (_e, name, content) => {
  if (!SAFE_FILES.has(name)) throw new Error('blocked file: ' + name);
  const p = path.join(CONFIG_DIR, name);
  fs.writeFileSync(p, content, 'utf8');
  return true;
});

// ---- lightweight external players (mpv / VLC / PotPlayer) ------------------
// 浏览器内 HLS 软解在电脑上很卡；调用轻量硬件解码播放器体验接近手机端。
const PLAYER_CANDIDATES = {
  mpv: [
    'C:\\Program Files\\mpv\\mpv.exe',
    'C:\\Program Files (x86)\\mpv\\mpv.exe',
    path.join(DATA_DIR, 'players', 'mpv.exe'),
  ],
  vlc: [
    'C:\\Program Files\\VideoLAN\\VLC\\vlc.exe',
    'C:\\Program Files (x86)\\VideoLAN\\VLC\\vlc.exe',
  ],
  potplayer: [
    'C:\\Program Files\\DAUM\\PotPlayer\\PotPlayerMini64.exe',
    'C:\\Program Files\\DAUM\\PotPlayer\\PotPlayerMini.exe',
    'C:\\Program Files (x86)\\DAUM\\PotPlayer\\PotPlayerMini.exe',
  ],
};
ipcMain.handle('detect-players', async () => {
  const found = {};
  for (const [key, paths] of Object.entries(PLAYER_CANDIDATES)) {
    found[key] = paths.find((p) => { try { return fs.existsSync(p); } catch (e) { return false; } }) || null;
  }
  return found;
});
// 用外部播放器播放：解码方式用参数指定（硬解优先），超时由播放器自身处理
ipcMain.handle('play-external', async (_e, playerKey, url, decodeMode) => {
  let exe = (PLAYER_CANDIDATES[playerKey] || []).find((p) => { try { return fs.existsSync(p); } catch (e) { return false; } });
  if (!exe) return { error: '未找到播放器：' + playerKey };
  let args;
  if (playerKey === 'mpv') {
    args = ['--hwdec=' + (decodeMode === 'software' ? 'no' : 'auto-safe'),
      '--vo=gpu', '--cache-secs=8', '--profile=fast', url];
  } else if (playerKey === 'vlc') {
    args = ['--avcodec-hw=' + (decodeMode === 'software' ? 'none' : 'any'), url];
  } else {
    args = [url];
  }
  try {
    const child = spawn(exe, args, { detached: true, stdio: 'ignore' });
    child.unref();
    return { ok: true, exe };
  } catch (err) { return { error: String(err && err.message || err) }; }
});

// ---- version --------------------------------------------------------------
ipcMain.handle('app-version', async () => app.getVersion());

// ---- Stream proxy: bypass CORS for IPTV / HLS ------------------------------
// 根因：绝大多数 IPTV 源不返回 Access-Control-Allow-Origin，Chromium 渲染进程
// 直接 XHR 拉 m3u8/分片会被 CORS 拦截 → 表现为“直播列表匹配不到资源”。
// 方案：主进程起一个本地 HTTP 代理，渲染进程把流地址换成代理地址。
// 主进程用 Node http 请求，不受同源策略限制；m3u8 清单里的分片路径自动重写为代理地址。
const PROXY_PORT = 19871;
let proxyServer = null;

// 记录每个代理地址的“原始基址”，用于重写 m3u8 内的相对路径
function encodeTarget(u) { return Buffer.from(String(u), 'utf8').toString('base64url'); }
function decodeTarget(u) {
  try { return Buffer.from(String(u), 'base64url').toString('utf8'); }
  catch (e) { return ''; }
}

// 重写 m3u8 内容：把所有非注释行（分片/子清单 URL）换成代理地址
function rewriteM3U8(text, baseUrl) {
  const lines = text.split(/\r?\n/);
  const out = lines.map((ln) => {
    const t = ln.trim();
    if (!t) return ln;
    if (t.charAt(0) === '#') return ln;
    let abs;
    try { abs = new URL(t, baseUrl).href; } catch (e) { return ln; }
    if (!/^https?:/i.test(abs)) return ln;
    return 'http://127.0.0.1:' + PROXY_PORT + '/s?u=' + encodeTarget(abs);
  });
  return out.join('\n');
}

function proxyFetch(targetUrl, reqHeaders, res, attempt) {
  attempt = attempt || 0;
  let u;
  try { u = new URL(targetUrl); } catch (e) { res.writeHead(400); res.end('bad url'); return; }
  const mod = u.protocol === 'https:' ? https : http;
  const headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'close',
  };
  // 透传 Range（分片拖拽/断点续播）
  if (reqHeaders.range) headers.Range = reqHeaders.range;
  // Referer 用源站同域，部分源做防盗链校验
  headers.Referer = u.protocol + '//' + u.host + '/';

  const opts = {
    method: 'GET',
    hostname: u.hostname,
    port: u.port || undefined,
    path: u.pathname + u.search,
    headers,
    timeout: 15000,
  };
  let gotHeaders = false;
  const doReq = (finalUrl) => {
    const req = mod.request(opts, (r) => {
      gotHeaders = true;
      req.setTimeout(0);
      if (r.statusCode >= 300 && r.statusCode < 400 && r.headers.location) {
        r.resume();
        try {
          const next = new URL(r.headers.location, finalUrl).href;
          const nu = new URL(next);
          opts.hostname = nu.hostname; opts.port = nu.port || undefined;
          opts.path = nu.pathname + nu.search;
          headers.Referer = nu.protocol + '//' + nu.host + '/';
          return doReq(next);
        } catch (e) { res.writeHead(302, { Location: r.headers.location }); res.end(); }
        return;
      }
      const ct = String(r.headers['content-type'] || '');
      const isM3U8 = /mpegurl|m3u8/i.test(ct) || /\.m3u8(\?|$)/i.test(finalUrl);
      // 清单：读全量并重写分片地址
      if (isM3U8) {
        const chunks = [];
        r.on('data', (c) => chunks.push(c));
        r.on('end', () => {
          let buf = Buffer.concat(chunks);
          if (/gzip/i.test(String(r.headers['content-encoding'] || ''))) {
            try { buf = zlib.gunzipSync(buf); } catch (e) {}
          }
          const text = buf.toString('utf8');
          const out = rewriteM3U8(text, finalUrl);
          res.writeHead(200, {
            'Content-Type': 'application/vnd.apple.mpegurl',
            'Content-Length': Buffer.byteLength(out),
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'no-cache',
          });
          res.end(out);
        });
        return;
      }
      // 二进制（ts/m4s/flv/mp4）：透传
      const outHeaders = Object.assign({}, r.headers);
      delete outHeaders['content-encoding'];
      delete outHeaders['transfer-encoding'];
      delete outHeaders['content-security-policy'];
      outHeaders['Access-Control-Allow-Origin'] = '*';
      res.writeHead(r.statusCode, outHeaders);
      r.pipe(res);
    });
    req.on('timeout', () => { req.destroy(new Error('proxy timeout')); });
    req.on('error', (e) => {
      // 首次失败重试一次（部分 IPTV 源首包会挂起）
      if (!gotHeaders && attempt < 2) {
        setTimeout(() => {
          try { if (!res.headersSent) proxyFetch(targetUrl, reqHeaders, res, attempt + 1); }
          catch (e2) { try { res.writeHead(502); res.end('proxy error'); } catch (e3) {} }
        }, 300);
        return;
      }
      if (!res.headersSent) { res.writeHead(502, { 'Access-Control-Allow-Origin': '*' }); }
      res.end('proxy error: ' + (e && e.message));
    });
    req.end();
  };
  doReq(targetUrl);
}

function startProxy() {
  if (proxyServer) return;
  proxyServer = http.createServer((req, res) => {
    // 本地代理只允许 GET/HEAD
    if (req.method !== 'GET' && req.method !== 'HEAD') { res.writeHead(405); res.end(); return; }
    let parsed;
    try { parsed = new URL(req.url, 'http://127.0.0.1:' + PROXY_PORT); }
    catch (e) { res.writeHead(400); res.end(); return; }
    const target = decodeTarget(parsed.searchParams.get('u') || '');
    if (!/^https?:/i.test(target)) { res.writeHead(400); res.end('missing target'); return; }
    proxyFetch(target, req.headers, res);
  });
  proxyServer.on('error', () => { proxyServer = null; });
  proxyServer.listen(PROXY_PORT, '127.0.0.1', () => {
    try {
      require('fs').appendFileSync(
        path.join(DATA_DIR, 'proxy.log'),
        'PROXY_LISTEN ' + new Date().toISOString() + ' port=' + PROXY_PORT + '\n');
    } catch (e) {}
  });
}

// 渲染进程请求：把远端流地址换成代理地址
ipcMain.handle('proxy-url', async (_e, url) => {
  if (!/^https?:/i.test(String(url || ''))) return String(url || '');
  return 'http://127.0.0.1:' + PROXY_PORT + '/s?u=' + encodeTarget(url);
});
ipcMain.handle('proxy-bulk', async (_e, urls) => {
  const arr = Array.isArray(urls) ? urls : [];
  const out = {};
  arr.forEach((u) => { if (/^https?:/i.test(String(u || ''))) out[u] = 'http://127.0.0.1:' + PROXY_PORT + '/s?u=' + encodeTarget(u); });
  return out;
});
// 探测某流是否可播（返回状态/类型），用于直播列表标记可用性
ipcMain.handle('probe-stream', async (_e, url) => {
  const target = String(url || '');
  if (!/^https?:/i.test(target)) return { ok: false, error: 'bad url' };
  return new Promise((resolve) => {
    let u;
    try { u = new URL(target); } catch (e) { return resolve({ ok: false, error: 'bad url' }); }
    const mod = u.protocol === 'https:' ? https : http;
    const req = mod.request({
      method: 'GET', hostname: u.hostname, port: u.port || undefined,
      path: u.pathname + u.search,
      headers: { 'User-Agent': 'okhttp/3.15', 'Accept': '*/*', 'Range': 'bytes=0-1023' },
      timeout: 8000,
    }, (r) => {
      if (r.statusCode >= 300 && r.statusCode < 400 && r.headers.location) {
        r.resume();
        try { return resolve({ ok: true, status: r.statusCode, redirect: r.headers.location, ct: '' }); }
        catch (e) { return resolve({ ok: false, error: 'bad redirect' }); }
      }
      const ct = String(r.headers['content-type'] || '');
      const chunks = [];
      r.on('data', (c) => { if (chunks.length < 6) chunks.push(c); });
      r.on('end', () => {
        const head = Buffer.concat(chunks).toString('latin1');
        resolve({
          ok: r.statusCode >= 200 && r.statusCode < 400,
          status: r.statusCode, ct,
          isM3U8: /#EXTM3U/.test(head) || /mpegurl/i.test(ct),
          isHtml: /<html|<!DOCTYPE/i.test(head),
          is404: /404|没有配置任何服务器|not found/i.test(head),
        });
      });
    });
    req.on('timeout', () => { req.destroy(); resolve({ ok: false, error: 'timeout' }); });
    req.on('error', (e) => resolve({ ok: false, error: String(e && e.message || e) }));
    req.end();
  });
});

app.on('before-quit', () => { if (proxyServer) { try { proxyServer.close(); } catch (e) {} } });

// ---- 自检入口 --------------------------------------------------------------
// 触发方式（任一）：环境变量 MSHELL_SELFTEST=1，或命令行含 selftest 字样。
// 放在文件末尾，确保 PROXY_PORT / startProxy / httpGet 均已初始化。
const SELFTEST_ON = process.env.MSHELL_SELFTEST === '1'
  || process.argv.some((a) => /selftest/i.test(a))
  || (process.argv.join(' ').indexOf('selftest') >= 0);
if (SELFTEST_ON) {
  app.whenReady().then(() => {
    try {
      fs.writeFileSync(path.join(DATA_DIR, 'selftest.log'),
        'SELFTEST_ON argv=' + JSON.stringify(process.argv) + ' env=' + process.env.MSHELL_SELFTEST + '\n', 'utf8');
    } catch (e) {}
    startProxy();
    setTimeout(() => runSelfTest(), 900);
  });
}

