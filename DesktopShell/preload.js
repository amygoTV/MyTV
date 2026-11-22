'use strict';
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('MediaShell', {
  // ---- 用户配置存储（订阅 / 设置 / 备份 / 重置）----
  getSubscription: () => ipcRenderer.invoke('get-subscription'),
  getSettings: () => ipcRenderer.invoke('get-settings'),
  saveSettings: (patch) => ipcRenderer.invoke('save-settings', patch),
  saveSubscription: (cfg) => ipcRenderer.invoke('save-subscription', cfg),
  hasSubscription: () => ipcRenderer.invoke('has-subscription'),
  storeInfo: () => ipcRenderer.invoke('store-info'),
  exportBackup: (payload) => ipcRenderer.invoke('export-backup', payload),
  importBackup: () => ipcRenderer.invoke('import-backup'),
  resetUserData: () => ipcRenderer.invoke('reset-userdata'),

  // ---- 本地文件（辅助）----
  readConfig: (name) => ipcRenderer.invoke('read-config', name),
  listConfigs: () => ipcRenderer.invoke('list-configs'),
  saveConfig: (name, content) => ipcRenderer.invoke('save-config', name, content),
  httpGet: (url, headers, timeout) => ipcRenderer.invoke('http-get', url, headers, timeout),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
  openWithPlayer: (url, title) => ipcRenderer.invoke('open-with-player', url, title),
  detectPlayers: () => ipcRenderer.invoke('detect-players'),
  playExternal: (playerKey, url, decodeMode) => ipcRenderer.invoke('play-external', playerKey, url, decodeMode),
  proxyUrl: (url) => ipcRenderer.invoke('proxy-url', url),
  proxyBulk: (urls) => ipcRenderer.invoke('proxy-bulk', urls),
  probeStream: (url) => ipcRenderer.invoke('probe-stream', url),
  // 同步版本：供 hls.js xhrSetup 内部改写请求地址使用
  // 注意：主进程用 base64url 解码，这里必须用同一编码（- / 替代 + /）
  localProxy: (url) => {
    const u = String(url || '');
    if (!/^https?:/i.test(u)) return u;
    // 本地代理已是代理地址，直接放行
    if (/^https?:\/\/127\.0\.0\.1:/i.test(u)) return u;
    try {
      const b64 = btoa(unescape(encodeURIComponent(u)))
        .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
      return 'http://127.0.0.1:19871/s?u=' + b64;
    } catch (e) { return u; }
  },
  appVersion: () => ipcRenderer.invoke('app-version'),
});
