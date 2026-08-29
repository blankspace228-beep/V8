(()=>{
  const KEY='purple_account_recovery_v95';
  const api=async(url,opt={})=>{const r=await fetch(url,{credentials:'include',headers:{'Content-Type':'application/json',...(opt.headers||{})},...opt});let j={};try{j=await r.json()}catch{}if(!r.ok)throw new Error(j.detail||j.message||'Request failed');return j};
  const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const remembered=()=>{try{return JSON.parse(localStorage.getItem(KEY)||'null')}catch{return null}};
  const savedLabel=()=>{const v=remembered();if(!v?.saved)return 'Not saved on this browser yet';const d=new Date(v.saved);return `Remembered as ${esc(v.username||'account')} • ${d.toLocaleString()}`};

  async function rememberNow(){
    const msg=document.getElementById('accountRememberMsg');
    const btn=document.getElementById('accountRememberBtn');
    if(btn){btn.disabled=true;btn.textContent='SAVING…'}
    try{
      if(window.PurpleAccountVault?.capture) await window.PurpleAccountVault.capture();
      else {
        const d=await api('/api/auth/account-vault');
        if(d.capsule)localStorage.setItem(KEY,JSON.stringify({capsule:d.capsule,username:d.username,saved:Date.now()}));
      }
      if(msg)msg.innerHTML=`<b>Remembered.</b> ${savedLabel()}<br><span style="opacity:.72">Your password and Owner Setup Code are never stored in browser recovery.</span>`;
    }catch(e){if(msg)msg.textContent=e.message||'Could not remember this account.'}
    finally{if(btn){btn.disabled=false;btn.textContent='REMEMBER THIS ACCOUNT'}}
  }

  async function mount(){
    let st;try{st=await api('/api/owner/claim-status')}catch{return}
    if(!st.signed_in)return;
    const host=document.querySelector('[data-view-panel="account"]')||document.querySelector('.account-page')||document.querySelector('main');
    if(!host)return;
    document.getElementById('ppAccountSettingsCard')?.remove();

    const card=document.createElement('section');card.id='ppAccountSettingsCard';card.className='card';card.style.cssText='margin-top:18px;padding:22px;max-width:980px';
    let ownerBody='';
    if(st.is_owner){
      ownerBody=`<div style="display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap"><div><span class="eyebrow">OWNER ACCESS</span><h2 style="margin:6px 0">Owner Active</h2><p style="margin:0;opacity:.78">This server currently recognizes <b>${esc(st.locked_to||st.current_username)}</b> as Owner.</p></div><span class="paper-tag">OWNER ACTIVE</span></div>`;
    } else if(st.can_claim){
      ownerBody=`<div><span class="eyebrow">OWNER ACCESS</span><h2 style="margin:6px 0">Enter Owner Setup Code</h2><p style="opacity:.78">This account matches the reserved Owner username <b>${esc(st.reserved_username)}</b>. Enter your private code here to activate Owner controls.</p><div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:15px"><input id="ownerClaimCode" type="password" autocomplete="new-password" spellcheck="false" placeholder="Owner Setup Code" style="min-width:280px;flex:1;padding:12px 14px;border-radius:10px;border:1px solid rgba(255,255,255,.14);background:#0d0912;color:white"><button id="ownerClaimBtn" class="trade-button" type="button">ACTIVATE OWNER</button></div><div id="ownerClaimMsg" style="margin-top:10px;min-height:22px;opacity:.8"></div></div>`;
    } else if(st.claimed){
      ownerBody=`<div><span class="eyebrow">OWNER ACCESS</span><h2 style="margin:6px 0">Owner already assigned</h2><p style="margin:0;opacity:.78">The current server database is assigned to <b>${esc(st.locked_to)}</b>.</p></div>`;
    } else {
      ownerBody=`<div><span class="eyebrow">OWNER ACCESS</span><h2 style="margin:6px 0">Reserved Owner account</h2><p style="margin:0;opacity:.78">Owner activation is reserved for <b>${esc(st.reserved_username)}</b>. You are signed in as <b>${esc(st.current_username)}</b>.</p></div>`;
    }

    card.innerHTML=`
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;border-bottom:1px solid rgba(255,255,255,.08);padding-bottom:18px;margin-bottom:20px">
        <div><span class="eyebrow">ACCOUNT SETTINGS</span><h1 style="margin:6px 0 5px;font-size:26px">Account & Security</h1><p style="margin:0;opacity:.72">Signed in as <b>${esc(st.current_username)}</b>. Manage Owner access and account recovery here.</p></div>
        <span class="paper-tag">${st.is_owner?'OWNER':'PLAYER'}</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-bottom:18px">
        <div style="padding:17px;border:1px solid rgba(255,255,255,.09);border-radius:14px;background:rgba(255,255,255,.018)">
          <span class="eyebrow">REMEMBER ACCOUNT</span><h3 style="margin:6px 0 8px">Stay signed in on this browser</h3><p style="margin:0 0 14px;opacity:.72;line-height:1.45">Purple Paper uses a long-lived secure session and a signed browser recovery capsule so reloads and normal revisits remember your account.</p>
          <button id="accountRememberBtn" class="secondary-button" type="button">REMEMBER THIS ACCOUNT</button>
          <div id="accountRememberMsg" style="margin-top:10px;font-size:12px;line-height:1.45;opacity:.82">${savedLabel()}<br><span style="opacity:.72">Passwords and Owner codes are not stored.</span></div>
        </div>
        <div style="padding:17px;border:1px solid rgba(255,255,255,.09);border-radius:14px;background:rgba(255,255,255,.018)">
          <span class="eyebrow">SESSION</span><h3 style="margin:6px 0 8px">Persistent sign-in</h3><p style="margin:0;opacity:.72;line-height:1.45">Successful logins use the site's extended session. If the temporary server database is ever replaced, the remembered-account recovery control can rebuild your login identity.</p>
        </div>
      </div>
      <div style="padding:18px;border:1px solid rgba(151,91,255,.22);border-radius:14px;background:linear-gradient(180deg,rgba(122,70,210,.07),rgba(255,255,255,.015))">${ownerBody}</div>`;
    host.appendChild(card);

    document.getElementById('accountRememberBtn')?.addEventListener('click',rememberNow);
    const btn=document.getElementById('ownerClaimBtn');
    if(btn)btn.onclick=async()=>{
      const msg=document.getElementById('ownerClaimMsg'),input=document.getElementById('ownerClaimCode'),code=input.value.trim();
      if(!code){msg.textContent='Enter the Owner Setup Code.';return}
      btn.disabled=true;btn.textContent='ACTIVATING…';
      try{
        const r=await api('/api/owner/claim',{method:'POST',body:JSON.stringify({code})});
        input.value='';
        msg.textContent=r.message||'Owner access activated.';
        try{await rememberNow()}catch{}
        setTimeout(()=>location.reload(),900);
      }catch(e){msg.textContent=e.message;btn.disabled=false;btn.textContent='ACTIVATE OWNER'}
    };
  }

  const start=()=>setTimeout(mount,900);
  document.readyState==='loading'?document.addEventListener('DOMContentLoaded',start):start();
  document.addEventListener('click',e=>{const b=e.target.closest('[data-view="account"],.user-chip');if(b)setTimeout(mount,250)});
})();