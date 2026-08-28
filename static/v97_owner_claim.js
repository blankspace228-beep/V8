(()=>{
  const api=async(url,opt={})=>{const r=await fetch(url,{credentials:'include',headers:{'Content-Type':'application/json',...(opt.headers||{})},...opt});let j={};try{j=await r.json()}catch{}if(!r.ok)throw new Error(j.detail||j.message||'Request failed');return j};
  const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  async function mount(){
    let st;try{st=await api('/api/owner/claim-status')}catch{return}
    if(!st.signed_in)return;
    const host=document.querySelector('[data-view-panel="account"]')||document.querySelector('.account-page')||document.querySelector('main');
    if(!host||document.getElementById('ownerClaimCard'))return;
    const card=document.createElement('section');card.id='ownerClaimCard';card.className='card';card.style.cssText='margin-top:18px;padding:22px;max-width:980px';
    let body='';
    if(st.is_owner){body=`<div style="display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap"><div><span class="eyebrow">OWNER ACCESS</span><h2 style="margin:6px 0">Server Owner Locked</h2><p style="margin:0;opacity:.78">Owner access is permanently bound to <b>${esc(st.locked_to||st.current_username)}</b> on this server and cannot be transferred to another account.</p></div><span class="paper-tag">OWNER ACTIVE</span></div>`}
    else if(st.can_claim){body=`<div><span class="eyebrow">OWNER ACCESS</span><h2 style="margin:6px 0">Claim this server</h2><p style="opacity:.78">This account matches the reserved Owner username <b>${esc(st.reserved_username)}</b>. Enter the private Owner Setup Code once. After it succeeds, this server's Owner slot is permanently locked to this account.</p><div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:15px"><input id="ownerClaimCode" type="password" autocomplete="off" placeholder="Owner Setup Code" style="min-width:280px;flex:1;padding:12px 14px;border-radius:10px;border:1px solid rgba(255,255,255,.14);background:#0d0912;color:white"><button id="ownerClaimBtn" class="trade-button" type="button">CLAIM OWNER</button></div><div id="ownerClaimMsg" style="margin-top:10px;min-height:22px;opacity:.8"></div></div>`}
    else if(st.claimed){body=`<div><span class="eyebrow">OWNER ACCESS</span><h2 style="margin:6px 0">Owner slot already claimed</h2><p style="margin:0;opacity:.78">This server is permanently bound to <b>${esc(st.locked_to)}</b>. Owner access cannot be reassigned from Settings.</p></div>`}
    else {body=`<div><span class="eyebrow">OWNER ACCESS</span><h2 style="margin:6px 0">Reserved Owner account</h2><p style="margin:0;opacity:.78">Owner access can only be claimed by the reserved username <b>${esc(st.reserved_username)}</b>. You are signed in as <b>${esc(st.current_username)}</b>.</p></div>`}
    card.innerHTML=body;host.appendChild(card);
    const btn=document.getElementById('ownerClaimBtn');if(btn)btn.onclick=async()=>{const msg=document.getElementById('ownerClaimMsg'),code=document.getElementById('ownerClaimCode').value.trim();if(!code){msg.textContent='Enter the Owner Setup Code.';return}btn.disabled=true;btn.textContent='CLAIMING…';try{const r=await api('/api/owner/claim',{method:'POST',body:JSON.stringify({code})});msg.textContent=r.message||'Owner access activated.';setTimeout(()=>location.reload(),900)}catch(e){msg.textContent=e.message;btn.disabled=false;btn.textContent='CLAIM OWNER'}};
  }
  const start=()=>setTimeout(mount,900);document.readyState==='loading'?document.addEventListener('DOMContentLoaded',start):start();
  document.addEventListener('click',e=>{const b=e.target.closest('[data-view="account"],.user-chip');if(b)setTimeout(mount,300)});
})();