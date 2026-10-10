const state={earnings:{},stocks:[],insufficient:[],blacklist:[],wishlist:[],nasdaq:[],companies:new Map(),tab:"wishlist",range:"below",query:""};
const $=s=>document.querySelector(s);
const fmt=n=>new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(n);
const poolConfig={wishlist:{label:"WISHLIST",eyebrow:"WISHLIST · WEEKLY SIGNAL",intro:"Start with the stocks you care about and see how far they are from their 200-week average."},nasdaq:{label:"NASDAQ-100",eyebrow:"NASDAQ-100 · WEEKLY SIGNAL",intro:"See how Nasdaq-100 constituents compare with their long-term trend."}};
let deployedRevision=null;
async function checkForUpdate(){try{const r=await fetch(`version.json?t=${Date.now()}`,{cache:"no-store"});if(!r.ok)return;const {revision}=await r.json();if(deployedRevision&&revision&&revision!==deployedRevision){location.reload();return}deployedRevision=revision||deployedRevision}catch(e){}}
function weekLabel(value){if(!value)return "Unknown week";const date=new Date(`${value.slice(0,10)}T12:00:00Z`),day=date.getUTCDay()||7;date.setUTCDate(date.getUTCDate()+4-day);const year=date.getUTCFullYear(),start=new Date(Date.UTC(year,0,1));return `Week ${Math.ceil((((date-start)/86400000)+1)/7)}, ${year}`}
function normalize(values){const byName=new Map([...state.companies].map(([s,n])=>[n.toUpperCase(),s]));return [...new Set(values.map(v=>{const x=v.trim().toUpperCase();return state.companies.has(x)?x:byName.get(x)||x}).filter(Boolean))]}
async function init(){try{const urls=["stocks.json","blacklist.json","watchlist.json","nasdaq100.json","earnings.json"].map(x=>fetch(`data/${x}`,{cache:"no-cache"}));const [dataRes,blackRes,wishRes,nasRes,epsRes]=await Promise.all(urls);if(!dataRes.ok)throw new Error();const data=await dataRes.json();state.earnings=epsRes.ok?(await epsRes.json()).stocks||{}:{};state.stocks=data.stocks||[];state.insufficient=data.insufficient_history||[];state.nasdaq=nasRes.ok?await nasRes.json():[];state.companies=new Map([...state.stocks.map(s=>[s.symbol,s.name]),...state.insufficient.map(s=>[s.symbol,s.name]),...state.nasdaq]);state.blacklist=normalize(blackRes.ok?await blackRes.json():[]);state.wishlist=normalize(wishRes.ok?await wishRes.json():[]);const dates=state.stocks.map(x=>x.updated).filter(Boolean).sort();$("#asof").textContent=dates.length?`Updated ${weekLabel(dates.at(-1))}`:"Awaiting first scan";render()}catch(e){$("#stock-list").innerHTML='<div class="empty"><p>No market data yet</p><small>Run the local update script first.</small></div>';updateStats([])}}
function poolSymbols(){return state.tab==="wishlist"?state.wishlist:state.nasdaq.map(x=>x[0])}
function belongs(symbol){return state.nasdaq.some(x=>x[0]===symbol)}
function inRange(d){return Number.isFinite(d)&&(state.range==="below"?d<0:d>=0&&d<Number(state.range))}
function poolRows(){const symbols=poolSymbols(),rows=symbols.map(symbol=>state.stocks.find(s=>s.symbol===symbol)).filter(Boolean);return rows.filter(s=>!state.blacklist.includes(s.symbol)&&inRange(s.distance)&&(!state.query||`${s.symbol} ${s.name}`.toLowerCase().includes(state.query))).sort((a,b)=>Math.abs(a.distance)-Math.abs(b.distance))}
function tags(symbol){
  if(!state.wishlist.includes(symbol))return [];
  const labels=["Wishlist"];
  if(belongs(symbol,"nasdaq"))labels.push("Nasdaq-100");
  return labels;
}
function badgeMarkup(symbol){const labels=tags(symbol);return labels.length?`<div class="badges">${labels.map(x=>`<i>${x}</i>`).join("")}</div>`:""}
function render(){const cfg=poolConfig[state.tab];$("#eyebrow").textContent=cfg.eyebrow;$("#intro").textContent=cfg.intro;$("#pool-label").textContent=cfg.label;$("#results-title").textContent=state.query?"Search results":"Signals";const rows=poolRows();updateStats(rows);const range=state.range==="below"?"below 200W":`0–${state.range}% above 200W`;$("#result-label").textContent=`${rows.length} stocks · ${range}`;$("#stock-list").innerHTML=rows.length?rows.map(card).join(""):`<div class="empty"><p>No stocks in this range.</p><small>Try widening the range or wait for a later scan.</small></div>`;renderAbove();renderInsufficient();renderBlacklist();renderEarnings()}
function updateStats(rows){const symbols=poolSymbols().filter(s=>!state.blacklist.includes(s)),covered=new Set(state.stocks.map(s=>s.symbol));$("#match-count").textContent=rows.length;$("#below-count").textContent=rows.filter(s=>s.distance<0).length;$("#coverage").textContent=`${symbols.filter(s=>covered.has(s)).length}/${symbols.length}`}
function valuation(symbol){
  const record=state.earnings[symbol]||{},quarters=(record.quarters||[]).slice().sort((a,b)=>a.fiscal_date_ending.localeCompare(b.fiscal_date_ending));
  const latest=quarters.at(-1),stock=state.stocks.find(s=>s.symbol===symbol),ttm=latest?.eps_ttm;
  let reason="";
  if(!Number.isFinite(latest?.eps))reason=record.error?"Earnings fetch failed; retry pending":"Awaiting reported earnings";
  else if(!Number.isFinite(ttm))reason="Need four consecutive reported quarters";
  else if(ttm<=0)reason="Trailing earnings are zero or negative";
  else if(!Number.isFinite(stock?.price)||stock.price<=0)reason="Awaiting price";
  else if(!stock.updated||stock.updated<(latest.reported_date||latest.fiscal_date_ending))reason="Awaiting price after earnings report";
  const pe=reason?null:stock.price/ttm;
  return {symbol,record,quarters,latest,stock,ttm,pe,reason};
}
function wishlistMetrics(symbol){
  if(state.tab!=="wishlist")return "";
  const {latest,pe,reason}=valuation(symbol);
  return `<div class="stock-valuation"><span>EPS <b>${Number.isFinite(latest?.eps)?latest.eps.toFixed(2):"Pending"}</b></span><span>PE <b>${Number.isFinite(pe)?pe.toFixed(1)+"×":"Pending"}</b></span>${reason?`<small>${escapeHtml(reason)}</small>`:""}</div>`;
}
function card(s){const below=s.distance<0,label=below?`${Math.abs(s.distance).toFixed(1)}% below`:`${s.distance.toFixed(1)}% above`,width=Math.max(3,Math.min(100,50+s.distance*5));return `<article class="stock-card"><div class="identity"><div class="ticker">${s.symbol}</div><div class="company"><strong>${s.name}</strong><span>${s.weeks||200}W · ${fmt(s.sma200)}</span>${badgeMarkup(s.symbol)}</div></div><div class="price"><strong>${fmt(s.price)}</strong><span class="distance ${below?"below":""}">${label}</span></div>${wishlistMetrics(s.symbol)}<div class="bar-wrap"><div class="bar"><i style="width:${width}%"></i></div><span>${weekLabel(s.updated)}</span></div></article>`}
function renderAbove(){const threshold=state.range==="below"?0:Number(state.range),symbols=new Set(poolSymbols()),rows=state.stocks.filter(s=>symbols.has(s.symbol)&&!state.blacklist.includes(s.symbol)&&Number.isFinite(s.distance)&&s.distance>=threshold&&(!state.query||`${s.symbol} ${s.name}`.toLowerCase().includes(state.query))).sort((a,b)=>a.distance-b.distance);$("#above-note").hidden=!rows.length;$("#above-count").textContent=rows.length;$("#above-list").innerHTML=rows.map(s=>`<div class="above-row"><strong>${s.symbol}</strong><span>${s.name}${badgeMarkup(s.symbol)}</span><b>${state.wishlist.includes(s.symbol)?`${fmt(s.price)} · `:""}+${s.distance.toFixed(2)}%</b>${wishlistMetrics(s.symbol)}</div>`).join("")}
function renderInsufficient(){const symbols=new Set(poolSymbols()),rows=state.insufficient.filter(s=>symbols.has(s.symbol)&&!state.blacklist.includes(s.symbol));$("#history-note").hidden=!rows.length;$("#history-count").textContent=rows.length;$("#history-list").innerHTML=rows.sort((a,b)=>b.weeks-a.weeks).map(s=>`<div class="history-row"><strong>${s.symbol}</strong><span>${s.name} · ${s.weeks}/200 weeks${badgeMarkup(s.symbol)}</span><small>Retry after ${weekLabel(s.retry_after)}</small></div>`).join("")}
function renderBlacklist(){$("#blacklist-count").textContent=state.blacklist.length;$("#blacklist-list").innerHTML=state.blacklist.length?state.blacklist.map(symbol=>`<div class="blacklist-row"><strong>${symbol}</strong><span>${state.companies.get(symbol)||"Excluded"}${badgeMarkup(symbol)}</span><i>Not scanned</i></div>`).join(""):'<div class="blacklist-row empty-row"><span>No stocks are currently excluded</span></div>'}
$(".tabs").addEventListener("click",e=>{if(!e.target.dataset.tab)return;document.querySelectorAll(".tabs button").forEach(x=>x.classList.toggle("active",x===e.target));state.tab=e.target.dataset.tab;render()});
$("#thresholds").addEventListener("click",e=>{if(!e.target.dataset.value)return;document.querySelectorAll("#thresholds button").forEach(x=>x.classList.toggle("active",x===e.target));state.range=e.target.dataset.value;render()});
$("#search").addEventListener("input",e=>{state.query=e.target.value.trim().toLowerCase();render()});
init();checkForUpdate();setInterval(checkForUpdate,30000);

function escapeHtml(value){return String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}

function trendChart(points){
  const W=620,H=240,L=58,R=562,T=30,B=194;
  const bounds=key=>{const values=points.map(p=>p[key]).filter(Number.isFinite);if(!values.length)return null;let lo=Math.min(...values),hi=Math.max(...values);const pad=(hi-lo||Math.abs(hi)*.2||1)*.15;return [lo-pad,hi+pad]};
  const epsBounds=bounds("eps"),peBounds=bounds("pe");
  const times=points.map(p=>Date.parse(p.observed_at)),start=Math.min(...times),end=Math.max(...times);
  const x=i=>points.length===1?(L+R)/2:L+(times[i]-start)/(end-start||1)*(R-L);
  const y=(value,range)=>B-(value-range[0])/(range[1]-range[0])*(B-T);
  let markup=`<svg class="valuation-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Quarterly EPS and trailing PE over weekly observation dates"><text x="${L}" y="15" class="eps-axis">EPS · left axis</text><text x="${R}" y="15" text-anchor="end" class="pe-axis">PE × · right axis</text>`;
  for(let i=0;i<4;i++){const yy=T+(B-T)*i/3;markup+=`<line x1="${L}" x2="${R}" y1="${yy}" y2="${yy}" class="chart-grid"/>`;for(const [range,xx,anchor,cls] of [[epsBounds,L-8,"end","eps-axis"],[peBounds,R+8,"start","pe-axis"]])if(range)markup+=`<text x="${xx}" y="${yy+4}" text-anchor="${anchor}" class="${cls}">${(range[1]-(range[1]-range[0])*i/3).toFixed(1)}</text>`}
  for(const [key,range,cls] of [["eps",epsBounds,"eps-series"],["pe",peBounds,"pe-series"]]){
    if(!range)continue;let segment=[];
    const flush=()=>{if(segment.length>1)markup+=`<polyline points="${segment.join(" ")}" class="${cls}"/>`;segment=[]};
    points.forEach((point,i)=>{if(!Number.isFinite(point[key])){flush();return}const xx=x(i),yy=y(point[key],range);segment.push(`${xx},${yy}`);markup+=`<circle cx="${xx}" cy="${yy}" r="4" class="${cls}"><title>${escapeHtml(point.observed_at)} · ${key.toUpperCase()}: ${point[key].toFixed(2)} · quarter ${escapeHtml(point.fiscal_date_ending)}</title></circle>`});flush();
  }
  const labels=points.length===1?[0]:[0,Math.floor((points.length-1)/2),points.length-1];
  for(const i of new Set(labels))markup+=`<text x="${x(i)}" y="221" text-anchor="middle">${escapeHtml(points[i].observed_at)}</text>`;
  return markup+"</svg>";
}
function renderEarnings(){
  $("#earnings-section").hidden=state.tab!=="wishlist";
  const symbols=state.wishlist.filter(s=>!state.blacklist.includes(s)&&(!state.query||`${s} ${state.companies.get(s)||""}`.toLowerCase().includes(state.query)));
  const rows=symbols.map(valuation).sort((a,b)=>{
    const aPE=Number.isFinite(a.pe)?a.pe:Infinity,bPE=Number.isFinite(b.pe)?b.pe:Infinity;
    return (aPE===bPE?0:aPE-bPE)||a.symbol.localeCompare(b.symbol);
  });
  $("#earnings-list").innerHTML=rows.map(({symbol,record,quarters,latest,stock,ttm,pe,reason})=>{
    const points=(record.valuations||[]).slice().sort((a,b)=>a.observed_at.localeCompare(b.observed_at));
    if(!points.length&&latest)points.push({observed_at:record.checked_at||latest.saved_at||latest.fiscal_date_ending,eps:latest.eps,pe,fiscal_date_ending:latest.fiscal_date_ending});
    return `<details class="eps-card"><summary class="eps-summary"><div class="eps-heading"><div><strong>${escapeHtml(symbol)}</strong><span class="eps-company">${escapeHtml(state.companies.get(symbol)||symbol)}</span></div><span class="eps-toggle" aria-hidden="true"></span></div><div class="valuation-metrics"><div><span>Quarterly EPS</span><strong class="eps-axis">${Number.isFinite(latest?.eps)?latest.eps.toFixed(2):"Pending"}</strong></div><div><span>PE · trailing 12 months</span><strong class="pe-axis">${Number.isFinite(pe)?`${pe.toFixed(1)}×`:"Pending"}</strong></div></div>${reason?`<p class="eps-hint">${escapeHtml(reason)}</p>`:""}</summary><div class="eps-content"><div class="eps-detail-meta"><span class="eps-period">${latest?`Quarter ended ${escapeHtml(latest.fiscal_date_ending)}`:"Awaiting earnings"}</span><div><span>Latest stored price</span><strong>${stock?fmt(stock.price):"—"}</strong><small>${stock?escapeHtml(stock.updated):"Awaiting price"}</small></div></div>${points.length?trendChart(points):'<div class="chart-empty">The chart starts after the first reported EPS is saved.</div>'}<div class="chart-legend"><span class="eps-key">Quarterly EPS</span><span class="pe-key">PE (TTM)</span><small>Weekly snapshots · separate scales</small></div>${points.length===1?'<p class="eps-hint">First observation saved. Lines appear after the next weekly snapshot.</p>':""}<details><summary>Saved history · ${quarters.length} quarter${quarters.length===1?"":"s"}</summary><div class="eps-table-wrap"><table><thead><tr><th>Observed</th><th>Quarter ended</th><th>EPS</th><th>Price</th><th>PE (TTM)</th></tr></thead><tbody>${points.map(r=>`<tr><td>${escapeHtml(r.observed_at)}</td><td>${escapeHtml(r.fiscal_date_ending)}</td><td>${r.eps.toFixed(2)}</td><td>${Number.isFinite(r.price)?fmt(r.price):"—"}</td><td>${Number.isFinite(r.pe)?r.pe.toFixed(2)+"×":"Pending"}</td></tr>`).join("")}</tbody></table></div></details>${record.error?'<p class="eps-hint">Latest fetch unavailable; saved history is retained.</p>':""}</div></details>`;
  }).join("")||'<p>No Wishlist stocks match.</p>';
}
