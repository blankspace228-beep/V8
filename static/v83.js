(()=>{
  const q=s=>document.querySelector(s), qa=s=>[...document.querySelectorAll(s)];
  const TIERS=[
    {name:'Starter',key:'starter',threshold:0,label:'Entry tier',perks:['Core paper trading','Basic Purple Coach','1 watchlist']},
    {name:'Bronze Desk',key:'bronze',threshold:100000,label:'$100,000',perks:['+5% career XP','Bronze badge frame','2 saved watchlists']},
    {name:'Silver Desk',key:'silver',threshold:1000000,label:'$1,000,000',perks:['+10% career XP','Expanded analytics','3 saved watchlists']},
    {name:'Gold Desk',key:'gold',threshold:10000000,label:'$10,000,000',perks:['+18% career XP','Advanced risk tools','Gold badge frame']},
    {name:'Platinum Desk',key:'platinum',threshold:100000000,label:'$100,000,000',perks:['+28% career XP','Priority coach insights','Premium badge frame']},
    {name:'Purple Institutional',key:'purple',threshold:1000000000,label:'$1,000,000,000',perks:['+40% career XP','Institutional analytics','Purple prestige frame']}
  ];
  const packPerks=[['1.1x XP on trades','Daily practice bonus'],['1.25x XP on trades','Extra watchlist slots'],['1.5x XP on trades','Advanced analytics'],['2.0x XP on trades','Priority support tools']];
  const fmt=n=>'$'+Number(n||0).toLocaleString('en-US',{maximumFractionDigits:0});
  let celebrating=false,lastTier='';

  function getCurrentTier(){
    const txt=q('#tierName')?.textContent?.trim()||'';
    return TIERS.find(t=>txt.toLowerCase().includes(t.name.toLowerCase()))||TIERS[0];
  }
  function userKey(){return (state?.user?.username||'guest').toLowerCase()}

  function tone(freq,start,dur,gain=.05,type='sine'){
    if(!state?.soundEnabled)return;
    try{const C=window.AudioContext||window.webkitAudioContext,ctx=window.__v83Audio||(window.__v83Audio=new C());const o=ctx.createOscillator(),g=ctx.createGain();o.type=type;o.frequency.setValueAtTime(freq,ctx.currentTime+start);g.gain.setValueAtTime(0,ctx.currentTime+start);g.gain.linearRampToValueAtTime(gain,ctx.currentTime+start+.03);g.gain.exponentialRampToValueAtTime(.0001,ctx.currentTime+start+dur);o.connect(g);g.connect(ctx.destination);o.start(ctx.currentTime+start);o.stop(ctx.currentTime+start+dur+.02)}catch{}
  }
  function playTierSound(){tone(196,0,.35,.045,'triangle');tone(294,.09,.4,.055,'triangle');tone(392,.18,.48,.06,'sine');tone(523,.34,.7,.07,'sine');tone(784,.58,.8,.045,'sine')}

  function burst(root,x,y,count=26){
    const colors=['#ffd54f','#ff9d00','#bd69ff','#7c45ff','#fff0a1'];
    for(let i=0;i<count;i++){const p=document.createElement('i');p.className='v83-particle';const a=(Math.PI*2*i/count)+(Math.random()-.5)*.25,d=90+Math.random()*230;p.style.left=x+'%';p.style.top=y+'%';p.style.color=colors[i%colors.length];p.style.background='currentColor';p.style.setProperty('--x',Math.cos(a)*d+'px');p.style.setProperty('--y',Math.sin(a)*d+'px');p.style.setProperty('--dur',(1+Math.random()*.8)+'s');root.appendChild(p);setTimeout(()=>p.remove(),2100)}
  }
  function goldRush(root){
    for(let i=0;i<30;i++){const g=document.createElement('i');g.className='v83-gold';g.style.setProperty('--sx',(Math.random()*360-180)+'px');g.style.setProperty('--sy',(Math.random()*160-80)+'px');g.style.setProperty('--x',(Math.random()*1000-500)+'px');g.style.setProperty('--y',(Math.random()*700-350)+'px');g.style.setProperty('--rx',(Math.random()*900-450)+'deg');g.style.setProperty('--ry',(Math.random()*900-450)+'deg');g.style.setProperty('--dur',(1+Math.random()*1.1)+'s');g.style.animationDelay=(Math.random()*.65)+'s';root.appendChild(g);setTimeout(()=>g.remove(),2600)}
  }

  function celebrate(tier){
    if(celebrating||tier.threshold<=0)return;celebrating=true;
    const root=document.createElement('div');root.className='v83-celebration';root.dataset.tier=tier.key;
    root.innerHTML=`<div class="v83-celebration-flash"></div><section class="v83-stage"><div class="v83-rays"></div><button class="v83-close" aria-label="Close">×</button><div class="v83-badge"><b>${tier.key==='purple'?'P':tier.name[0]}</b></div><div class="v83-kicker">★ DESK TIER ACHIEVED ★</div><div class="v83-title">CONGRATULATIONS!</div><div class="v83-milestone">${fmt(tier.threshold)}</div><div class="v83-tier-label">${tier.name.toUpperCase()} UNLOCKED!</div><div class="v83-ribbon">KEEP BUILDING YOUR TRADING EMPIRE!</div><div class="v83-perk-strip">${tier.perks.map((p,i)=>`<div class="v83-perk-chip"><b>${i===0?'XP BOOST':i===1?'NEW ACCESS':'DESK PERK'}</b>${p}</div>`).join('')}</div><div class="v83-actions"><button class="v83-go">LET'S GO!</button></div></section>`;
    document.body.appendChild(root);playTierSound();
    setTimeout(()=>burst(root,18,23,30),180);setTimeout(()=>burst(root,82,22,34),320);setTimeout(()=>burst(root,73,42,20),640);setTimeout(()=>burst(root,29,42,24),720);setTimeout(()=>goldRush(root),260);
    const close=()=>{root.classList.add('closing');setTimeout(()=>{root.remove();celebrating=false},380)};root.querySelector('.v83-close').onclick=close;root.querySelector('.v83-go').onclick=close;
  }

  function decorateTiers(){
    const track=q('#tierTrack');if(!track)return;const current=getCurrentTier();
    [...track.children].forEach(card=>{const t=TIERS.find(x=>card.textContent.toLowerCase().includes(x.name.toLowerCase()));if(!t)return;card.classList.toggle('v83-tier-current',t.key===current.key);let s=card.querySelector('.v83-tier-perk');if(!s){s=document.createElement('small');s.className='v83-tier-perk';card.appendChild(s)}s.textContent=t.perks[0]+' • '+t.perks[1]});
  }
  function decoratePacks(){
    const packs=q('#practicePacks');if(!packs)return;[...packs.children].forEach((card,i)=>{if(card.querySelector('.v83-pack-perks'))return;const p=document.createElement('div');p.className='v83-pack-perks';const perks=packPerks[i]||['Scaling XP perk','Extra training tools'];p.innerHTML=`<b>PERKS</b><br>• ${perks[0]}<br>• ${perks[1]}<br><span style="opacity:.7">Checkout prep only • non-redeemable practice credits</span>`;card.appendChild(p);const btn=card.querySelector('button');if(btn&&btn.disabled)btn.textContent='CHECKOUT COMING SOON'});
  }
  function addPerksBoard(){
    if(q('#v83PerksBoard'))return;const anchor=q('.tier-economy-grid');if(!anchor)return;const current=getCurrentTier();const board=document.createElement('section');board.id='v83PerksBoard';board.className='v83-perks-board';
    const cards=[
      ['bronze',current.name+' PERKS',current.perks],
      ['purple','PRACTICE CREDIT PERKS',['Store price previews','Bonus daily credits','Extra chart indicators','Special badge cosmetics']],
      ['blue','CAREER PERKS',['Higher XP multipliers','Exclusive achievements','Career set rewards','Seasonal rewards']],
      ['green','PORTFOLIO PERKS',['More saved portfolios','Advanced risk tools','Custom alerts','Performance insights']],
      ['gold','COMMUNITY PERKS',['Community events','Trading tournaments','Coaching resources','Exclusive contests']]
    ];
    board.innerHTML=cards.map(c=>`<article class="v83-perk-card ${c[0]}"><h3>${c[1]}</h3><ul>${c[2].map(x=>`<li>${x}</li>`).join('')}</ul></article>`).join('');anchor.insertAdjacentElement('afterend',board)
  }
  function refreshPerksBoard(){const b=q('#v83PerksBoard');if(b){b.remove();addPerksBoard()}}

  function checkTier(){
    const tier=getCurrentTier();decorateTiers();decoratePacks();if(tier.key!==lastTier){lastTier=tier.key;refreshPerksBoard()}
    if(!state?.user||tier.threshold<=0)return;const key=`purple-tier-seen:${userKey()}:${tier.key}:v83`;if(!localStorage.getItem(key)){localStorage.setItem(key,'1');setTimeout(()=>celebrate(tier),450)}
  }

  if(typeof refreshTraderTier==='function'){const old=refreshTraderTier;refreshTraderTier=async function(...a){const r=await old.apply(this,a);setTimeout(checkTier,80);return r}}
  if(typeof refreshPracticePacks==='function'){const old=refreshPracticePacks;refreshPracticePacks=async function(...a){const r=await old.apply(this,a);setTimeout(decoratePacks,50);return r}}
  const mo=new MutationObserver(()=>{if(q('#tierName'))requestAnimationFrame(checkTier)});mo.observe(document.body,{subtree:true,childList:true,characterData:true});
  setTimeout(()=>{checkTier();addPerksBoard();decoratePacks()},900);
  window.PurplePaperTierCelebration={replay:()=>celebrate(getCurrentTier()),resetCurrent:()=>localStorage.removeItem(`purple-tier-seen:${userKey()}:${getCurrentTier().key}:v83`)};
})();
