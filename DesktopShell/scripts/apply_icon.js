/**
 * afterPack 钩子：给 unpacked 目录里的 MediaShell.exe 注入应用图标。
 *
 * 为什么需要它：
 *   electron-builder 默认用 winCodeSign 包里的 rcedit 改 exe 图标，但该包在
 *   Windows 上解压会因「创建符号链接需要管理员权限」而失败。本机缓存里已有
 *   解压好的 winCodeSign（含 rcedit-x64.exe），直接复用即可，无需下载。
 *   找不到本地 rcedit 时静默跳过 —— 图标缺失不影响 EXE 正常运行。
 *
 * 用法（electron-builder.yml 里）：
 *   afterPack: scripts/apply_icon.js
 *   导出名必须是 afterPack，electron-builder 会以模块方式 require 并调用。
 */
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const CACHE_ROOTS = [
  process.env.ELECTRON_BUILDER_CACHE,
  path.join(process.env.LOCALAPPDATA || '', 'electron-builder', 'Cache'),
  path.join(process.env.HOME || '', '.cache', 'electron-builder'),
].filter(Boolean);

function findRcedit() {
  for (const root of CACHE_ROOTS) {
    const signDir = path.join(root, 'winCodeSign');
    if (!fs.existsSync(signDir)) continue;
    const candidates = [];
    for (const name of fs.readdirSync(signDir)) {
      candidates.push(path.join(signDir, name, 'rcedit-x64.exe'));
      candidates.push(path.join(signDir, name, 'rcedit-ia32.exe'));
    }
    for (const c of candidates) {
      if (fs.existsSync(c)) return c;
    }
  }
  return null;
}

async function afterPack(context) {
  const appOutDir = context && context.appOutDir;
  const productFilename = context && context.packager
    ? context.packager.appInfo.productFilename
    : 'MediaShell';
  if (!appOutDir) {
    console.log('  [icon] afterPack: 缺少 appOutDir，跳过');
    return;
  }
  const exePath = path.join(appOutDir, productFilename + '.exe');
  const iconPath = path.join(__dirname, '..', 'build', 'icon.ico');
  if (!fs.existsSync(exePath)) {
    console.log('  [icon] 未找到 ' + exePath + '，跳过');
    return;
  }
  if (!fs.existsSync(iconPath)) {
    console.log('  [icon] 未找到 ' + iconPath + '，跳过');
    return;
  }
  const rcedit = findRcedit();
  if (!rcedit) {
    console.log('  [icon] 未找到本地 rcedit，跳过图标注入');
    return;
  }
  try {
    execFileSync(rcedit, [exePath, '--set-icon', iconPath], { stdio: 'pipe' });
    console.log('  [icon] 已注入图标: ' + path.basename(exePath));
  } catch (e) {
    const msg = (e.stderr && e.stderr.toString()) || e.message || '';
    console.log('  [icon] 注入失败（忽略）: ' + msg.slice(0, 160));
  }
}

module.exports = afterPack;
module.exports.default = afterPack;
