const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

const state = {
  prices: {}, quotes: {}, active: 'AAPL', assetType: 'stock', side: 'buy',
  account: null, bars: [], timeframe: '1Min', chartMode: 'candles',
  orders: [], journal: [], feedHealth: null, cryptoAssets: [],
  cryptoConnected: false, stockConnected: false, tier: null, adaptiveCoach: null, user: null, authMode: 'login', soundEnabled: localStorage.getItem('purple_sound') !== 'off'
};
const watchSymbols = ['AAPL','MSFT','NVDA','TSLA','AMZN','META','SPY'];
const cryptoFeatured = ['BTC/USD','ETH/USD','SOL/USD','DOGE/USD','LTC/USD','AVAX/USD','LINK/USD'];
const fmt = n => Number(n || 0).toLocaleString('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:2});
const priceFmt = n => {
  const v = Number(n || 0);
  if (!v) return '—';
  const digits = v < .01 ? 8 : v < 1 ? 6 : v < 100 ? 4 : 2;
  return '$' + v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:digits});
};
const num = n => Number(n || 0).toLocaleString('en-US',{maximumFractionDigits:8});
const plClass = n => Number(n) >= 0 ? 'pos' : 'neg';
const isCrypto = s => String(s || '').includes('/');
const esc = s => String(s ?? '').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

async function api(url,opts={}) {
  const r = await fetch(url,{headers:{'Content-Type':'application/json'},...opts});
  if(!r.ok){let msg=await r.text();try{msg=JSON.parse(msg).detail||msg}catch{}throw new Error(msg)}
  return r.json();
}

function setView(view){
  $$('.view').forEach(v=>v.classList.toggle('active',v.dataset.viewPanel===view));
  $$('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.view===view));
  window.scrollTo({top:0,behavior:'smooth'});
  if(view==='game'){renderGame();refreshTraderTier();refreshPracticePacks();}
  if(view==='crypto') refreshCryptoView();
  if(view==='orders') refreshOrders();
  if(view==='journal') refreshJournal();
  if(view==='coach'){refreshCoach();refreshAdaptiveCoach();}
  if(view==='account') refreshAccountConsole();
}
$$('.nav-item').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.view)));
$$('.jump-view').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.target)));

async function subscribe(s,assetType=null){
  s=s.trim().toUpperCase(); if(!s)return;
  const type=assetType||(isCrypto(s)?'crypto':'stock');
  if(type==='stock'&&!watchSymbols.includes(s))watchSymbols.push(s);
  const d=await api('/api/subscribe',{method:'POST',body:JSON.stringify({symbol:s,asset_type:type})});
  if(d.price)state.prices[s]=d.price;
  if(d.quote)state.quotes[s]=d.quote;
  renderWatch(); renderCryptoAssets();
  return d;
}

function renderWatch(){
  const w=$('#watchlist'); if(!w)return; w.innerHTML='';
  watchSymbols.forEach(s=>{
    const b=document.createElement('button'); b.type='button';
    b.className='watch'+(s===state.active?' active':'');
    b.innerHTML=`<strong>${esc(s)}</strong><span>${state.prices[s]?priceFmt(state.prices[s]):'Waiting…'}</span>`;
    b.addEventListener('click',()=>selectSymbol(s,'stock')); w.appendChild(b);
  });
}

async function selectSymbol(s,assetType=null){
  s=s.toUpperCase(); state.active=s; state.assetType=assetType||(isCrypto(s)?'crypto':'stock');
  $('#activeSymbol').textContent=s; $('#orderSymbol').value=s;
  $('#tickerBadge').textContent=state.assetType==='crypto'?(s.split('/')[0].slice(0,2)):s[0]||'?';
  $('#companyHint').textContent=state.assetType==='crypto'?'24/7 crypto paper market':'Live U.S. stock simulation';
  const qtyLabel=$('#qtyLabel'); if(qtyLabel) qtyLabel.childNodes[0].textContent=state.assetType==='crypto'?'Units':'Shares';
  const riskButton=$('#sizeByRisk'); if(riskButton) riskButton.textContent=state.assetType==='crypto'?'Calculate units from risk':'Calculate shares from risk';
  $$('.quick-qty button').forEach((b,i)=>{if(state.assetType==='crypto'){const vals=['0.0001','0.001','0.01','0.1'];b.dataset.q=vals[i];b.textContent=vals[i]}else{const vals=['0.25','1','5','10'],labels=['¼ share','1','5','10'];b.dataset.q=vals[i];b.textContent=labels[i]}});
  renderWatch(); renderCryptoAssets(); updateActive();
  try{
    const url=state.assetType==='crypto'
      ? `/api/crypto/bars?symbol=${encodeURIComponent(s)}&timeframe=${encodeURIComponent(state.timeframe)}&limit=220`
      : `/api/bars/${encodeURIComponent(s)}?timeframe=${encodeURIComponent(state.timeframe)}&limit=220`;
    const d=await api(url); state.bars=d.bars||[]; drawChart();
  }catch{state.bars=[];drawChart()}
}

function updateActive(){
  const p=state.prices[state.active],q=state.quotes[state.active]||{},unit=state.assetType==='crypto'?'units':'shares';
  $('#activePrice').textContent=p?priceFmt(p):'—';
  $('#activeSpread').textContent=`Bid ${q.bid?priceFmt(q.bid):'—'} / Ask ${q.ask?priceFmt(q.ask):'—'}`;
  $('#bidPrice').textContent=q.bid?priceFmt(q.bid):'—'; $('#askPrice').textContent=q.ask?priceFmt(q.ask):'—';
  $('#bidSize').textContent=q.bid_size?`${num(q.bid_size)} ${unit}`:`— ${unit}`; $('#askSize').textContent=q.ask_size?`${num(q.ask_size)} ${unit}`:`— ${unit}`;
  $('#spreadValue').textContent=q.bid&&q.ask?priceFmt(q.ask-q.bid):'—'; $('#ticketQuote').textContent=p?priceFmt(p):'—';
  const age=quoteAgeSeconds(q.timestamp); $('#quoteAge').textContent=age==null?'—':age<60?`${Math.round(age)}s ago`:age<3600?`${Math.round(age/60)}m ago`:`${Math.round(age/3600)}h ago`;
  $('#quoteState').textContent=age==null?'WAITING':age<20?'LIVE':age<300?'RECENT':'LAST'; $('#quoteState').className=age!=null&&age<20?'pos':age!=null&&age<300?'':'neg';
  $('#feedName').textContent=state.assetType==='crypto'?'ALPACA • CRYPTO US':state.feedHealth?.configured?`ALPACA • ${(state.feedHealth.feed||'iex').toUpperCase()}`:'NO LIVE KEY';
  updateEstimate(); updateCryptoSpotlight();
}
function quoteAgeSeconds(ts){if(!ts)return null;const t=Date.parse(ts);if(!Number.isFinite(t))return null;return Math.max(0,(Date.now()-t)/1000)}

function setStatus(ok,text){
  state.stockConnected=!!ok; $('#statusDot').style.background=ok?'var(--green)':'var(--red)'; $('#statusText').textContent=text;
  const b=$('#dataSetupBtn'); if(b){b.classList.toggle('live',!!ok);b.title=text||''}
  if(ok&&$('#marketConfigState')){$('#marketConfigState').textContent='LIVE';$('#marketConfigState').classList.add('live')}
}
function setCryptoStatus(ok,text){
  state.cryptoConnected=!!ok;
  const pill=$('#cryptoLivePill'),msg=$('#cryptoConnectionText');
  if(pill){pill.textContent=ok?'LIVE • 24/7':'CONNECTING';pill.classList.toggle('live',ok)}
  if(msg)msg.textContent=text||'Crypto market feed';
}

function connectWS(){
  const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);
  ws.onopen=()=>ws.send('hello');
  ws.onmessage=e=>{
    const m=JSON.parse(e.data);
    if(m.type==='status') setStatus(m.connected,m.message);
    else if(m.type==='crypto_status') setCryptoStatus(m.connected,m.message);
    else if(m.type==='trade'){
      state.prices[m.symbol]=m.price;
      if(m.symbol===state.active){
        state.bars.push({t:m.timestamp,c:m.price,o:m.price,h:m.price,l:m.price,v:m.size||0}); if(state.bars.length>250)state.bars.shift(); updateActive(); drawChart();
      }
      renderWatch(); renderCryptoAssets();
    } else if(m.type==='quote'){
      state.quotes[m.symbol]={bid:m.bid,ask:m.ask,bid_size:m.bid_size,ask_size:m.ask_size,timestamp:m.timestamp,asset_type:m.asset_type};
      if(m.symbol===state.active)updateActive(); renderCryptoAssets();
    } else if(m.type==='crypto_bar'&&m.symbol===state.active&&state.assetType==='crypto'){
      const bar=m.bar||{}; const last=state.bars.at(-1);
      if(last&&last.t===bar.t)Object.assign(last,bar);else state.bars.push(bar); if(state.bars.length>250)state.bars.shift(); drawChart();
    } else if(m.type==='account'){state.account=m.data;renderAccount()}
    else if(m.type==='snapshot'){state.prices={...state.prices,...m.prices};state.quotes={...state.quotes,...m.quotes};renderWatch();renderCryptoAssets();updateActive()}
    else if(m.type==='order_update')refreshOrders();
  };
  ws.onclose=()=>{setStatus(false,'Reconnecting…');setCryptoStatus(false,'Crypto reconnecting…');setTimeout(connectWS,2200)};
}

async function refreshAccount(){state.account=await api('/api/account');renderAccount()}
function renderAccount(){
  const a=state.account;if(!a)return;
  const map={equity:a.equity,cash:a.cash,marketValue:a.market_value,realizedPL:a.realized_pl,pEquity:a.equity,pCash:a.cash,unrealizedPL:a.unrealized_pl,pRealizedPL:a.realized_pl};
  Object.entries(map).forEach(([id,v])=>{const el=$('#'+id);if(!el)return;el.textContent=fmt(v);el.classList.toggle('neg',v<0&&id.toLowerCase().includes('pl'));el.classList.toggle('pos',v>0&&id.toLowerCase().includes('pl'))});
  $('#totalPL').textContent=`${fmt(a.total_pl)} (${a.total_pl_pct.toFixed(2)}%) all time`;$('#totalPL').className=plClass(a.total_pl);
  $('#pTotalPL').textContent=`${fmt(a.total_pl)} • ${a.total_pl_pct.toFixed(2)}% all time`;$('#pTotalPL').className=plClass(a.total_pl);
  $('#sessionPill').textContent=a.session?.label||'Market';renderPositions(a.positions||[]);renderPositionCards(a.positions||[]);updateChallenges();renderGame();updateCryptoMetrics();
}
function renderPositions(rows){
  const t=$('#positions');t.innerHTML=rows.length?'':'<tr><td colspan="6">No positions yet. Place a paper trade to begin.</td></tr>';
  rows.forEach(p=>{const tr=document.createElement('tr');tr.innerHTML=`<td><div class="asset-cell"><span class="asset-dot ${isCrypto(p.symbol)?'crypto':''}">${isCrypto(p.symbol)?'₿':esc(p.symbol[0])}</span><b>${esc(p.symbol)}</b></div></td><td>${num(p.qty)}</td><td>${priceFmt(p.avg_price)}</td><td>${priceFmt(p.price)}</td><td>${fmt(p.market_value)}</td><td class="${plClass(p.unrealized_pl)}">${fmt(p.unrealized_pl)}<br><small>${p.unrealized_pl_pct.toFixed(2)}%</small></td>`;t.appendChild(tr)})
}
function renderPositionCards(rows){
  const c=$('#positionCards');c.innerHTML=rows.length?'':'<div class="position-mini"><small>No positions yet</small></div>';
  rows.slice(0,6).forEach(p=>{const d=document.createElement('div');d.className='position-mini';d.innerHTML=`<div><b>${esc(p.symbol)}</b><b class="${plClass(p.unrealized_pl)}">${p.unrealized_pl_pct.toFixed(2)}%</b></div><div><small>${num(p.qty)} ${isCrypto(p.symbol)?'units':'shares'}</small><small>${fmt(p.market_value)}</small></div>`;c.appendChild(d)})
}

async function refreshOrders(){
  state.orders=await api('/api/orders');const t=$('#orders'),cards=$('#orderCards');
  t.innerHTML=state.orders.length?'':'<tr><td colspan="9">No paper orders yet.</td></tr>';cards.innerHTML=state.orders.length?'':'<div class="order-mobile">No paper orders yet.</div>';
  state.orders.forEach(o=>{
    const trigger=o.order_type==='market'?'Market':o.order_type==='limit'?`Limit ${priceFmt(o.limit_price)}`:o.order_type==='stop'?`Stop ${priceFmt(o.stop_price)}`:`Stop ${priceFmt(o.stop_price)} / Limit ${priceFmt(o.limit_price)}`;
    const action=o.status==='open'?`<button class="cancel-order" data-id="${o.id}">Cancel</button>`:'';
    const tr=document.createElement('tr');tr.innerHTML=`<td>#${o.id}</td><td><b>${esc(o.symbol)}</b></td><td class="${o.side==='buy'?'pos':'neg'}">${o.side.toUpperCase()}</td><td>${esc(o.order_type.replace('_',' '))}</td><td>${num(o.qty)}</td><td>${trigger}</td><td>${o.fill_price?priceFmt(o.fill_price):'—'}</td><td><span class="status-chip ${o.status}">${esc(o.status)}</span></td><td>${action}</td>`;t.appendChild(tr);
    const d=document.createElement('div');d.className='order-mobile';d.innerHTML=`<div class="order-mobile-head"><h3>${esc(o.symbol)} • <span class="${o.side==='buy'?'pos':'neg'}">${o.side.toUpperCase()}</span></h3><span class="status-chip ${o.status}">${esc(o.status)}</span></div><p>${num(o.qty)} ${isCrypto(o.symbol)?'units':'shares'} • ${trigger}${o.fill_price?' • Fill '+priceFmt(o.fill_price):''}</p><div class="order-mobile-foot"><small>Order #${o.id}</small>${action}</div>`;cards.appendChild(d);
  });
  $$('.cancel-order').forEach(b=>b.addEventListener('click',async()=>{try{await api(`/api/cancel/${b.dataset.id}`,{method:'POST'});refreshOrders()}catch(e){alert(e.message)}}));
  updateChallenges();renderGame();
}

function syncOrderFields(){const type=$('#orderType').value;$('#limitRow').classList.toggle('hidden',!['limit','stop_limit'].includes(type));$('#stopRow').classList.toggle('hidden',!['stop','stop_limit'].includes(type));updateEstimate()}
function updateEstimate(){const type=$('#orderType').value,s=$('#orderSymbol').value.trim().toUpperCase(),qty=Number($('#qty').value),p=type==='limit'||type==='stop_limit'?Number($('#limitPrice').value):state.prices[s];$('#estimate').textContent=p&&qty?fmt(p*qty):'—';$('#placeOrder').textContent=`Review ${state.side.toUpperCase()} order`}
function showMsg(m,bad=false){$('#orderMessage').textContent=m;$('#orderMessage').className='message '+(bad?'neg':'pos')}

$('#tickerForm').addEventListener('submit',async e=>{e.preventDefault();const s=$('#tickerInput').value.trim().toUpperCase();if(!s)return;try{await subscribe(s,'stock');await selectSymbol(s,'stock');$('#tickerInput').value=''}catch(err){showMsg(err.message,true)}});
$$('.side').forEach(b=>b.addEventListener('click',()=>{$$('.side').forEach(x=>x.classList.remove('active'));b.classList.add('active');state.side=b.dataset.side;updateEstimate()}));
$('#orderType').addEventListener('change',syncOrderFields);['#orderSymbol','#qty','#limitPrice','#stopPrice'].forEach(x=>$(x).addEventListener('input',updateEstimate));$$('.quick-qty button').forEach(b=>b.addEventListener('click',()=>{$('#qty').value=b.dataset.q;updateEstimate()}));
function updateRiskPlanner(){
  const pct=Math.max(.1,Math.min(10,Number($('#riskPct').value)||1));$('#riskBudgetText').textContent=`${pct.toFixed(1)}% risk`;
  const p=state.prices[$('#orderSymbol').value.trim().toUpperCase()],stop=Number($('#plannedStop').value),equity=state.account?.equity||0;
  if(!p||!stop||!equity){$('#riskHint').textContent='Enter a planned stop to size a trade by account risk.';return}
  const perUnit=Math.abs(p-stop),budget=equity*pct/100;if(perUnit<=0){$('#riskHint').textContent='Planned stop must differ from the current price.';return}
  const qty=budget/perUnit,unit=state.assetType==='crypto'?'unit':'share';$('#riskHint').textContent=`Risk budget ${fmt(budget)} • ${priceFmt(perUnit)} risk/${unit} • ${num(qty)} ${unit}${qty===1?'':'s'}`;return qty;
}
$('#riskPct').addEventListener('input',updateRiskPlanner);$('#plannedStop').addEventListener('input',updateRiskPlanner);$('#sizeByRisk').addEventListener('click',()=>{const q=updateRiskPlanner();if(q&&Number.isFinite(q)&&q>0){$('#qty').value=Math.max(.00000001,Math.floor(q*100000000)/100000000);updateEstimate()}});
$('#placeOrder').addEventListener('click',async()=>{
  const symbol=$('#orderSymbol').value.trim().toUpperCase(),qty=Number($('#qty').value),order_type=$('#orderType').value,limit_price=['limit','stop_limit'].includes(order_type)?Number($('#limitPrice').value):null,stop_price=['stop','stop_limit'].includes(order_type)?Number($('#stopPrice').value):null;
  const type=isCrypto(symbol)?'crypto':'stock'; if(!symbol||!qty||qty<=0)return showMsg(`Enter a valid symbol and ${type==='crypto'?'unit':'share'} quantity.`,true);
  if(['limit','stop_limit'].includes(order_type)&&(!limit_price||limit_price<=0))return showMsg('Enter a valid limit price.',true); if(['stop','stop_limit'].includes(order_type)&&(!stop_price||stop_price<=0))return showMsg('Enter a valid stop price.',true);
  const p=limit_price||state.prices[symbol],details=`${state.side.toUpperCase()} ${num(qty)} ${symbol}\n${order_type.replace('_',' ').toUpperCase()}${p?' • '+priceFmt(p):''}`;
  if(!confirm(`PAPER TRADE ONLY\n\n${details}\n\nThis uses fake funds only. Place simulated order?`))return;
  try{const r=await api('/api/order',{method:'POST',body:JSON.stringify({symbol,asset_type:type,side:state.side,order_type,qty,limit_price,stop_price})});showMsg(`Paper order #${r.order_id} accepted.`);await refreshAccount();await refreshOrders();await refreshCoach();await refreshTraderTier();await refreshAdaptiveCoach()}catch(e){showMsg(e.message,true)}
});
$('#refreshOrders').addEventListener('click',refreshOrders);$('#resetBtn').addEventListener('click',async()=>{if(confirm('Reset fake cash, positions, orders, trades, and journal?')){await api('/api/reset',{method:'POST'});await Promise.all([refreshAccount(),refreshOrders(),refreshJournal(),refreshCoach(),refreshTraderTier(),refreshAdaptiveCoach()])}});

$$('#timeframes button').forEach(b=>b.addEventListener('click',async()=>{$$('#timeframes button').forEach(x=>x.classList.remove('active'));b.classList.add('active');state.timeframe=b.dataset.timeframe;$('#chartRange').textContent=b.textContent;await selectSymbol(state.active,state.assetType)}));
$$('#chartModes button').forEach(b=>b.addEventListener('click',()=>{$$('#chartModes button').forEach(x=>x.classList.remove('active'));b.classList.add('active');state.chartMode=b.dataset.chart;drawChart()}));
function drawChart(){
  const c=$('#chart'),wrap=c.parentElement,rect=wrap.getBoundingClientRect(),dpr=Math.min(devicePixelRatio||1,2);c.width=Math.max(1,rect.width*dpr);c.height=Math.max(1,rect.height*dpr);c.style.width=rect.width+'px';c.style.height=rect.height+'px';const x=c.getContext('2d');x.setTransform(dpr,0,0,dpr,0,0);x.clearRect(0,0,rect.width,rect.height);
  const bars=(state.bars||[]).map(b=>({o:Number(b.o??b.c),h:Number(b.h??b.c),l:Number(b.l??b.c),c:Number(b.c)})).filter(b=>[b.o,b.h,b.l,b.c].every(Number.isFinite));
  $('#chartEmpty').style.display=bars.length<2?'flex':'none';if(bars.length<2)return;
  const pad={x:28,y:24},lo=Math.min(...bars.map(b=>b.l)),hi=Math.max(...bars.map(b=>b.h)),range=(hi-lo)||1,toY=v=>pad.y+(hi-v)/range*(rect.height-pad.y*2);
  for(let i=1;i<5;i++){const y=pad.y+(rect.height-pad.y*2)*i/5;x.strokeStyle='rgba(76,61,89,.28)';x.lineWidth=1;x.beginPath();x.moveTo(pad.x,y);x.lineTo(rect.width-pad.x,y);x.stroke()}
  if(state.chartMode==='line'){
    const vals=bars.map(b=>b.c),up=vals.at(-1)>=vals[0],stroke=up?'#45dfa5':'#ff6685';x.beginPath();vals.forEach((v,i)=>{const px=pad.x+(rect.width-pad.x*2)*i/(vals.length-1),py=toY(v);i?x.lineTo(px,py):x.moveTo(px,py)});x.strokeStyle=stroke;x.lineWidth=2;x.stroke();x.lineTo(rect.width-pad.x,rect.height-pad.y);x.lineTo(pad.x,rect.height-pad.y);x.closePath();const g=x.createLinearGradient(0,pad.y,0,rect.height);g.addColorStop(0,up?'rgba(69,223,165,.16)':'rgba(255,102,133,.14)');g.addColorStop(1,'rgba(0,0,0,0)');x.fillStyle=g;x.fill();return;
  }
  const usable=rect.width-pad.x*2,step=usable/bars.length,body=Math.max(2,Math.min(10,step*.56));bars.forEach((b,i)=>{const cx=pad.x+step*(i+.5),up=b.c>=b.o,color=up?'#45dfa5':'#ff6685';x.strokeStyle=color;x.fillStyle=color;x.lineWidth=1;x.beginPath();x.moveTo(cx,toY(b.h));x.lineTo(cx,toY(b.l));x.stroke();const top=toY(Math.max(b.o,b.c)),bottom=toY(Math.min(b.o,b.c));x.fillRect(cx-body/2,top,body,Math.max(1,bottom-top))});
}

async function refreshJournal(){
  state.journal=await api('/api/journal');const box=$('#journalEntries');box.innerHTML=state.journal.length?'':'<div class="journal-entry"><small>No journal entries yet.</small></div>';
  state.journal.forEach(j=>{const d=document.createElement('article');d.className='journal-entry';d.innerHTML=`<div class="journal-entry-head"><div><h3>${esc(j.title)}</h3><small>${new Date(j.created_at).toLocaleString()}</small></div><button class="delete-entry" data-id="${j.id}" aria-label="Delete entry">×</button></div><p>${esc(j.body)}</p><div class="journal-tags">${j.symbol?`<span>${esc(j.symbol)}</span>`:''}<span>${esc(j.mood||'neutral')}</span></div>`;box.appendChild(d)});
  $$('.delete-entry').forEach(b=>b.addEventListener('click',async()=>{await api(`/api/journal/${b.dataset.id}`,{method:'DELETE'});refreshJournal()}));updateChallenges();renderGame();
}
$('#journalForm').addEventListener('submit',async e=>{e.preventDefault();const body={title:$('#journalTitle').value.trim(),body:$('#journalBody').value.trim(),symbol:$('#journalSymbol').value.trim().toUpperCase()||null,mood:$('#journalMood').value};if(!body.title||!body.body)return;await api('/api/journal',{method:'POST',body:JSON.stringify(body)});e.target.reset();$('#journalMood').value='neutral';refreshJournal()});

async function refreshCoach(){
  const [items,summary,history]=await Promise.all([api('/api/coach'),api('/api/coach/summary'),api('/api/coach/history')]);const box=$('#coachInsights');box.innerHTML='';items.forEach(i=>{const d=document.createElement('article');d.className=`insight ${i.kind||''}`;d.innerHTML=`<i></i><h3>${esc(i.title)}</h3><p>${esc(i.text)}</p>`;box.appendChild(d)});
  $('#coachRiskScore').textContent=`${summary.risk_score}/100`;$('#coachRiskLabel').textContent=summary.risk_score>=80?'Controlled practice':summary.risk_score>=60?'Watch your habits':'Higher-risk practice';$('#coachWinRate').textContent=summary.closed_trades?`${summary.win_rate.toFixed(1)}%`:'—';$('#coachClosedTrades').textContent=`${summary.closed_trades} closed trade${summary.closed_trades===1?'':'s'}`;$('#coachProfitFactor').textContent=!summary.closed_trades?'—':summary.profit_factor>=999?'∞':summary.profit_factor.toFixed(2);$('#coachConcentration').textContent=summary.biggest_symbol?`${summary.concentration.toFixed(1)}%`:'—';$('#coachLargestSymbol').textContent=summary.biggest_symbol||'No positions';renderCoachHistory(history);updateChallenges();
}
function renderCoachHistory(history){const chat=$('#coachChat'),reviews=$('#coachReviews');chat.innerHTML='';if(!history.messages.length){chat.innerHTML='<div class="coach-bubble coach"><b>Purple Coach</b><p>Ask me about your risk, win rate, losses, concentration, order execution, crypto exposure, or journaling. I analyze only your paper-trading account.</p></div>'}else{history.messages.forEach(m=>{const d=document.createElement('div');d.className=`coach-bubble ${m.role==='user'?'user':'coach'}`;d.innerHTML=`<b>${m.role==='user'?'You':'Purple Coach'}</b><p>${esc(m.body)}</p>`;chat.appendChild(d)})}chat.scrollTop=chat.scrollHeight;reviews.innerHTML=history.reviews.length?'':'<div class="coach-review"><small>No fills reviewed yet.</small></div>';history.reviews.forEach(r=>{const d=document.createElement('article');d.className=`coach-review ${r.severity||''}`;d.innerHTML=`<div class="coach-review-head"><b>${esc(r.title)}</b><small>${new Date(r.created_at).toLocaleString()}</small></div><p>${esc(r.body)}</p>`;reviews.appendChild(d)})}
async function sendCoachMessage(text){const msg=(text||'').trim();if(!msg)return;const input=$('#coachInput'),button=$('#coachForm button');input.value='';input.disabled=true;button.disabled=true;const chat=$('#coachChat');const mine=document.createElement('div');mine.className='coach-bubble user';mine.innerHTML=`<b>You</b><p>${esc(msg)}</p>`;chat.appendChild(mine);const thinking=document.createElement('div');thinking.className='coach-bubble coach';thinking.innerHTML='<b>Purple Coach</b><p>Analyzing your paper account…</p>';chat.appendChild(thinking);chat.scrollTop=chat.scrollHeight;try{const r=await api('/api/coach/chat',{method:'POST',body:JSON.stringify({message:msg})});thinking.querySelector('p').textContent=r.reply;await refreshCoach()}catch(e){thinking.querySelector('p').textContent=e.message}finally{input.disabled=false;button.disabled=false;input.focus()}}
$('#coachForm').addEventListener('submit',e=>{e.preventDefault();sendCoachMessage($('#coachInput').value)});$$('[data-coach-prompt]').forEach(b=>b.addEventListener('click',()=>sendCoachMessage(b.dataset.coachPrompt)));$('#clearCoach').addEventListener('click',async()=>{await api('/api/coach/clear',{method:'POST'});await refreshCoach()});$('#refreshCoach').addEventListener('click',refreshCoach);
function updateChallenges(){const a=state.account||{positions:[],equity:0};let maxShare=0;if(a.positions?.length&&a.equity)maxShare=Math.max(...a.positions.map(p=>p.market_value/a.equity*100));$('#challengeConcentration').textContent=!a.positions?.length?'Waiting for positions':maxShare<=25?`Passed • max ${maxShare.toFixed(1)}%`:`Practice target • ${maxShare.toFixed(1)}%`;$('#challengeJournal').textContent=`${state.journal.length} entr${state.journal.length===1?'y':'ies'}`;const advanced=state.orders.some(o=>['limit','stop','stop_limit'].includes(o.order_type));$('#challengeOrders').textContent=advanced?'Completed':'Not completed'}

async function refreshSessionReport(){try{const r=await api('/api/session-report');$('#reportGrade').textContent=r.grade;$('#reportLabel').textContent=r.label;$('#reportFeed').textContent=r.feed_configured?`${r.feed} • Stocks + crypto enabled`:'Add Alpaca keys for live market data';$('#reportFills').textContent=r.fills;$('#reportWin').textContent=r.closed?`${r.win_rate.toFixed(1)}%`:'—';$('#reportJournal').textContent=r.journal_count;if(state.assetType==='stock')$('#feedName').textContent=r.feed_configured?`ALPACA • ${(state.feedHealth?.feed||'IEX').toUpperCase()}`:'NO LIVE KEY'}catch(e){$('#reportFeed').textContent='Report unavailable'}}
$('#refreshReport')?.addEventListener('click',refreshSessionReport);
function renderPropChallenge(){const a=state.account||{total_pl_pct:0,positions:[],equity:0};const filled=(state.orders||[]).filter(o=>o.status==='filled'),closed=(state.orders||[]).filter(o=>o.status==='filled'&&o.side==='sell').length;let maxShare=0;if(a.positions?.length&&a.equity)maxShare=Math.max(...a.positions.map(p=>p.market_value/a.equity*100));const profit=a.total_pl_pct||0,drawdown=Math.min(0,profit);$('#propProfit').textContent=`${profit.toFixed(2)}%`;$('#propProfitBar').style.width=`${Math.max(0,Math.min(100,profit/8*100))}%`;$('#propDrawdown').textContent=`${drawdown.toFixed(2)}%`;$('#propDrawdownBar').style.width=`${Math.max(0,Math.min(100,(5+drawdown)/5*100))}%`;$('#propTrades').textContent=`${closed}/20`;$('#propTradesBar').style.width=`${Math.min(100,closed/20*100)}%`;$('#propRisk').textContent=a.positions?.length?`${maxShare.toFixed(1)}%`:'—';$('#propRiskBar').style.width=`${a.positions?.length?Math.max(0,Math.min(100,(25/Math.max(25,maxShare))*100)):0}%`;const failed=drawdown<=-5||maxShare>40,passed=profit>=8&&closed>=20&&maxShare<=25;$('#propStatus').textContent=failed?'FAILED':passed?'PASSED':'ACTIVE';$('#propStatus').className='paper-tag '+(failed?'neg':passed?'pos':'')}

// --- Career progression, original badge art, sounds, and celebrations ---
const progressKey=()=>`purple_progress_v8_${state.user?.id||'guest'}`;
let celebrationQueue=[],celebrationBusy=false;
function badgeArtwork(id){
  const common=`viewBox="0 0 96 96" aria-hidden="true"`;
  const bg='<circle cx="48" cy="48" r="42" fill="url(#g)" stroke="currentColor" stroke-width="2"/><defs><linearGradient id="g" x1="18" y1="12" x2="80" y2="86"><stop stop-color="#2c1a40"/><stop offset="1" stop-color="#0b0910"/></linearGradient></defs>';
  const art={
    first:`<path d="M27 62V47h8v15m9 0V33h8v29m9 0V23h8v39" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round"/><path d="M25 72h46" stroke="currentColor" stroke-width="3"/>`,
    planner:`<circle cx="48" cy="48" r="19" fill="none" stroke="currentColor" stroke-width="4"/><path d="M48 21v9m0 36v9M21 48h9m36 0h9" stroke="currentColor" stroke-width="4"/><path d="M39 50l6 6 13-17" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round"/>`,
    analyst:`<path d="M31 67l10-17 9 7 15-29" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round"/><circle cx="31" cy="67" r="4"/><circle cx="41" cy="50" r="4"/><circle cx="50" cy="57" r="4"/><circle cx="65" cy="28" r="4"/>`,
    balanced:`<path d="M48 20l25 11v18c0 16-10 24-25 29-15-5-25-13-25-29V31z" fill="none" stroke="currentColor" stroke-width="4"/><path d="M35 50h26M48 36v28" stroke="currentColor" stroke-width="4"/>`,
    coach:`<path d="M48 20l7 15 17 2-13 11 4 17-15-9-15 9 4-17-13-11 17-2z" fill="none" stroke="currentColor" stroke-width="4"/><circle cx="48" cy="48" r="6"/>`,
    operator:`<path d="M30 70h36M35 62V39l13-14 13 14v23" fill="none" stroke="currentColor" stroke-width="4"/><path d="M42 62V48h12v14M29 39h38" stroke="currentColor" stroke-width="4"/>`,
    crypto:`<circle cx="48" cy="48" r="23" fill="none" stroke="currentColor" stroke-width="4"/><path d="M40 31v34m-7-27h18c11 0 11 14 0 14H34h19c12 0 12 14 0 14H33" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round"/><path d="M43 25v6m9-6v6m-9 34v6m9-6v6" stroke="currentColor" stroke-width="3"/>`,
    diversified:`<circle cx="48" cy="48" r="25" fill="none" stroke="currentColor" stroke-width="4"/><path d="M48 23v25h25M48 48L31 67" stroke="currentColor" stroke-width="4"/><path d="M52 25a24 24 0 0119 19M28 64a24 24 0 01-3-30" fill="none" stroke="currentColor" stroke-width="5"/>`
  };
  return `<svg ${common}>${bg}${art[id]||art.first}</svg>`;
}
function playSound(kind){
  if(!state.soundEnabled)return; try{
    const AC=window.AudioContext||window.webkitAudioContext;if(!AC)return;const ctx=new AC();const master=ctx.createGain();master.gain.setValueAtTime(.12,ctx.currentTime);master.connect(ctx.destination);
    const notes=kind==='level'?[523.25,659.25,783.99,1046.5]:[659.25,987.77,1318.51];
    notes.forEach((f,i)=>{const o=ctx.createOscillator(),g=ctx.createGain(),t=ctx.currentTime+i*.09;o.type=i%2?'triangle':'sine';o.frequency.setValueAtTime(f,t);g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(kind==='level'?.7:.48,t+.018);g.gain.exponentialRampToValueAtTime(.001,t+.38);o.connect(g);g.connect(master);o.start(t);o.stop(t+.42)});setTimeout(()=>ctx.close(),900);
  }catch{}
}
function queueCelebration(item){celebrationQueue.push(item);runCelebration()}
function runCelebration(){
  if(celebrationBusy||!celebrationQueue.length)return;celebrationBusy=true;const item=celebrationQueue.shift();playSound(item.kind);
  let host=$('#celebrationHost');if(!host){host=document.createElement('div');host.id='celebrationHost';document.body.appendChild(host)}
  const card=document.createElement('div');card.className=`celebration celebration-${item.kind}`;
  card.innerHTML=`<div class="celebration-beam"></div><div class="celebration-art">${item.art||badgeArtwork('operator')}</div><div class="celebration-copy"><span>${item.kind==='level'?'CAREER PROGRESSION':'ACHIEVEMENT UNLOCKED'}</span><h2>${esc(item.title)}</h2><p>${esc(item.text)}</p></div><button type="button" aria-label="Dismiss">×</button>`;
  host.appendChild(card);requestAnimationFrame(()=>card.classList.add('show'));
  const done=()=>{card.classList.remove('show');setTimeout(()=>{card.remove();celebrationBusy=false;runCelebration()},250)};card.querySelector('button').addEventListener('click',done);setTimeout(done,item.kind==='level'?4200:3400);
}
function getProgressModel(){
  const a=state.account||{equity:0,total_pl:0,total_pl_pct:0,positions:[]};const filled=(state.orders||[]).filter(o=>o.status==='filled');const advanced=(state.orders||[]).some(o=>['limit','stop','stop_limit'].includes(o.order_type));const journalCount=(state.journal||[]).length;
  let maxShare=0;if(a.positions?.length&&a.equity)maxShare=Math.max(...a.positions.map(p=>p.market_value/a.equity*100));const cryptoFills=filled.filter(o=>isCrypto(o.symbol));const stockFills=filled.filter(o=>!isCrypto(o.symbol));
  const missions=[{done:filled.length>=1,icon:'01',title:'First Fill',text:'Complete one fake-money market trade.',xp:50},{done:advanced,icon:'02',title:'Execution Student',text:'Place a limit, stop, or stop-limit order.',xp:75},{done:journalCount>=1,icon:'03',title:'Write the Why',text:'Save at least one trade-journal entry.',xp:50},{done:a.positions?.length>0&&maxShare<=25,icon:'04',title:'Risk Discipline',text:'Keep the largest open position at or below 25% of equity.',xp:100},{done:cryptoFills.length>=1,icon:'05',title:'24/7 Market',text:'Complete your first crypto paper fill.',xp:75}];
  const baseXP=filled.length*20+journalCount*15+cryptoFills.length*10+missions.reduce((n,m)=>n+(m.done?m.xp:0),0),xp=Math.floor(baseXP*Number(state.tier?.current?.xp_mult||1)),level=Math.max(1,Math.floor(xp/250)+1),levelXP=xp%250,ranks=['ROOKIE','SCOUT','TRADER','TACTICIAN','OPERATOR','VETERAN','ELITE','DESK PRO','MARKET ACE','PURPLE LEGEND'],rank=ranks[Math.min(ranks.length-1,Math.floor((level-1)/2))];
  const badges=[
    {id:'first',name:'First Fill',text:'Complete your first simulated fill',done:filled.length>=1},
    {id:'planner',name:'Execution Architect',text:'Use an advanced order type',done:advanced},
    {id:'analyst',name:'Trade Analyst',text:'Create a journal entry',done:journalCount>=1},
    {id:'balanced',name:'Risk Guardian',text:'Keep concentration at 25% or less',done:a.positions?.length>0&&maxShare<=25},
    {id:'coach',name:'Coach Ready',text:'Generate a Purple Coach trade review',done:filled.length>=1},
    {id:'operator',name:'Desk Operator',text:'Reach Trader Level 3',done:level>=3},
    {id:'crypto',name:'Crypto Pioneer',text:'Complete a 24/7 crypto paper fill',done:cryptoFills.length>=1},
    {id:'diversified',name:'Cross-Market',text:'Hold both a stock and crypto position',done:stockFills.length>=1&&cryptoFills.length>=1&&a.positions?.some(p=>isCrypto(p.symbol))&&a.positions?.some(p=>!isCrypto(p.symbol))}
  ];
  return {a,filled,advanced,journalCount,maxShare,cryptoFills,missions,xp,level,levelXP,rank,badges};
}
function detectProgress(model){
  let prev=null;try{prev=JSON.parse(localStorage.getItem(progressKey())||'null')}catch{}
  const unlocked=model.badges.filter(b=>b.done).map(b=>b.id);
  if(!prev){localStorage.setItem(progressKey(),JSON.stringify({level:model.level,badges:unlocked}));return}
  if(model.level>Number(prev.level||1))queueCelebration({kind:'level',title:`Level ${model.level} • ${model.rank}`,text:`Congratulations. You advanced to ${model.rank} with ${model.xp} career XP.`,art:badgeArtwork('operator')});
  const old=new Set(prev.badges||[]);model.badges.filter(b=>b.done&&!old.has(b.id)).forEach(b=>queueCelebration({kind:'badge',title:b.name,text:b.text,art:badgeArtwork(b.id)}));
  localStorage.setItem(progressKey(),JSON.stringify({level:Math.max(model.level,Number(prev.level||1)),badges:[...new Set([...(prev.badges||[]),...unlocked])]}));
}
function renderGame(){
  renderPropChallenge();const m=getProgressModel(),a=m.a,completed=m.missions.filter(x=>x.done).length;const scoreEl=$('#gameXP');if(!scoreEl)return;
  scoreEl.textContent=m.xp;$('#gameLevel').textContent=`Level ${m.level}`;$('#gameRank').textContent=m.rank;$('#gameNext').textContent=`${250-m.levelXP} XP to next level`;document.querySelector('.xp-ring').style.setProperty('--xp-progress',`${m.levelXP/250*100}%`);
  $('#gEquity').textContent=fmt(a.equity||0);$('#gPL').textContent=`${(a.total_pl_pct||0).toFixed(2)}% total`;$('#gTrades').textContent=m.filled.length;$('#gMissions').textContent=`${completed}/${m.missions.length}`;
  const riskScore=100-Math.min(70,Math.max(0,m.maxShare-25)*1.2)-(m.journalCount===0&&m.filled.length>1?10:0);$('#gDiscipline').textContent=`${Math.max(0,Math.round(riskScore))}/100`;
  const list=$('#gameMissionsList');list.innerHTML='';m.missions.forEach(x=>{const d=document.createElement('article');d.className='mission '+(x.done?'done':'');d.innerHTML=`<div class="mission-icon">${x.done?'✓':x.icon}</div><div><h3>${esc(x.title)}</h3><p>${esc(x.text)}</p></div><span class="mission-reward">+${x.xp} XP</span>`;list.appendChild(d)});
  const box=$('#gameBadges');box.innerHTML='';m.badges.forEach(b=>{const d=document.createElement('div');d.className='badge '+(b.done?'unlocked':'');d.innerHTML=`<div class="badge-art">${badgeArtwork(b.id)}</div><div><strong>${esc(b.name)}</strong><small>${esc(b.text)}</small></div>${b.done?'<span class="badge-unlocked">UNLOCKED</span>':''}`;box.appendChild(d)});
  const next=m.missions.find(x=>!x.done);$('#arenaTitle').textContent=next?next.title:'Mission set complete';$('#arenaText').textContent=next?next.text:'You cleared the current career set. Keep practicing stocks and crypto while Purple Coach reviews your process.';detectProgress(m);
}


async function refreshTraderTier(){
  try{
    const t=await api('/api/game/tier');state.tier=t;
    const name=$('#tierName');if(!name)return t;
    name.textContent=t.current.name;$('#tierVolume').textContent=`${fmt(t.lifetime_volume)} traded`;
    $('#tierProgress').style.width=`${Math.max(0,Math.min(100,t.progress||0))}%`;
    $('#tierPerk').textContent=t.current.perk;
    $('#tierNext').textContent=t.next?`${fmt(Math.max(0,t.next.threshold-t.lifetime_volume))} volume to ${t.next.name}`:'Highest trader tier reached';
    const track=$('#tierTrack');track.innerHTML='';
    t.tiers.forEach(x=>{const d=document.createElement('div');d.className='tier-node'+(x.id===t.current.id?' active':'')+(t.lifetime_volume>=x.threshold?' reached':'');d.innerHTML=`<strong>${esc(x.name)}</strong><small>${x.threshold?fmt(x.threshold):'Entry tier'}</small>`;track.appendChild(d)});
    renderGame();return t;
  }catch(e){console.warn('tier',e);return null}
}
async function refreshPracticePacks(){
  const box=$('#practicePacks');if(!box)return;
  try{const r=await api('/api/practice-credit-packs');box.innerHTML='';r.packs.forEach(p=>{const d=document.createElement('article');d.className='practice-pack';d.innerHTML=`<b>${esc(p.label)}</b><strong>${fmt(p.practice_cash)}</strong><small>${esc(p.display_price)} display tier</small><button type="button" disabled title="Payments intentionally not connected">PAYMENTS OFF</button>`;box.appendChild(d)})}catch(e){box.innerHTML='<small>Practice store preview unavailable.</small>'}
}
async function refreshAdaptiveCoach(){
  try{const a=await api('/api/coach/adaptive');state.adaptiveCoach=a;if(!$('#adaptiveAvgTicket'))return a;
    $('#adaptiveAvgTicket').textContent=fmt(a.average_ticket);$('#adaptiveLossStreak').textContent=String(a.loss_streak);$('#adaptiveAdvanced').textContent=`${Number(a.advanced_ratio||0).toFixed(0)}%`;$('#adaptiveTopShare').textContent=a.top_symbol?`${a.top_symbol} • ${Number(a.top_symbol_share||0).toFixed(0)}%`:'—';
    const box=$('#adaptiveCoachInsights');box.innerHTML='';(a.observations||[]).forEach(i=>{const d=document.createElement('article');d.className=`insight ${i.kind||''}`;d.innerHTML=`<i></i><h3>${esc(i.title)}</h3><p>${esc(i.text)}</p>`;box.appendChild(d)});return a
  }catch(e){console.warn('adaptive coach',e);return null}
}

$('#soundToggle')?.addEventListener('click',()=>{state.soundEnabled=!state.soundEnabled;localStorage.setItem('purple_sound',state.soundEnabled?'on':'off');$('#soundToggle').textContent=state.soundEnabled?'🔊':'🔇';$('#soundToggle').title=state.soundEnabled?'Career sounds on':'Career sounds muted';if(state.soundEnabled)playSound('badge')});

// --- Crypto 24/7 market section ---
async function loadCryptoAssets(){
  try{const r=await api('/api/crypto/assets');state.cryptoAssets=r.assets||[];$('#cryptoCatalogState').textContent=r.dynamic?`${state.cryptoAssets.length} current USD pairs from Alpaca`:`${state.cryptoAssets.length} featured pairs`;renderCryptoAssets();const preload=state.cryptoAssets.slice(0,Math.min(12,state.cryptoAssets.length));await Promise.all(preload.map(a=>subscribe(a.symbol,'crypto').catch(()=>{})));renderCryptoAssets()}catch(e){$('#cryptoCatalogState').textContent='Crypto catalog unavailable'}
}
function coinMark(base){const map={BTC:'₿',ETH:'Ξ',SOL:'S',DOGE:'Ð',LTC:'Ł',AVAX:'A',LINK:'⬡',XRP:'X'};return map[base]||base.slice(0,2)}
function renderCryptoAssets(){
  const grid=$('#cryptoAssets');if(!grid)return;const q=($('#cryptoSearch')?.value||'').trim().toLowerCase();const rows=(state.cryptoAssets.length?state.cryptoAssets:cryptoFeatured.map(s=>({symbol:s,base:s.split('/')[0],name:s.split('/')[0]}))).filter(a=>!q||a.symbol.toLowerCase().includes(q)||(a.name||'').toLowerCase().includes(q));
  grid.innerHTML=rows.length?'':'<div class="crypto-empty">No matching crypto pairs.</div>';
  rows.forEach(a=>{const p=state.prices[a.symbol],quote=state.quotes[a.symbol]||{},age=quoteAgeSeconds(quote.timestamp),live=age!=null&&age<20;const card=document.createElement('button');card.type='button';card.className='crypto-asset'+(a.symbol===state.active?' active':'');card.innerHTML=`<span class="coin-mark">${esc(coinMark(a.base||a.symbol.split('/')[0]))}</span><span class="coin-copy"><b>${esc(a.base||a.symbol.split('/')[0])}</b><small>${esc(a.name||a.symbol)}</small></span><span class="coin-price"><b>${p?priceFmt(p):'Tap for live'}</b><small class="${live?'pos':''}">${live?'LIVE • 24/7':p?'RECENT':'READY'}</small></span>`;card.addEventListener('click',async()=>{await subscribe(a.symbol,'crypto');await selectSymbol(a.symbol,'crypto');updateCryptoSpotlight();});grid.appendChild(card)})
}
function updateCryptoSpotlight(){
  if(!$('#cryptoSpotSymbol'))return;const sym=state.assetType==='crypto'?state.active:(state.cryptoAssets[0]?.symbol||'BTC/USD'),p=state.prices[sym],q=state.quotes[sym]||{};$('#cryptoSpotSymbol').textContent=sym;$('#cryptoSpotPrice').textContent=p?priceFmt(p):'—';$('#cryptoSpotBid').textContent=q.bid?priceFmt(q.bid):'—';$('#cryptoSpotAsk').textContent=q.ask?priceFmt(q.ask):'—';const age=quoteAgeSeconds(q.timestamp);$('#cryptoSpotFresh').textContent=age==null?'Waiting for first quote':age<20?'Live now':`${Math.round(age)}s since update`;$('#cryptoTradeSelected').disabled=!p;$('#cryptoTradeSelected').dataset.symbol=sym;
}
function updateCryptoMetrics(){
  if(!$('#cryptoExposure'))return;const a=state.account||{positions:[],equity:0,cash:0};const crypto=a.positions?.filter(p=>isCrypto(p.symbol))||[],exposure=crypto.reduce((n,p)=>n+p.market_value,0);$('#cryptoExposure').textContent=fmt(exposure);$('#cryptoPositions').textContent=crypto.length;$('#cryptoCash').textContent=fmt(a.cash||0);$('#cryptoPairCount').textContent=state.cryptoAssets.length||'—';
}
async function refreshCryptoView(){if(!state.cryptoAssets.length)await loadCryptoAssets();updateCryptoMetrics();renderCryptoAssets();updateCryptoSpotlight()}
$('#cryptoSearch')?.addEventListener('input',renderCryptoAssets);
$('#cryptoTradeSelected')?.addEventListener('click',async e=>{const sym=e.currentTarget.dataset.symbol||'BTC/USD';await subscribe(sym,'crypto');await selectSymbol(sym,'crypto');setView('trade')});
$$('[data-crypto-quick]').forEach(b=>b.addEventListener('click',async()=>{const sym=b.dataset.cryptoQuick;await subscribe(sym,'crypto');await selectSymbol(sym,'crypto');setView('trade')}));

// --- Market data setup ---
function openMarketSetup(){const m=$('#marketModal');m.classList.add('open');m.setAttribute('aria-hidden','false');setTimeout(()=>$('#alpacaApiKey')?.focus(),30)}
function closeMarketSetup(){const m=$('#marketModal');m.classList.remove('open');m.setAttribute('aria-hidden','true')}
function marketMessage(text,kind=''){const el=$('#marketSetupMessage');if(!el)return;el.textContent=text;el.className='market-setup-message '+kind}
async function refreshMarketConfig(autoOpen=false){
  try{const c=await api('/api/market-data/config');state.feedHealth=c;$('#marketConfigState').textContent=c.connected?'LIVE':c.configured?'CONFIGURED':'NOT CONFIGURED';$('#dataSetupBtn').disabled=c.can_configure===false;$('#dataSetupBtn').title=c.can_configure===false?'Only the Owner configures the shared live market feed':'Configure shared market data';$('#marketConfigState').className='market-config-state'+(c.connected?' live':'');$('#dataSetupBtn').classList.toggle('live',!!c.connected);$('#alpacaFeed').value=c.feed||'iex';$('#alpacaApiKey').placeholder=c.api_key_masked?`Saved: ${c.api_key_masked}`:'Paste your Alpaca API key';$('#alpacaSecretKey').placeholder=c.secret_key_masked?`Saved: ${c.secret_key_masked}`:'Paste your Alpaca secret key';if(state.assetType==='stock')$('#feedName').textContent=c.configured?`ALPACA • ${(c.feed||'iex').toUpperCase()}`:'NO LIVE KEY';const title=$('#chartEmptyTitle'),text=$('#chartEmptyText'),setup=$('#chartSetupBtn');if(!c.configured){if(title)title.textContent='Live prices are not connected';if(text)text.textContent='Add your Alpaca keys once to enable both stocks and 24/7 crypto.';if(setup)setup.style.display='inline-block';if(autoOpen)setTimeout(openMarketSetup,250)}else{if(title)title.textContent='Waiting for the next market update…';if(text)text.textContent='Credentials are configured. Purple Paper is loading the latest quote and live stream.';if(setup)setup.style.display='none'}return c}catch(e){marketMessage(`Could not read market-data settings: ${e.message}`,'bad');return null}
}
async function testCurrentFeed(){const b=$('#testExistingFeed');b.disabled=true;marketMessage('Testing current Alpaca connection…');try{const r=await api('/api/market-data/test',{method:'POST'});marketMessage(`Connected. ${r.symbol} ${priceFmt(r.price)} • ${(r.feed||'iex').toUpperCase()} feed. Crypto uses the same keys.`,'good');if(r.price){state.prices[r.symbol]=r.price;if(r.quote)state.quotes[r.symbol]=r.quote;renderWatch();updateActive()}await refreshMarketConfig();await selectSymbol(state.active,state.assetType);await loadCryptoAssets()}catch(e){marketMessage(e.message,'bad')}finally{b.disabled=false}}
$('#dataSetupBtn')?.addEventListener('click',openMarketSetup);$('#chartSetupBtn')?.addEventListener('click',openMarketSetup);$('#closeMarketSetup')?.addEventListener('click',closeMarketSetup);$$('[data-close-market]').forEach(x=>x.addEventListener('click',closeMarketSetup));
$('#toggleSecret')?.addEventListener('click',()=>{const i=$('#alpacaSecretKey'),b=$('#toggleSecret');const show=i.type==='password';i.type=show?'text':'password';b.textContent=show?'HIDE':'SHOW'});$('#testExistingFeed')?.addEventListener('click',testCurrentFeed);
$('#marketSetupForm')?.addEventListener('submit',async e=>{e.preventDefault();const apiKey=$('#alpacaApiKey').value.trim(),secret=$('#alpacaSecretKey').value.trim(),feed=$('#alpacaFeed').value;if(!apiKey||!secret){marketMessage('Paste both the API key and secret key. Existing masked keys are not re-used here for security.','bad');return}const btn=$('#saveMarketData');btn.disabled=true;btn.textContent='TESTING…';marketMessage('Verifying credentials against a real AAPL market snapshot…');try{const r=await api('/api/market-data/config',{method:'POST',body:JSON.stringify({api_key:apiKey,secret_key:secret,feed})});$('#alpacaApiKey').value='';$('#alpacaSecretKey').value='';marketMessage(`${r.message}${r.test_price?` Test quote: AAPL ${priceFmt(r.test_price)}.`:''} Crypto will connect automatically.`,'good');if(r.test_price)state.prices.AAPL=r.test_price;await refreshMarketConfig();renderWatch();updateActive();await selectSymbol(state.active,state.assetType);await refreshSessionReport();await loadCryptoAssets();setTimeout(closeMarketSetup,1200)}catch(err){marketMessage(`Connection failed: ${err.message}`,'bad')}finally{btn.disabled=false;btn.textContent='SAVE & TEST'}});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('#marketModal')?.classList.contains('open'))closeMarketSetup()});

window.addEventListener('resize',drawChart);
// --- V8 server-backed accounts + staff roles ---
const rolePower={player:0,coach:10,moderator:20,admin:30,owner:40};
function roleClass(role){return ['owner','admin','moderator','coach','player'].includes(role)?role:'player'}
function setAuthMessage(text,kind=''){const e=$('#authMessage');if(!e)return;e.textContent=text;e.className='auth-message '+kind}
function openAuth(){const m=$('#authModal');m.classList.add('open');m.setAttribute('aria-hidden','false')}
function closeAuth(){const m=$('#authModal');m.classList.remove('open');m.setAttribute('aria-hidden','true')}
function setAuthMode(mode){state.authMode=mode;$('#authLoginTab').classList.toggle('active',mode==='login');$('#authSignupTab').classList.toggle('active',mode==='signup');$('#authSubmit').textContent=mode==='login'?'LOG IN':'CREATE ACCOUNT';$('#authPassword').autocomplete=mode==='login'?'current-password':'new-password';setAuthMessage(mode==='signup'?'Create your Purple Paper account.':'Enter your Purple Paper credentials.')}
function renderIdentity(){
  const u=state.user,role=u?.role||'player';$('#userRoleMini').textContent=u?(u.role_label||role.toUpperCase()):'GUEST';$('#userNameMini').textContent=u?u.username:'Sign in';$('#accountUsername').textContent=u?u.username:'—';const badge=$('#accountRoleBadge');if(badge){badge.textContent=u?(u.role_label||role.toUpperCase()):'PLAYER';badge.className='staff-role '+roleClass(role)}
  const desc={owner:'Full platform owner • protected highest rank',admin:'Administrator • staff and platform management',moderator:'Moderator • community account controls',coach:'Coach / Staff • recognized training role',player:'Standard Purple Paper trader account'};$('#accountRoleDescription').textContent=desc[role]||desc.player;
}
async function refreshNetworkStatus(){
  try{const n=await api('/api/network/status');const mode=$('#networkMode');if(mode){mode.textContent=n.hosted_mode?'HOSTED':'SERVER MODE';mode.classList.toggle('hosted',!!n.hosted_mode)};if($('#networkScope'))$('#networkScope').textContent=n.account_scope==='server-backed per-user'?'Per-user server storage':'Server-backed';if($('#networkUsers'))$('#networkUsers').textContent=String(n.user_count??'—');if($('#networkRole'))$('#networkRole').textContent=n.current_user?.role_label||'—';if($('#networkMessage'))$('#networkMessage').textContent=n.hosted_mode?'This account is stored on the hosted Purple Paper server and can be used from other devices that open the same server URL.':'The account engine is server-backed and multi-user ready. For internet access, deploy this build to a host using the included Docker/Render files.';return n}catch(e){if($('#networkMode'))$('#networkMode').textContent='OFFLINE';if($('#networkMessage'))$('#networkMessage').textContent='Could not read Purple Paper Network status: '+e.message;return null}
}
async function refreshAccountConsole(){
  renderIdentity();refreshNetworkStatus();const u=state.user;if(!u)return;const box=$('#ownerConsole');const canView=(rolePower[u.role]||0)>=rolePower.moderator;box.classList.toggle('hidden',!canView);if(!canView)return;
  try{const d=await api('/api/admin/users');const list=$('#userAdminList');list.innerHTML='';d.users.forEach(x=>{const row=document.createElement('div');row.className='admin-user';const canRoles=(rolePower[u.role]||0)>=rolePower.admin;const protectedTarget=x.role==='owner'&&u.role!=='owner';const options=(d.roles||[]).map(r=>`<option value="${r}" ${r===x.role?'selected':''}>${r.toUpperCase()}</option>`).join('');row.innerHTML=`<div class="admin-user-main"><span class="staff-role ${roleClass(x.role)}">${esc(x.role_label)}</span><div><strong>${esc(x.username)}</strong><small>${x.last_login_at?'Last login '+new Date(x.last_login_at).toLocaleString():'No login recorded yet'}</small></div></div><select class="role-select" data-id="${x.id}" ${(!canRoles||protectedTarget)?'disabled':''}>${options}</select><button class="account-toggle ${x.is_active?'danger':''}" data-active-id="${x.id}" ${x.id===u.id||protectedTarget?'disabled':''}>${x.is_active?'DISABLE':'ENABLE'}</button>`;list.appendChild(row)});
    $$('.role-select').forEach(sel=>sel.addEventListener('change',async()=>{try{await api(`/api/admin/users/${sel.dataset.id}/role`,{method:'POST',body:JSON.stringify({role:sel.value})});await refreshAccountConsole()}catch(e){alert(e.message);await refreshAccountConsole()}}));
    $$('[data-active-id]').forEach(btn=>btn.addEventListener('click',async()=>{try{const x=d.users.find(v=>String(v.id)===String(btn.dataset.activeId));await api(`/api/admin/users/${btn.dataset.activeId}/active`,{method:'POST',body:JSON.stringify({is_active:!x.is_active})});await refreshAccountConsole()}catch(e){alert(e.message)}}));
  }catch(e){console.warn('staff console',e)}
}
async function checkAuth(){
  try{const d=await api('/api/auth/status');state.user=d.user||null;renderIdentity();if(!d.authenticated){openAuth();if(d.needs_owner_setup){setAuthMode('signup');if(d.owner_setup_locked){$('#ownerSetupCodeWrap')?.classList.add('hidden');$('#ownerSetupCode').required=false;$('#authIntro').textContent='This hosted Purple Paper server is secured and cannot create its first account yet.';setAuthMessage('OWNER SETUP LOCKED • The server owner must configure the private OWNER_SETUP_CODE before anyone can claim the Owner account.','bad');$('#authSubmit').disabled=true;return false}$('#authSubmit').disabled=false;$('#ownerSetupCodeWrap')?.classList.toggle('hidden',!d.owner_setup_code_required);$('#ownerSetupCode').required=!!d.owner_setup_code_required;$('#authIntro').textContent='No Purple Paper Network accounts exist on this server yet. Create the first account now — it automatically becomes the protected OWNER account.';setAuthMessage(d.owner_setup_code_required?'HOSTED OWNER SETUP • Enter the private setup code, then choose your Owner login.':'OWNER SETUP • Choose your username and a password of at least 8 characters.','good')}else{$('#authSubmit').disabled=false;$('#ownerSetupCodeWrap')?.classList.add('hidden');$('#ownerSetupCode').required=false;setAuthMode('login');$('#authIntro').textContent='Sign in to continue to your Purple Paper trading account.'}return false}closeAuth();return true}catch(e){openAuth();setAuthMessage('Account system could not start: '+e.message,'bad');return false}
}
$('#authLoginTab')?.addEventListener('click',()=>setAuthMode('login'));$('#authSignupTab')?.addEventListener('click',()=>setAuthMode('signup'));
$('#authForm')?.addEventListener('submit',async e=>{e.preventDefault();const username=$('#authUsername').value.trim(),password=$('#authPassword').value;const btn=$('#authSubmit');btn.disabled=true;setAuthMessage(state.authMode==='login'?'Signing in…':'Creating account…');try{const endpoint=state.authMode==='login'?'/api/auth/login':'/api/auth/signup';const payload={username,password};if(state.authMode==='signup'&&!$('#ownerSetupCodeWrap')?.classList.contains('hidden'))payload.setup_code=$('#ownerSetupCode').value;const d=await api(endpoint,{method:'POST',body:JSON.stringify(payload)});state.user=d.user;renderIdentity();closeAuth();$('#authPassword').value='';if(d.owner_created){setTimeout(()=>showCelebration?.({kind:'badge',title:'OWNER ACCOUNT CREATED',subtitle:'Purple Paper Founder',body:'You now hold the protected Owner rank.'}),300)}if(!window.__purpleStarted)await initApp();else await refreshAccountConsole()}catch(err){setAuthMessage(err.message,'bad')}finally{btn.disabled=false;btn.textContent=state.authMode==='login'?'LOG IN':'CREATE ACCOUNT'}});
$('#logoutBtn')?.addEventListener('click',async()=>{try{await api('/api/auth/logout',{method:'POST'})}catch{}state.user=null;renderIdentity();$('#ownerSetupCodeWrap')?.classList.add('hidden');$('#ownerSetupCode').required=false;openAuth();setAuthMode('login');setAuthMessage('You have been logged out.');});
$('#userChip')?.addEventListener('click',()=>{if(state.user)setView('account');else openAuth()});

async function initApp(){
  if(window.__purpleStarted)return;window.__purpleStarted=true;
  renderWatch();syncOrderFields();connectWS();$('#soundToggle').textContent=state.soundEnabled?'🔊':'🔇';const cfg=await refreshMarketConfig(true);
  for(const s of watchSymbols)subscribe(s,'stock').catch(()=>{});
  await Promise.all([refreshAccount(),refreshOrders(),refreshJournal(),refreshCoach(),refreshSessionReport(),loadCryptoAssets(),refreshTraderTier(),refreshAdaptiveCoach(),refreshPracticePacks(),refreshNetworkStatus()]);await selectSymbol('AAPL','stock');renderGame();updateRiskPlanner();renderIdentity();
  if(!cfg?.configured)showMsg('Live prices are not configured yet. Click MARKET DATA to connect stocks and crypto.',true);
  setInterval(()=>{updateActive();updateCryptoSpotlight();refreshSessionReport().catch(()=>{});refreshMarketConfig(false).catch(()=>{})},15000);
  if('serviceWorker' in navigator&&location.protocol==='https:')navigator.serviceWorker.register('/service-worker.js').catch(()=>{});
}
async function boot(){const ok=await checkAuth();if(ok)await initApp()}
boot();
