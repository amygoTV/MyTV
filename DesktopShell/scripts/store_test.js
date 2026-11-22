/**
 * 用户配置存储层测试（真实文件系统）
 * 运行：node scripts/store_test.js
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { UserStore } = require('../user-store');

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ms-store-'));
const store = new UserStore(dir);
const results = [];
function t(name, fn) {
  try { fn(); results.push(['PASS', name]); }
  catch (e) { results.push(['FAIL', name, e.message]); }
}

t('全新目录：没有订阅（空壳）', () => {
  if (store.getSubscription() !== null) throw new Error('应为空');
  if (store.hasSubscription()) throw new Error('hasSubscription 应为 false');
});

t('默认设置齐全', () => {
  const s = store.getSettings();
  if (s.theme !== 'dark') throw new Error('theme=' + s.theme);
  if (s.danmaku !== false) throw new Error('danmaku=' + s.danmaku);
});

t('保存设置并读回', () => {
  store.saveSettings({ theme: 'light', danmaku: true, danmakuFontSize: 28 });
  const s = store.getSettings();
  if (s.theme !== 'light') throw new Error('theme=' + s.theme);
  if (s.danmaku !== true) throw new Error('danmaku=' + s.danmaku);
  if (s.danmakuFontSize !== 28) throw new Error('font=' + s.danmakuFontSize);
  if (s.danmakuOpacity !== 0.85) throw new Error('未保留默认值');
});

t('非法主题回落为 dark', () => {
  store.saveSettings({ theme: 'rainbow' });
  const s = store.getSettings();
  if (s.theme !== 'dark') throw new Error('theme=' + s.theme);
});

t('保存订阅并读回', () => {
  store.saveSubscription({ sites: [{ key: 'a', name: 'A', api: 'http://x/api.php/provide/vod/' }], lives: [] });
  const sub = store.getSubscription();
  if (!sub || sub.sites.length !== 1) throw new Error('未读回');
  if (!store.hasSubscription()) throw new Error('hasSubscription 应为 true');
});

t('拒绝无 sites 的订阅', () => {
  try { store.saveSubscription({ sites: [] }); throw new Error('本应抛错'); }
  catch (e) { if (e.message.indexOf('sites') < 0) throw e; }
});

t('导出备份含设置与订阅', () => {
  const b = store.exportBackup();
  if (!b.settings || !b.subscription) throw new Error('缺字段');
  if (b.subscription.sites.length !== 1) throw new Error('订阅为空');
});

t('重置后回到空壳', () => {
  store.resetAll();
  if (store.getSubscription() !== null) throw new Error('订阅未清除');
  const s = store.getSettings();
  if (s.theme !== 'dark') throw new Error('设置未回落');
  if (store.hasSubscription()) throw new Error('hasSubscription 应为 false');
});

t('导入备份可恢复订阅与设置', () => {
  const backup = {
    app: 'MediaShell', version: 1,
    settings: { theme: 'light', danmaku: true },
    subscription: { sites: [{ key: 'x', name: 'X', api: 'http://y/' }] },
  };
  const r = store.importBackup(backup);
  if (!r.settings || !r.subscription) throw new Error('applied 标记错误');
  if (store.getSettings().theme !== 'light') throw new Error('设置未恢复');
  if (!store.getSubscription()) throw new Error('订阅未恢复');
});

t('导入非法备份被拒绝', () => {
  try { store.importBackup({ foo: 1 }); throw new Error('本应抛错'); }
  catch (e) { if (e.message.indexOf('备份') < 0) throw e; }
});

t('重置后再次导入仍可用', () => {
  store.resetAll();
  store.importBackup({ settings: { theme: 'dark' }, subscription: { sites: [{ key: 'k', name: 'K' }] } });
  if (!store.getSubscription()) throw new Error('未恢复');
});

try { fs.rmSync(dir, { recursive: true, force: true }); } catch (e) {}

console.log(results.map((x) => x[0] + '  ' + x[1] + (x[2] ? '  -> ' + x[2] : '')).join('\n'));
const fail = results.filter((x) => x[0] === 'FAIL').length;
console.log('\n通过 ' + (results.length - fail) + ' / ' + results.length);
process.exit(fail ? 1 : 0);
