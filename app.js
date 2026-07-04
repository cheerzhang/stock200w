const state={stocks:[],insufficient:[],blacklist:[],watchlist:[],companies:new Map(),range:"below",query:""};
const $=s=>document.querySelector(s);
const fmt=n=>new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(n);
let deployedRevision=null;
async function checkForUpdate(){
  try{
    const response=await fetch(`version.json?t=${Date.now()}`,{cache:"no-store"});
    if(!response.ok)return;
    const {revision}=await response.json();
    if(deployedRevision&&revision&&revision!==deployedRevision){location.reload();return}
    deployedRevision=revision||deployedRevision;
  }catch(e){}
}
function weekLabel(value){
  if(!value)return "Unknown week"; const date=new Date(`${value.slice(0,10)}T12:00:00Z`);
  const day=date.getUTCDay()||7; date.setUTCDate(date.getUTCDate()+4-day);
  const year=date.getUTCFullYear(),start=new Date(Date.UTC(year,0,1));
  const week=Math.ceil((((date-start)/86400000)+1)/7);
  return `Week ${week}, ${year}`;
}

async function init(){
  try{
    const [res,blacklistRes,watchlistRes,companiesRes]=await Promise.all([fetch("data/stocks.json",{cache:"no-cache"}),fetch("data/blacklist.json",{cache:"no-cache"}),fetch("data/watchlist.json",{cache:"no-cache"}),fetch("data/nasdaq100.json",{cache:"no-cache"})]);
    if(!res.ok) throw new Error("Market data is unavailable");
    const data=await res.json(); state.stocks=data.stocks||[]; state.insufficient=data.insufficient_history||[];
    if(blacklistRes.ok)state.blacklist=await blacklistRes.json();
    if(watchlistRes.ok)state.watchlist=await watchlistRes.json();
    if(companiesRes.ok)state.companies=new Map(await companiesRes.json());
    const byName=new Map([...state.companies].map(([symbol,name])=>[name.toUpperCase(),symbol]));
    state.blacklist=[...new Set(state.blacklist.map(value=>state.companies.has(value.toUpperCase())?value.toUpperCase():byName.get(value.toUpperCase())).filter(Boolean))];
    state.watchlist=[...new Set(state.watchlist.map(value=>state.companies.has(value.toUpperCase())?value.toUpperCase():byName.get(value.toUpperCase())||value.toUpperCase()).filter(Boolean))];
    const dates=state.stocks.map(x=>x.updated).filter(Boolean).sort();
    $("#asof").textContent=dates.length?`Updated ${weekLabel(dates.at(-1))}`:"Awaiting first update";
    render(); renderWatchlist(); renderAllWatchlist(); renderInsufficient(); renderBlacklist();
  }catch(e){
    $("#stock-list").innerHTML=`<div class="empty"><p>No market data yet</p><small>Run the local update script to populate this page.</small></div>`;
    updateStats([]);
  }
}
function filtered(){
  return state.stocks.filter(s=>{
    if(state.blacklist.includes(s.symbol)||state.watchlist.includes(s.symbol)||!Number.isFinite(s.distance))return false;
    return inSelectedRange(s.distance)&&(!state.query||`${s.symbol} ${s.name}`.toLowerCase().includes(state.query));
  }).sort((a,b)=>Math.abs(a.distance)-Math.abs(b.distance));
}
function inSelectedRange(distance){
  if(!Number.isFinite(distance))return false;
  return state.range==="below"?distance<0:distance>=0&&distance<Number(state.range);
}
function render(){
  if(state.query){renderSearch();return}
  const rows=filtered(); updateStats(rows);
  $("#results-title").textContent="Signals";
  const rangeLabel=state.range==="below"?"below 200W":`0–${state.range}% above 200W`;
  $("#result-label").textContent=`${rows.length} stocks · ${rangeLabel}`;
  $("#stock-list").innerHTML=rows.length?rows.map(card).join(""):`<div class="empty"><p>No stocks in this range.</p><small>Try widening the near range.</small></div>`;
  renderAbove();
}
function renderSearch(){
  const matches=[...state.companies].filter(([symbol,name])=>`${symbol} ${name}`.toLowerCase().includes(state.query));
  $("#watch-section").hidden=true;
  $("#results-title").textContent="Search results"; $("#result-label").textContent=`${matches.length} stocks`;
  $("#stock-list").innerHTML=matches.length?matches.map(([symbol,name])=>searchResult(symbol,name)).join(""):`<div class="empty"><p>No match in the Nasdaq-100.</p><small>Check the symbol or company name.</small></div>`;
  $("#above-note").hidden=true; $("#watchlist-all-note").hidden=true; $("#history-note").hidden=true; $("#blacklist-note").hidden=true;
}
function searchResult(symbol,name){
  const stock=state.stocks.find(s=>s.symbol===symbol),young=state.insufficient.find(s=>s.symbol===symbol);
  const flags=[]; if(state.blacklist.includes(symbol))flags.push("Excluded"); if(state.watchlist.includes(symbol))flags.push("Watchlist");
  if(stock)return card(stock,flags.join(" · "));
  const status=young?`Limited history · ${young.weeks}/200 weeks`:"Awaiting scan";
  return `<article class="stock-card status-card"><div class="identity"><div class="ticker">${symbol}</div><div class="company"><strong>${name}</strong><span>${[status,...flags].filter(Boolean).join(" · ")}</span></div></div></article>`;
}
function updateStats(rows){
  $("#match-count").textContent=rows.length;
  $("#below-count").textContent=rows.filter(x=>x.distance<0).length;
  const eligible=new Set([...state.companies.keys(),...state.watchlist].filter(symbol=>!state.blacklist.includes(symbol)));
  $("#coverage").textContent=`${state.stocks.filter(s=>!state.blacklist.includes(s.symbol)).length}/${eligible.size}`;
}
function renderInsufficient(){
  const rows=state.insufficient.filter(s=>!state.blacklist.includes(s.symbol)); $("#history-note").hidden=!rows.length; if(!rows.length)return;
  $("#history-note").hidden=false; $("#history-count").textContent=rows.length;
  $("#history-list").innerHTML=rows.sort((a,b)=>b.weeks-a.weeks).map(s=>`<div class="history-row"><strong>${s.symbol}</strong><span>${s.name} · ${s.weeks}/200 weeks</span><small>Retry after ${weekLabel(s.retry_after)}</small></div>`).join("");
}
function renderBlacklist(){
  $("#blacklist-count").textContent=state.blacklist.length;
  $("#blacklist-list").innerHTML=state.blacklist.length?state.blacklist.map(symbol=>`<div class="blacklist-row"><strong>${symbol}</strong><span>${state.companies.get(symbol)||"Excluded from scanning"}</span><i>Not scanned</i></div>`).join(""):`<div class="blacklist-row empty-row"><span>No stocks are currently excluded</span></div>`;
}
function renderAbove(){
  const threshold=state.range==="below"?0:Number(state.range);
  const rows=state.stocks.filter(s=>!state.blacklist.includes(s.symbol)&&!state.watchlist.includes(s.symbol)&&Number.isFinite(s.distance)&&s.distance>=threshold&&(!state.query||`${s.symbol} ${s.name}`.toLowerCase().includes(state.query))).sort((a,b)=>a.distance-b.distance);
  $("#above-note").hidden=!rows.length; $("#above-count").textContent=rows.length;
  $("#above-list").innerHTML=rows.map(s=>`<div class="above-row"><strong>${s.symbol}</strong><span>${s.name}</span><b>+${s.distance.toFixed(2)}%</b></div>`).join("");
}
function card(s,flag=""){
  const d=s.distance; const below=d<0;
  const label=below?`${Math.abs(d).toFixed(1)}% below`:`${d.toFixed(1)}% above`;
  const width=Math.max(3,Math.min(100,50+d*5));
  return `<article class="stock-card">
    <div class="identity"><div class="ticker">${s.symbol}</div><div class="company"><strong>${s.name}</strong><span>200W · ${fmt(s.sma200)}${flag?` · ${flag}`:""}</span></div></div>
    <div class="price"><strong>${fmt(s.price)}</strong><span class="distance ${below?"below":""}">${label}</span></div>
    <div class="bar-wrap"><div class="bar"><i style="width:${width}%"></i></div><span>${weekLabel(s.updated)}</span></div>
  </article>`;
}
function renderWatchlist(){
  const rows=state.watchlist.map(symbol=>state.stocks.find(s=>s.symbol===symbol)).filter(stock=>stock&&inSelectedRange(stock.distance));
  $("#watch-section").hidden=state.query||!rows.length;
  if(state.query||!rows.length)return;
  $("#watch-count").textContent=`${rows.length} stocks`;
  $("#watch-list").innerHTML=rows.map(stock=>card(stock,state.blacklist.includes(stock.symbol)?"Excluded":"Watchlist")).join("");
}
function renderAllWatchlist(){
  const rows=state.watchlist.map(symbol=>({symbol,stock:state.stocks.find(s=>s.symbol===symbol)}));
  $("#watchlist-all-note").hidden=state.query||!rows.length;
  if(state.query||!rows.length)return;
  $("#watchlist-all-count").textContent=rows.length;
  $("#watchlist-all-list").innerHTML=rows.map(({symbol,stock})=>{
    const name=stock?.name||state.companies.get(symbol)||symbol;
    if(!stock||!Number.isFinite(stock.distance))return `<div class="above-row"><strong>${symbol}</strong><span>${name}</span><b class="pending">Awaiting scan</b></div>`;
    const below=stock.distance<0;
    return `<div class="above-row"><strong>${symbol}</strong><span>${name}</span><b class="${below?"below":""}">${below?"":"+"}${stock.distance.toFixed(2)}%</b></div>`;
  }).join("");
}
$("#thresholds").addEventListener("click",e=>{if(!e.target.dataset.value)return;document.querySelectorAll("#thresholds button").forEach(x=>x.classList.remove("active"));e.target.classList.add("active");state.range=e.target.dataset.value;render();renderWatchlist()});
$("#search").addEventListener("input",e=>{state.query=e.target.value.trim().toLowerCase();render();if(!state.query){renderWatchlist();renderAllWatchlist();renderInsufficient();renderBlacklist()}});
init();
checkForUpdate();
setInterval(checkForUpdate,30000);
