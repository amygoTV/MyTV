/**
 * afterAllArtifactBuild 钩子：给最终 portable 外壳 exe 注入图标（保留 overlay）。
 *
 * 踩坑记录：
 *   - afterPack 只改到 win-unpacked 里的内层 MediaShell.exe，用户双击不到它。
 *   - portable 外壳是 NSIS stub(PE) + 尾部 payload(overlay)，用户双击的是它。
 *   - signAndEditExecutable:false（绕开 winCodeSign 符号链接权限问题）会让外壳留默认图标。
 *   - ⚠️ 直接对最终 exe 跑 rcedit --set-icon 会重写 PE 并丢掉 overlay，
 *     exe 从 ~66MB 缩到 ~400KB，程序报废。所以必须走 Python 脚本保留 overlay。
 *
 * 在 electron-builder.yml 里：afterAllArtifactBuild: scripts/apply_final_icon.js
 */
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

async function afterAllArtifactBuild(context) {
  const artifactPaths = (context && context.artifactPaths) || [];
  const exes = artifactPaths.filter((p) => p && /\.exe$/i.test(p));
  if (!exes.length) {
    console.log('  [final-icon] 没有 exe 产物，跳过');
    return [];
  }
  const pyScript = path.join(__dirname, 'inject_icon_keep_overlay.py');
  const iconPath = path.join(__dirname, '..', 'build', 'icon.ico');
  if (!fs.existsSync(pyScript) || !fs.existsSync(iconPath)) {
    console.log('  [final-icon] 缺脚本或图标，跳过');
    return [];
  }
  for (const exe of exes) {
    try {
      const out = execFileSync('python', [pyScript, exe, iconPath], { encoding: 'utf8' });
      console.log('  [final-icon] ' + path.basename(exe) + ': ' +
        (out || '').split('\n').filter((l) => l.includes('完整性') || l.includes('注入完成')).join(' | '));
    } catch (e) {
      const msg = (e.stdout || e.stderr || e.message || '').toString();
      console.log('  [final-icon] 注入失败（请手动处理）: ' + msg.slice(0, 200));
    }
  }
  return [];
}

module.exports = afterAllArtifactBuild;
module.exports.default = afterAllArtifactBuild;
