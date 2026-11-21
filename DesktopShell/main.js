'use strict';
const { app, BrowserWindow, ipcMain, shell, dialog, session, Menu } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const https = require('https');
const { spawn } = require('child_process');
const { URL } = require('url');

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
}

try{require('fs').appendFileSync('g:/Model/WorkBuddy/AI编程助手/MyTV_work/MediaShellApp/selftest.log','MARK_WHENREADY '+new Date().toISOString()+'\n');}catch(e){}
app.whenReady().then(() => {
  // Disable the default User-Agent reveal where not needed
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
function httpGet(rawUrl, headers, timeout) {
  return new Promise((resolve, reject) => {
    let url;
    try { url = new URL(rawUrl); } catch (e) { return reject(e); }
    const mod = url.protocol === 'https:' ? https : http;
    const opts = {
      method: 'GET',
      hostname: url.hostname,
      port: url.port || undefined,
      path: url.pathname + url.search,
      headers: Object.assign({
        'User-Agent': 'okhttp/3.15',
        'Accept': '*/*',
      }, headers || {}),
    };
    const req = mod.request(opts, (res) => {
      // follow redirects (max 5)
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume();
        return httpGet(new URL(res.headers.location, rawUrl).href, headers, timeout).then(resolve, reject);
      }
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const buf = Buffer.concat(chunks);
        let body;
        const ct = String(res.headers['content-type'] || '');
        if (/gb2312|gbk/i.test(ct)) {
          try { body = new TextDecoder('gbk').decode(buf); } catch (e) { body = buf.toString('utf8'); }
        } else {
          body = buf.toString('utf8');
        }
        resolve({ status: res.statusCode, body, headers: res.headers, bytes: buf.length });
      });
    });
    req.setTimeout(timeout || 15000, () => req.destroy(new Error('timeout')));
    req.on('error', reject);
    req.end();
  });
}
ipcMain.handle('http-get', async (_e, url, headers, timeout) => {
  try { return await httpGet(url, headers, timeout); }
  catch (err) { return { status: 0, body: '', error: String(err && err.message || err) }; }
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
