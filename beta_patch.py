from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
html_path = ROOT / "index.html"
if not html_path.exists():
    raise SystemExit("Run prepare_desktop.py before beta_patch.py")

html = html_path.read_text(encoding="utf-8")

beta_ui = r'''
<style>
#grLicenseGate{position:fixed;inset:0;z-index:2147483647;background:radial-gradient(circle at 50% 15%,rgba(27,115,255,.18),transparent 32%),#050b14;display:flex;align-items:center;justify-content:center;padding:24px;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#f4f8ff}
#grLicenseGate.gr-hidden{display:none}
.gr-license-card{width:min(520px,100%);background:linear-gradient(180deg,rgba(16,31,53,.98),rgba(7,16,29,.98));border:1px solid rgba(103,166,255,.24);border-radius:24px;box-shadow:0 30px 90px rgba(0,0,0,.5);padding:30px}
.gr-license-logo{width:76px;height:76px;display:block;margin:0 auto 16px;filter:drop-shadow(0 12px 28px rgba(27,115,255,.28))}
.gr-license-kicker{text-align:center;font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:#57e4d9;font-weight:800}
.gr-license-title{text-align:center;font-size:28px;margin:6px 0 8px;font-weight:850;letter-spacing:-.03em}
.gr-license-copy{text-align:center;color:#9eb0c8;line-height:1.55;font-size:14px;margin:0 auto 22px;max-width:430px}
.gr-license-input{width:100%;box-sizing:border-box;border-radius:13px;border:1px solid #29405f;background:#07111f;color:#fff;padding:15px 16px;font-size:15px;outline:none;transition:.18s}
.gr-license-input:focus{border-color:#2b83ff;box-shadow:0 0 0 3px rgba(43,131,255,.14)}
.gr-license-actions{display:flex;gap:10px;margin-top:12px}
.gr-license-btn{border:0;border-radius:13px;padding:13px 16px;font-weight:800;cursor:pointer;transition:.18s}
.gr-license-btn:hover{transform:translateY(-1px)}
.gr-license-btn.primary{flex:1;background:linear-gradient(135deg,#1778ff,#2a9fff);color:white;box-shadow:0 10px 24px rgba(23,120,255,.24)}
.gr-license-btn.secondary{background:#101d30;color:#d9e7f7;border:1px solid #29405f}
.gr-license-error{min-height:20px;color:#ff8d96;font-size:13px;text-align:center;margin-top:12px}
.gr-beta-box{margin-top:18px;border:1px dashed rgba(87,228,217,.35);background:rgba(24,192,177,.055);border-radius:14px;padding:12px 13px}
.gr-beta-box strong{display:block;color:#66eadf;font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:5px}
.gr-beta-key{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px;color:#eafcff;word-break:break-all}
#grLicenseBadge{position:fixed;z-index:2147483000;top:15px;right:18px;display:none;align-items:center;gap:8px;background:rgba(5,16,30,.88);backdrop-filter:blur(16px);border:1px solid rgba(87,228,217,.26);border-radius:999px;padding:8px 11px;color:#dffefa;font:800 11px/1 system-ui;letter-spacing:.07em;box-shadow:0 8px 22px rgba(0,0,0,.22);cursor:pointer}
#grLicenseBadge.visible{display:flex}
#grLicenseBadge .dot{width:7px;height:7px;border-radius:50%;background:#4ee7d6;box-shadow:0 0 0 4px rgba(78,231,214,.10)}
#grLicensePanel{position:fixed;z-index:2147483001;top:58px;right:18px;width:260px;display:none;background:#081321;border:1px solid #243955;border-radius:16px;padding:15px;box-shadow:0 22px 60px rgba(0,0,0,.4);font-family:system-ui;color:#eaf2ff}
#grLicensePanel.visible{display:block}
#grLicensePanel h4{margin:0 0 8px;font-size:14px}
#grLicensePanel p{margin:4px 0;color:#93a8c2;font-size:12px}
#grLicensePanel button{width:100%;margin-top:12px;border:1px solid #3b4e67;background:#111f32;color:#fff;border-radius:10px;padding:9px;cursor:pointer;font-weight:700}
</style>
<div id="grLicenseGate">
  <div class="gr-license-card">
    <img class="gr-license-logo" src="build/icon.png" alt="GuardReady CA">
    <div class="gr-license-kicker">GuardReady CA Beta</div>
    <div class="gr-license-title">Activate GuardReady</div>
    <p class="gr-license-copy">Enter your license key to unlock the desktop app. This beta uses the same first-launch activation flow planned for paid customers.</p>
    <input id="grLicenseInput" class="gr-license-input" type="text" spellcheck="false" autocomplete="off" placeholder="GUARDREADY-XXXX-XXXX">
    <div class="gr-license-actions">
      <button id="grActivateBtn" class="gr-license-btn primary">Activate Beta</button>
      <button id="grPasteBtn" class="gr-license-btn secondary">Paste</button>
    </div>
    <div id="grLicenseError" class="gr-license-error"></div>
    <div class="gr-beta-box">
      <strong>Beta tester key</strong>
      <div class="gr-beta-key">GUARDREADY-BETA-2026</div>
    </div>
  </div>
</div>
<div id="grLicenseBadge" title="License details"><span class="dot"></span><span>BETA • LICENSED</span></div>
<div id="grLicensePanel">
  <h4>GuardReady CA Beta</h4>
  <p>Edition: Beta Tester</p>
  <p id="grLicenseDate">License active</p>
  <button id="grDeactivateBtn">Deactivate License</button>
</div>
<script>
(function(){
  const gate=document.getElementById('grLicenseGate'), input=document.getElementById('grLicenseInput'),
        activate=document.getElementById('grActivateBtn'), paste=document.getElementById('grPasteBtn'),
        error=document.getElementById('grLicenseError'), badge=document.getElementById('grLicenseBadge'),
        panel=document.getElementById('grLicensePanel'), date=document.getElementById('grLicenseDate'),
        deactivate=document.getElementById('grDeactivateBtn');

  function unlocked(status){
    gate.classList.add('gr-hidden'); badge.classList.add('visible');
    if(status && status.activatedAt){ try{date.textContent='Activated: '+new Date(status.activatedAt).toLocaleString();}catch(e){} }
  }
  function locked(){ panel.classList.remove('visible'); badge.classList.remove('visible'); gate.classList.remove('gr-hidden'); setTimeout(()=>input.focus(),50); }
  async function getStatus(){
    if(!window.guardreadyLicense){ error.textContent='License service could not start.'; return locked(); }
    const status=await window.guardreadyLicense.status();
    status && status.active ? unlocked(status) : locked();
  }
  async function doActivate(){
    error.textContent=''; activate.disabled=true; activate.textContent='Checking…';
    try{
      const result=await window.guardreadyLicense.activate(input.value);
      if(result && result.ok){ input.value=''; unlocked(result.status); }
      else error.textContent=(result && result.message)||'That license key is not valid.';
    }catch(e){ error.textContent='Activation failed. Please try again.'; }
    activate.disabled=false; activate.textContent='Activate Beta';
  }
  activate.addEventListener('click',doActivate);
  input.addEventListener('keydown',e=>{if(e.key==='Enter')doActivate();});
  paste.addEventListener('click',async()=>{
    try{ const text=await navigator.clipboard.readText(); if(text) input.value=text.trim(); }
    catch(e){ input.value='GUARDREADY-BETA-2026'; }
  });
  badge.addEventListener('click',()=>panel.classList.toggle('visible'));
  deactivate.addEventListener('click',async()=>{ await window.guardreadyLicense.deactivate(); locked(); });
  document.addEventListener('click',e=>{ if(panel.classList.contains('visible')&&!panel.contains(e.target)&&!badge.contains(e.target))panel.classList.remove('visible'); });
  getStatus();
})();
</script>
'''
html = html.replace("</body>", beta_ui + "\n</body>")
html_path.write_text(html, encoding="utf-8")

preload = r'''const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('guardreadyLicense', {
  status: () => ipcRenderer.invoke('license:status'),
  activate: key => ipcRenderer.invoke('license:activate', key),
  deactivate: () => ipcRenderer.invoke('license:deactivate')
});
'''
(ROOT / "preload.js").write_text(preload, encoding="utf-8")

main = r'''const { app, BrowserWindow, shell, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const iconPath = path.join(__dirname, 'build', 'icon.png');
const BETA_KEY = 'GUARDREADY-BETA-2026';

const licensePath = () => path.join(app.getPath('userData'), 'license.json');
function readLicense(){
  try{
    const d=JSON.parse(fs.readFileSync(licensePath(),'utf8'));
    return {active:d.active===true && d.key===BETA_KEY, edition:'Beta Tester', activatedAt:d.activatedAt||null};
  }catch(_){ return {active:false, edition:'Beta Tester', activatedAt:null}; }
}
function installLicenseHandlers(){
  ipcMain.handle('license:status', async()=>readLicense());
  ipcMain.handle('license:activate', async(_event,key)=>{
    const normalized=String(key||'').trim().toUpperCase().replace(/\s+/g,'');
    if(normalized!==BETA_KEY) return {ok:false,message:'Invalid beta license key.'};
    const data={active:true,key:BETA_KEY,edition:'Beta Tester',activatedAt:new Date().toISOString()};
    try{
      fs.mkdirSync(path.dirname(licensePath()),{recursive:true});
      fs.writeFileSync(licensePath(),JSON.stringify(data,null,2),'utf8');
      return {ok:true,status:readLicense()};
    }catch(_){ return {ok:false,message:'GuardReady could not save the license on this computer.'}; }
  });
  ipcMain.handle('license:deactivate',async()=>{try{fs.unlinkSync(licensePath());}catch(_){} return {ok:true};});
}
function createWindow(){
  const win=new BrowserWindow({
    width:1280,height:820,minWidth:920,minHeight:620,backgroundColor:'#07101d',
    icon:iconPath,title:'GuardReady CA Beta',show:false,
    webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true,devTools:false,preload:path.join(__dirname,'preload.js')}
  });
  win.removeMenu(); win.loadFile('index.html'); win.once('ready-to-show',()=>win.show());
  win.webContents.setWindowOpenHandler(({url})=>{if(/^https?:\/\//i.test(url))shell.openExternal(url);return{action:'deny'};});
  win.webContents.on('will-navigate',(event,url)=>{if(!url.startsWith('file://')){event.preventDefault();if(/^https?:\/\//i.test(url))shell.openExternal(url);}});
}
app.whenReady().then(()=>{installLicenseHandlers();if(process.platform==='darwin'&&app.dock)app.dock.setIcon(iconPath);createWindow();app.on('activate',()=>{if(BrowserWindow.getAllWindows().length===0)createWindow();});});
app.on('window-all-closed',()=>{if(process.platform!=='darwin')app.quit();});
'''
(ROOT / "main.js").write_text(main, encoding="utf-8")

pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
pkg["name"] = "guardready-ca-beta"
pkg["version"] = "1.1.0-beta.1"
pkg["description"] = "GuardReady CA desktop beta with license activation flow"
pkg["build"]["appId"] = "com.guardready.ca.desktop.beta"
pkg["build"]["productName"] = "GuardReady CA Beta"
pkg["build"]["files"] = ["main.js","preload.js","index.html","build/icon.png"]
pkg["build"]["nsis"]["shortcutName"] = "GuardReady CA Beta"
pkg["build"]["dmg"]["title"] = "GuardReady CA Beta"
(ROOT / "package.json").write_text(json.dumps(pkg, indent=2), encoding="utf-8")

print("Applied GuardReady beta licensing layer")
