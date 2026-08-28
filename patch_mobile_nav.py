from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else 'android-project/app/src/main/assets/index.html')
h = path.read_text(encoding='utf-8')

if 'id="menuToggle"' in h and 'id="drawerOverlay"' in h:
    print('Mobile drawer already present')
    raise SystemExit(0)

h = h.replace('content="width=device-width,initial-scale=1"','content="width=device-width,initial-scale=1,viewport-fit=cover"')

h = h.replace('.toast.show{opacity:1;transform:translateY(0)}', '.toast.show{opacity:1;transform:translateY(0)}\n.menu-toggle,.drawer-close{display:none}.drawer-overlay{display:none}', 1)

old_mobile = "@media(max-width:680px){.shell{display:block}.side{position:fixed;z-index:60;left:0;right:0;bottom:0;top:auto;height:auto;width:100%;border-right:0;border-top:1px solid var(--line);padding:8px;background:var(--panel)}.brand,.side-note{display:none}.nav{grid-template-columns:repeat(7,1fr);gap:2px}.nav button{padding:8px 2px;box-shadow:none}.nav button.active{box-shadow:none}.main{padding:20px 15px 85px}.top h2{font-size:25px}.pill small{display:none}.stats{grid-template-columns:1fr 1fr}.modules{grid-template-columns:1fr}.learnlayout{grid-template-columns:1fr}.lessonlist{grid-template-columns:1fr 1fr}.controls{grid-template-columns:1fr}.qcard{padding:20px}.qcard h3{font-size:20px}.hero{padding:22px}.hero h3{font-size:27px}.breakdown{grid-template-columns:1fr}.sourceitem{align-items:flex-start;flex-direction:column}}"
new_mobile = "@media(max-width:680px){.shell{display:block}.side{position:fixed;z-index:80;left:0;top:0;bottom:0;width:min(82vw,300px);height:100dvh;border-right:1px solid var(--line);border-top:0;padding:calc(18px + env(safe-area-inset-top)) 14px calc(18px + env(safe-area-inset-bottom));background:rgba(5,13,24,.98);transform:translateX(-105%);transition:transform .24s ease;box-shadow:18px 0 45px rgba(0,0,0,.36);overflow-y:auto}.light .side{background:rgba(255,255,255,.98)}.side.open{transform:translateX(0)}.brand{display:flex;padding:0 4px 18px;position:relative}.brand>div:last-child{display:block}.brand h1{font-size:19px}.brand p{font-size:10px}.drawer-close{display:grid;place-items:center;position:absolute;right:-2px;top:-4px;width:36px;height:36px;border:1px solid var(--line);border-radius:11px;background:var(--panel2);color:var(--text);font-size:22px;cursor:pointer}.drawer-overlay{display:block;position:fixed;z-index:70;inset:0;background:rgba(0,0,0,.46);opacity:0;pointer-events:none;transition:opacity .24s ease}.drawer-overlay.show{opacity:1;pointer-events:auto}.nav{grid-template-columns:1fr;gap:7px}.nav button{font-size:15px;justify-content:flex-start;padding:13px 13px;box-shadow:none}.nav button span{font-size:18px}.nav button.active{box-shadow:inset 3px 0 0 var(--blue)}.side-note{display:block;margin-top:18px}.main{padding:calc(16px + env(safe-area-inset-top)) 15px calc(24px + env(safe-area-inset-bottom));min-height:100dvh}.top{align-items:flex-start;gap:10px;margin-bottom:20px}.top>div:first-child{display:flex;align-items:flex-start;gap:10px}.menu-toggle{display:grid;place-items:center;flex:0 0 44px;width:44px;height:44px;border:1px solid var(--line);background:var(--panel);color:var(--text);border-radius:13px;box-shadow:var(--shadow);font-size:22px;cursor:pointer}.top h2{font-size:25px}.pill small{display:none}.stats{grid-template-columns:1fr 1fr}.modules{grid-template-columns:1fr}.learnlayout{grid-template-columns:1fr}.lessonlist{grid-template-columns:1fr 1fr}.controls{grid-template-columns:1fr}.qcard{padding:20px}.qcard h3{font-size:20px}.hero{padding:22px}.hero h3{font-size:27px}.breakdown{grid-template-columns:1fr}.sourceitem{align-items:flex-start;flex-direction:column}}"
if old_mobile not in h:
    raise SystemExit('Could not locate old phone navigation CSS')
h = h.replace(old_mobile, new_mobile, 1)
h = h.replace('@media(max-width:680px){body{overscroll-behavior:none}.main{padding-bottom:92px}.answer{min-height:54px}.btn{min-height:46px}}', '@media(max-width:680px){body{overscroll-behavior:none}.answer{min-height:54px}.btn{min-height:46px}}')

old_brand = '<div class="brand"><div class="shield">G</div><div><h1>GuardReady</h1><p>California Guard Card Prep</p></div></div>'
new_brand = '<div class="brand"><div class="shield">G</div><div><h1>GuardReady</h1><p>California Guard Card Prep</p></div><button class="drawer-close" id="drawerClose" aria-label="Close menu">×</button></div>'
if old_brand not in h:
    raise SystemExit('Could not locate brand block')
h = h.replace(old_brand, new_brand, 1)
h = h.replace('</aside>\n<main class="main">', '</aside>\n<div class="drawer-overlay" id="drawerOverlay"></div>\n<main class="main">', 1)

old_header = '<header class="top"><div><p class="eyebrow">CALIFORNIA SECURITY GUARD PREP</p><h2 id="title">Dashboard</h2></div><div class="topright"><div class="pill">🔥 <strong id="streak">0</strong><small>day streak</small></div><button class="icon" id="theme" title="Light / dark">◐</button></div></header>'
new_header = '<header class="top"><div><button class="menu-toggle" id="menuToggle" aria-label="Open menu">☰</button><div><p class="eyebrow">CALIFORNIA SECURITY GUARD PREP</p><h2 id="title">Dashboard</h2></div></div><div class="topright"><div class="pill">🔥 <strong id="streak">0</strong><small>day streak</small></div><button class="icon" id="theme" title="Light / dark">◐</button></div></header>'
if old_header not in h:
    raise SystemExit('Could not locate header block')
h = h.replace(old_header, new_header, 1)

old_nav = "function nav(v){$$('.view').forEach(x=>x.classList.remove('active'));$('#'+v).classList.add('active');$$('.nav button').forEach(x=>x.classList.toggle('active',x.dataset.v===v));let names={dashboard:'Dashboard',learn:'Learn',practice:'Practice',exam:'Mock Exam',flash:'Flashcards',missed:'Missed Questions',sources:'Sources'};$('#title').textContent=names[v];if(v==='dashboard')renderDashboard();if(v==='learn')renderLearn();if(v==='practice')renderPracticeStart();if(v==='exam')renderExamStart();if(v==='flash')renderFlash();if(v==='missed')renderMissed();if(v==='sources')renderSources()}\n$$('.nav button').forEach(b=>b.onclick=()=>nav(b.dataset.v));"
new_nav = "function closeDrawer(){const s=document.querySelector('.side'),o=$('#drawerOverlay');if(s)s.classList.remove('open');if(o)o.classList.remove('show');}\nfunction openDrawer(){const s=document.querySelector('.side'),o=$('#drawerOverlay');if(s)s.classList.add('open');if(o)o.classList.add('show');}\nfunction nav(v){$$('.view').forEach(x=>x.classList.remove('active'));$('#'+v).classList.add('active');$$('.nav button').forEach(x=>x.classList.toggle('active',x.dataset.v===v));let names={dashboard:'Dashboard',learn:'Learn',practice:'Practice',exam:'Mock Exam',flash:'Flashcards',missed:'Missed Questions',sources:'Sources'};$('#title').textContent=names[v];if(v==='dashboard')renderDashboard();if(v==='learn')renderLearn();if(v==='practice')renderPracticeStart();if(v==='exam')renderExamStart();if(v==='flash')renderFlash();if(v==='missed')renderMissed();if(v==='sources')renderSources();closeDrawer()}\n$$('.nav button').forEach(b=>b.onclick=()=>nav(b.dataset.v));\nif($('#menuToggle'))$('#menuToggle').onclick=openDrawer;if($('#drawerClose'))$('#drawerClose').onclick=closeDrawer;if($('#drawerOverlay'))$('#drawerOverlay').onclick=closeDrawer;document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDrawer()});"
if old_nav not in h:
    raise SystemExit('Could not locate nav script')
h = h.replace(old_nav, new_nav, 1)

path.write_text(h, encoding='utf-8')
print('Applied GuardReady mobile drawer navigation update')
