from pathlib import Path
import base64, urllib.request, zipfile, shutil, json, struct, zlib, math

ROOT = Path(__file__).resolve().parent
BASE = "https://raw.githubusercontent.com/blankspace228-beep/V8/guardready-android-build/guardready-build/"

# Reuse the same GuardReady study content that is already used by the Android build.
parts = []
for name in ["project.b64.001", "project.b64.002", "project.b64.003", "project.b64.004"]:
    with urllib.request.urlopen(BASE + name) as r:
        parts.append(r.read().decode("utf-8").strip())
raw = base64.b64decode("".join(parts))
zip_path = ROOT / "android_source.zip"
zip_path.write_bytes(raw)
extract = ROOT / "android_source"
if extract.exists():
    shutil.rmtree(extract)
with zipfile.ZipFile(zip_path) as z:
    z.extractall(extract)
source_html = extract / "app" / "src" / "main" / "assets" / "index.html"
if not source_html.exists():
    raise SystemExit("Could not find GuardReady HTML in Android project")
html = source_html.read_text(encoding="utf-8")
html = html.replace(
    '.brand{display:flex;gap:12px;align-items:center;padding:0 7px 24px}',
    '.brand{display:flex;gap:12px;align-items:center;padding:0 7px 24px}.brand-logo{width:48px;height:48px;object-fit:contain;filter:drop-shadow(0 8px 16px rgba(27,115,255,.22))}'
)
html = html.replace(
    '<div class="brand"><div class="shield">G</div><div>',
    '<div class="brand"><img class="brand-logo" src="build/icon.png" alt="GuardReady CA"><div>'
)
(ROOT / "index.html").write_text(html, encoding="utf-8")

# Create a 512x512 GuardReady shield/check PNG with no external Python packages.
def in_poly(x, y, pts):
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]; xj, yj = pts[j]
        if ((yi > y) != (yj > y)) and (x < (xj-xi)*(y-yi)/(yj-yi+1e-9)+xi):
            inside = not inside
        j = i
    return inside

def dist_seg(px, py, ax, ay, bx, by):
    vx, vy = bx-ax, by-ay
    wx, wy = px-ax, py-ay
    c1 = vx*wx + vy*wy
    if c1 <= 0: return math.hypot(px-ax, py-ay)
    c2 = vx*vx + vy*vy
    if c2 <= c1: return math.hypot(px-bx, py-by)
    t = c1/c2
    return math.hypot(px-(ax+t*vx), py-(ay+t*vy))

S=512
outer=[(128,10),(224,46),(208,171),(128,242),(48,171),(32,46)]
inner=[(128,28),(207,58),(193,161),(128,220),(63,161),(49,58)]
mid=[(128,44),(189,68),(179,151),(128,199),(77,151),(67,68)]
rows=[]
for y in range(S):
    row=bytearray([0])
    for x in range(S):
        xx, yy = x/2.0, y/2.0
        rgba=(0,0,0,0)
        if in_poly(xx,yy,outer): rgba=(13,118,255,255)
        if in_poly(xx,yy,inner): rgba=(5,24,57,255)
        if in_poly(xx,yy,mid): rgba=(21,107,222,255)
        if dist_seg(xx,yy,86,125,112,151) <= 8 or dist_seg(xx,yy,112,151,171,91) <= 8:
            rgba=(255,255,255,255)
        if 91 <= xx <= 165 and 177 <= yy <= 184: rgba=(58,226,215,255)
        if 101 <= xx <= 155 and 188 <= yy <= 195: rgba=(58,226,215,255)
        row.extend(rgba)
    rows.append(bytes(row))

def chunk(tag,data):
    import binascii
    return struct.pack('>I',len(data))+tag+data+struct.pack('>I',binascii.crc32(tag+data)&0xffffffff)
png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',S,S,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows),9))+chunk(b'IEND',b'')
(ROOT / "build").mkdir(exist_ok=True)
(ROOT / "build" / "icon.png").write_bytes(png)

main_js = r"""const { app, BrowserWindow, shell } = require('electron');
const path = require('path');
const iconPath = path.join(__dirname, 'build', 'icon.png');
function createWindow() {
  const win = new BrowserWindow({
    width: 1280, height: 820, minWidth: 920, minHeight: 620,
    backgroundColor: '#07101d', icon: iconPath, title: 'GuardReady CA', show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, devTools: false }
  });
  win.removeMenu();
  win.loadFile('index.html');
  win.once('ready-to-show', () => win.show());
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith('file://')) {
      event.preventDefault();
      if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    }
  });
}
app.whenReady().then(() => {
  if (process.platform === 'darwin' && app.dock) app.dock.setIcon(iconPath);
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
"""
(ROOT / "main.js").write_text(main_js, encoding="utf-8")

pkg = {
  "name":"guardready-ca",
  "version":"1.0.0",
  "description":"California Guard Card study and exam-prep desktop application",
  "main":"main.js",
  "author":"GuardReady CA",
  "license":"UNLICENSED",
  "scripts": {
    "start":"electron .",
    "dist:win":"electron-builder --win nsis portable --x64",
    "dist:mac":"electron-builder --mac dmg zip --universal"
  },
  "build": {
    "appId":"com.guardready.ca.desktop",
    "productName":"GuardReady CA",
    "copyright":"Copyright © 2026 GuardReady CA",
    "asar": True,
    "files":["main.js","index.html","build/icon.png"],
    "directories":{"output":"dist"},
    "win":{"icon":"build/icon.png","target":[{"target":"nsis","arch":["x64"]},{"target":"portable","arch":["x64"]}]},
    "nsis":{"oneClick":False,"allowToChangeInstallationDirectory":True,"createDesktopShortcut":True,"createStartMenuShortcut":True,"shortcutName":"GuardReady CA"},
    "mac":{"icon":"build/icon.png","category":"public.app-category.education","target":["dmg","zip"],"hardenedRuntime":False,"gatekeeperAssess":False},
    "dmg":{"title":"GuardReady CA"}
  }
}
(ROOT / "package.json").write_text(json.dumps(pkg, indent=2), encoding="utf-8")
print("Prepared GuardReady desktop source")
