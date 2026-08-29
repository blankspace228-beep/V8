(()=>{
  const $=s=>document.querySelector(s);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let last=null;
  async function getConfig(){
    try{
      const r=await fetch('/api/market-data/config',{credentials:'include'});
      if(!r.ok)return null;
      return await r.json();
    }catch{return null;}
  }
  function ensureStyles(){
    if($('#v98GatewayStyles'))return;
    const s=document.createElement('style');
    s.id='v98GatewayStyles';
    s.textContent=`
      .pp-gateway-card{border:1px solid rgba(150,92,255,.34);background:linear-gradient(145deg,rgba(39,24,58,.96),rgba(17,12,25,.96));border-radius:18px;padding:18px;margin:14px 0;box-shadow:0 18px 46px rgba(0,0,0,.25)}
      .pp-gateway-top{display:flex;align-items:center;justify-content:space-between;gap:14px}.pp-gateway-id{display:flex;gap:12px;align-items:center}.pp-gateway-dot{width:12px;height:12px;border-radius:50%;background:#ff587e;box-shadow:0 0 18px rgba(255,88,126,.45)}.pp-gateway-dot.live{background:#43e9a6;box-shadow:0 0 18px rgba(67,233,166,.6)}
      .pp-gateway-card h3{margin:0;font-size:17px}.pp-gateway-card p{margin:7px 0 0;color:#a99bb7;font-size:12px;line-height:1.55}.pp-gateway-badge{font-size:10px;font-weight:900;letter-spacing:.12em;border:1px solid rgba(255,255,255,.12);padding:7px 9px;border-radius:999px}.pp-gateway-badge.live{color:#43e9a6;border-color:rgba(67,233,166,.35);background:rgba(67,233,166,.08)}
      .pp-gateway-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:14px}.pp-gateway-grid div{border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.025);padding:11px;border-radius:12px}.pp-gateway-grid span{display:block;color:#80738d;font-size:9px;font-weight:800;letter-spacing:.1em}.pp-gateway-grid b{display:block;margin-top:4px;font-size:12px}.pp-gateway-actions{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}.pp-gateway-actions button{border:1px solid rgba(153,91,255,.45);background:#251738;color:#eee7f7;border-radius:11px;padding:10px 13px;font-weight:800;cursor:pointer}.pp-gateway-actions button:hover{background:#34204e}.pp-gateway-note{margin-top:12px!important;padding-top:12px;border-top:1px solid rgba(255,255,255,.07)}
      .pp-managed-hidden{display:none!important}@media(max-width:650px){.pp-gateway-grid{grid-template-columns:1fr}.pp-gateway-top{align-items:flex-start}}
    `;
    document.head.appendChild(s);
  }
  function card(c){
    let el=$('#ppMarketGatewayCard');
    if(!el){
      el=document.createElement('section');el.id='ppMarketGatewayCard';el.className='pp-gateway-card';
      const provider=$('.market-provider');provider?.insertAdjacentElement('afterend',el);
    }
    const live=!!c.connected;
    el.innerHTML=`<div class="pp-gateway-top"><div class="pp-gateway-id"><i class="pp-gateway-dot ${live?'live':''}"></i><div><h3>Central Market Data Gateway</h3><p>One server-side Alpaca connection supplies live market data to every Purple Paper account.</p></div></div><span class="pp-gateway-badge ${live?'live':''}">${live?'LIVE':'RECONNECTING'}</span></div><div class="pp-gateway-grid"><div><span>PROVIDER</span><b>Alpaca Market Data</b></div><div><span>FEED</span><b>${esc(String(c.feed||'iex').toUpperCase())}</b></div><div><span>ACCESS</span><b>Server managed</b></div></div><div class="pp-gateway-actions"><button type="button" id="ppGatewayTest">TEST SERVER FEED</button></div><p class="pp-gateway-note">${c.can_configure?'Owner view: credentials are stored on the Purple Paper server and are never sent to player browsers.':'Live market credentials are managed by Purple Paper. No Alpaca account or API key is required for players.'}</p>`;
    $('#ppGatewayTest')?.addEventListener('click',testFeed,{once:true});
  }
  async function testFeed(){
    const b=$('#ppGatewayTest');if(b){b.disabled=true;b.textContent='TESTING…';}
    try{
      const r=await fetch('/api/market-data/test',{method:'POST',credentials:'include'});const d=await r.json();
      if(!r.ok)throw new Error(d.detail||'Feed test failed');
      if(b){b.textContent=`LIVE • ${d.symbol} ${Number(d.price||0).toLocaleString('en-US',{style:'currency',currency:'USD'})}`;}
      setTimeout(()=>sync(),1800);
    }catch(e){if(b){b.textContent='RETRY SERVER FEED';b.title=e.message;}}
    finally{if(b)b.disabled=false;}
  }
  function apply(c){
    if(!c)return;last=c;ensureStyles();card(c);
    const title=$('#marketSetupTitle');if(title)title.textContent='Central Market Feed';
    const head=$('.market-setup-head p');if(head)head.textContent='Purple Paper uses one protected server-side market connection for stocks and 24/7 crypto. Players never need to enter an Alpaca key.';
    const state=$('#marketConfigState');if(state){state.textContent=c.connected?'SERVER LIVE':c.configured?'SERVER READY':'NOT CONFIGURED';state.classList.toggle('live',!!c.connected);}
    const top=$('#dataSetupBtn');if(top){top.disabled=false;const span=top.querySelector('span');if(span)span.textContent=c.connected?'LIVE FEED':'MARKET FEED';top.title=c.connected?'Central Alpaca feed is live':'View central market feed status';}
    const form=$('#marketSetupForm');
    if(c.configured && form)form.classList.add('pp-managed-hidden');
    else if(form && c.can_configure)form.classList.remove('pp-managed-hidden');
    const setup=$('#chartSetupBtn');if(setup){setup.textContent='CHECK LIVE FEED';setup.style.display=c.configured?'none':'inline-block';}
    ['#alpacaApiKey','#alpacaSecretKey','#toggleSecret'].forEach(s=>{const e=$(s);if(e && !c.can_configure)e.closest('label,div')?.classList.add('pp-managed-hidden');});
  }
  async function sync(){const c=await getConfig();if(c)apply(c);}
  const observer=new MutationObserver(()=>{if(last)apply(last);});
  observer.observe(document.documentElement,{childList:true,subtree:true});
  setTimeout(sync,900);setInterval(sync,20000);
  window.PurpleMarketGateway={sync,testFeed};
})();