'use strict';
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('MediaShell', {
  readConfig: (name) => ipcRenderer.invoke('read-config', name),
  listConfigs: () => ipcRenderer.invoke('list-configs'),
  saveConfig: (name, content) => ipcRenderer.invoke('save-config', name, content),
  httpGet: (url, headers, timeout) => ipcRenderer.invoke('http-get', url, headers, timeout),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
  openWithPlayer: (url, title) => ipcRenderer.invoke('open-with-player', url, title),
  detectPlayers: () => ipcRenderer.invoke('detect-players'),
  playExternal: (playerKey, url, decodeMode) => ipcRenderer.invoke('play-external', playerKey, url, decodeMode),
  appVersion: () => ipcRenderer.invoke('app-version'),
});
