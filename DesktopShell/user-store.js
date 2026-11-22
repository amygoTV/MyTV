'use strict';
/**
 * 用户配置存储层（MediaShell）
 *
 * 设计要点：
 *  1) **空壳首启**：应用不再内置任何影视资源。新用户首次打开时 store 里没有任何
 *     配置，界面显示引导页；导入订阅后才写入。
 *  2) **自动恢复**：配置写在 DATA_DIR（便携版 userdata / 目录版 userdata/），
 *     重新打开应用自动加载，无需再次导入。
 *  3) **导入导出**：整份配置可导出为一个 JSON 备份文件，也可从备份文件导入。
 *  4) **重置**：清空全部用户配置，回到空壳状态。
 *
 * 存储布局（DATA_DIR 下）：
 *    settings.json     用户设置（主题、弹幕、播放器偏好等）
 *    subscription.json  导入的影视仓/TVBox 配置（sites/lives/rules 等）
 */
const fs = require('fs');
const path = require('path');

const SETTINGS_FILE = 'settings.json';
const SUBSCRIPTION_FILE = 'subscription.json';

// 默认设置
const DEFAULT_SETTINGS = {
  theme: 'dark',              // dark | light
  danmaku: false,             // 弹幕总开关
  danmakuOpacity: 0.85,
  danmakuFontSize: 22,
  danmakuArea: 0.5,           // 弹幕显示区域占比（0~1）
  danmakuSpeed: 8,
  liveTimeout: 8,
  liveDecoder: 'hardware',
  livePlayer: 'builtin',
  autoSite: true,             // 启动自动测速选站
  lastSite: '',
};

class UserStore {
  constructor(dataDir) {
    this.dir = dataDir;
    this.settingsPath = path.join(dataDir, SETTINGS_FILE);
    this.subPath = path.join(dataDir, SUBSCRIPTION_FILE);
  }

  _ensure() {
    try { fs.mkdirSync(this.dir, { recursive: true }); } catch (e) {}
  }

  _readJson(file, fallback) {
    try {
      const raw = fs.readFileSync(file, 'utf8');
      if (!raw || !raw.trim()) return fallback;
      return JSON.parse(raw);
    } catch (e) { return fallback; }
  }

  _writeJson(file, data) {
    this._ensure();
    const tmp = file + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(data, null, 2), 'utf8');
    // 原子替换，避免写入中断导致配置损坏
    try { fs.renameSync(tmp, file); }
    catch (e) { fs.writeFileSync(file, JSON.stringify(data, null, 2), 'utf8'); }
    return true;
  }

  // ---- settings ----
  getSettings() {
    const s = this._readJson(this.settingsPath, {});
    const merged = Object.assign({}, DEFAULT_SETTINGS, s || {});
    // 主题合法性兜底
    if (merged.theme !== 'light' && merged.theme !== 'dark') merged.theme = 'dark';
    return merged;
  }

  saveSettings(patch) {
    const cur = this.getSettings();
    const next = Object.assign({}, cur, patch || {});
    this._writeJson(this.settingsPath, next);
    return next;
  }

  // ---- subscription (影视接口配置) ----
  getSubscription() {
    const sub = this._readJson(this.subPath, null);
    if (!sub || !Array.isArray(sub.sites) || !sub.sites.length) return null;
    return sub;
  }

  saveSubscription(cfg) {
    if (!cfg || !Array.isArray(cfg.sites) || !cfg.sites.length) {
      throw new Error('配置中没有 sites');
    }
    this._writeJson(this.subPath, cfg);
    return true;
  }

  hasSubscription() {
    return !!this.getSubscription();
  }

  // ---- 备份导出 / 导入 ----
  exportBackup() {
    return {
      app: 'MediaShell',
      version: 1,
      exportedAt: new Date().toISOString(),
      settings: this.getSettings(),
      subscription: this.getSubscription(),
    };
  }

  importBackup(payload) {
    if (!payload || typeof payload !== 'object') throw new Error('备份文件格式无效');
    const hasSub = payload.subscription && Array.isArray(payload.subscription.sites)
      && payload.subscription.sites.length;
    const hasSet = payload.settings && typeof payload.settings === 'object';
    if (!hasSub && !hasSet) throw new Error('备份文件中没有可恢复的配置');
    if (hasSet) this.saveSettings(payload.settings);
    if (hasSub) this.saveSubscription(payload.subscription);
    return { settings: !!hasSet, subscription: !!hasSub };
  }

  // ---- 重置：清空全部用户配置，回到空壳状态 ----
  resetAll() {
    const removed = [];
    [this.settingsPath, this.subPath].forEach((f) => {
      try { if (fs.existsSync(f)) { fs.unlinkSync(f); removed.push(path.basename(f)); } }
      catch (e) {}
    });
    // 清理可能的临时文件
    try {
      fs.readdirSync(this.dir).forEach((n) => {
        if (/\.tmp$/.test(n)) { try { fs.unlinkSync(path.join(this.dir, n)); } catch (e) {} }
      });
    } catch (e) {}
    return removed;
  }

  // 存储位置（供界面展示）
  info() {
    return { dir: this.dir, settings: this.settingsPath, subscription: this.subPath };
  }
}

module.exports = { UserStore, DEFAULT_SETTINGS };
