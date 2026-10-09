"use strict";

// ---- SVG gauge (semicircle with colored zones + needle) ------------------
const NS = "http://www.w3.org/2000/svg";
const CX = 100, CY = 105, R = 82;

function polar(a){ return [CX + R*Math.cos(a), CY + R*Math.sin(a)]; }
function angleOf(frac){ return Math.PI + Math.max(0,Math.min(1,frac))*Math.PI; }
function arcPath(a0, a1, r=R){
  const [x0,y0]=[CX+r*Math.cos(a0), CY+r*Math.sin(a0)];
  const [x1,y1]=[CX+r*Math.cos(a1), CY+r*Math.sin(a1)];
  const large = (a1-a0) > Math.PI ? 1 : 0;
  return `M ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1}`;
}
function el(tag, attrs){ const e=document.createElementNS(NS,tag);
  for(const k in attrs) e.setAttribute(k, attrs[k]); return e; }

class Gauge{
  constructor(cfg){
    this.cfg = cfg;
    const wrap = document.createElement("div");
    wrap.className = "gauge" + (cfg.primary ? " primary":"");
    const svg = el("svg",{viewBox:"0 0 200 118"});
    svg.appendChild(el("path",{d:arcPath(Math.PI,2*Math.PI),
      fill:"none",stroke:"#26313d","stroke-width":14,"stroke-linecap":"round"}));
    this.zones = el("g",{}); svg.appendChild(this.zones);
    this.markers = el("g",{}); svg.appendChild(this.markers);
    this.needle = el("line",{x1:CX,y1:CY,x2:CX,y2:CY-R+8,
      stroke:"#e8eef4","stroke-width":3,"stroke-linecap":"round"});
    svg.appendChild(this.needle);
    svg.appendChild(el("circle",{cx:CX,cy:CY,r:6,fill:"#e8eef4"}));
    wrap.appendChild(svg);
    this.val = document.createElement("div"); this.val.className="g-val";
    this.unit = document.createElement("div"); this.unit.className="g-unit";
    this.label = document.createElement("div"); this.label.className="g-label";
    this.label.textContent = cfg.label;
    this.unit.textContent = cfg.unit;
    wrap.appendChild(this.val); wrap.appendChild(this.unit); wrap.appendChild(this.label);
    this.root = wrap;
  }
  drawZones(zones){
    this.zones.innerHTML="";
    const span = this.cfg.max - this.cfg.min;
    for(const z of zones){
      const a0=angleOf((z.from-this.cfg.min)/span), a1=angleOf((z.to-this.cfg.min)/span);
      if(a1<=a0) continue;
      this.zones.appendChild(el("path",{d:arcPath(a0,a1),fill:"none",
        stroke:z.color,"stroke-width":14,"stroke-linecap":"butt",opacity:.9}));
    }
  }
  drawMarkers(markers){
    this.markers.innerHTML="";
    const span=this.cfg.max-this.cfg.min;
    for(const m of markers){
      const a=angleOf((m.value-this.cfg.min)/span);
      const [x0,y0]=polar(a), [xi,yi]=[CX+(R-16)*Math.cos(a),CY+(R-16)*Math.sin(a)];
      this.markers.appendChild(el("line",{x1:xi,y1:yi,x2:x0,y2:y0,
        stroke:m.color,"stroke-width":3,"stroke-dasharray":m.dash||"0"}));
    }
  }
  set(value, text){
    const frac=(value-this.cfg.min)/(this.cfg.max-this.cfg.min);
    const a=angleOf(frac);
    const [x,y]=[CX+(R-8)*Math.cos(a), CY+(R-8)*Math.sin(a)];
    this.needle.setAttribute("x2",x); this.needle.setAttribute("y2",y);
    this.val.textContent = text!==undefined?text:value;
  }
}

// ---- gauge definitions ----------------------------------------------------
const G = {};
function buildGauges(s){
  const host=document.getElementById("gauges"); host.innerHTML="";
  const z=s.g_zones;
  const defs=[
    {key:"glucose",label:"Blood glucose",unit:"mmol/L",min:0,max:12,primary:true,
     zones:st=>[
       {from:0,to:z.death,color:"var(--red)"},
       {from:z.death,to:z.crit_low,color:"var(--orange)"},
       {from:z.crit_low,to:z.normal_low,color:"var(--amber)"},
       {from:z.normal_low,to:z.hyper_high,color:"var(--green)"},
       {from:z.hyper_high,to:12,color:"var(--amber)"}]},
    {key:"basal_rate",label:"Basal rate",unit:"U/h",min:0,max:s.hard_ceiling,
     zones:st=>[{from:0,to:st.factory_max,color:"var(--green)"},
                {from:st.factory_max,to:s.hard_ceiling,color:"var(--red)"}],
     markers:st=>[{value:st.max_basal_limit,color:"#fff",dash:"0"},
                  {value:st.factory_max,color:"var(--green)",dash:"3 3"}]},
    {key:"plasma_insulin",label:"Plasma insulin",unit:"U",min:0,max:20,
     zones:st=>[{from:0,to:4,color:"var(--green)"},{from:4,to:8,color:"var(--amber)"},
                {from:8,to:20,color:"var(--red)"}]},
    {key:"reservoir",label:"Reservoir",unit:"U",min:0,max:300,
     zones:st=>[{from:0,to:20,color:"var(--red)"},{from:20,to:60,color:"var(--amber)"},
                {from:60,to:300,color:"var(--green)"}]},
    {key:"heart_rate",label:"Heart rate",unit:"bpm",min:0,max:180,
     zones:st=>[{from:0,to:40,color:"var(--red)"},{from:40,to:60,color:"var(--amber)"},
                {from:60,to:100,color:"var(--green)"},{from:100,to:140,color:"var(--amber)"},
                {from:140,to:180,color:"var(--red)"}]},
    {key:"spo2",label:"SpO₂",unit:"%",min:70,max:100,
     zones:st=>[{from:70,to:85,color:"var(--red)"},{from:85,to:92,color:"var(--amber)"},
                {from:92,to:100,color:"var(--green)"}]},
  ];
  for(const d of defs){
    const g=new Gauge(d); G[d.key]={gauge:g,def:d}; host.appendChild(g.root);
    g.drawZones(d.zones(s));
  }
}

// ---- flags / scoreboard ---------------------------------------------------
const KILL=new Set(["F7","F8","F9"]);
function renderScore(s){
  const body=document.getElementById("scoreBody");
  const empty=document.getElementById("scoreEmpty");
  body.innerHTML="";
  const rows=s.scoreboard||[];
  empty.style.display = rows.length? "none":"block";
  const ids=s.flag_defs.map(f=>f.id);
  rows.forEach((r,i)=>{
    const tr=document.createElement("tr"); if(i===0&&r.count>0) tr.className="rank1";
    const earned=new Set(r.earned), ver=new Set(r.verified);
    const dots=ids.map(id=>{
      let c="fdot"; if(earned.has(id)) c+= KILL.has(id)?" on kill":" on";
      if(ver.has(id)) c+=" ver";
      return `<span class="${c}" title="${id}">${id.slice(1)}</span>`;
    }).join("");
    tr.innerHTML=`<td>${escapeHtml(r.name)}</td>
      <td><div class="flag-dots">${dots}</div></td><td>${r.count}</td>`;
    body.appendChild(tr);
  });
}
function renderEvents(s){
  const ul=document.getElementById("eventList"); ul.innerHTML="";
  (s.events||[]).forEach(e=>{
    const li=document.createElement("li"); li.className="ev-"+e.kind;
    li.innerHTML=`<span class="ev-name">${escapeHtml(e.name)}</span> ${escapeHtml(e.text)}`;
    ul.appendChild(li);
  });
}
function escapeHtml(x){return String(x).replace(/[&<>"]/g,c=>(
  {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}

// ---- indicators -----------------------------------------------------------
function ind(id, val, cls){
  const box=document.getElementById(id); box.textContent=val;
  const wrap=box.closest(".ind"); wrap.className="ind "+(cls||"");
}

// ---- state update ---------------------------------------------------------
let built=false;
function update(s){
  if(!built){ buildGauges(s); built=true; }
  document.getElementById("devName").textContent=s.device_name;

  G.glucose.gauge.set(s.glucose, s.glucose.toFixed(1));
  G.basal_rate.gauge.set(s.basal_rate, s.basal_rate.toFixed(2));
  G.basal_rate.gauge.drawMarkers(G.basal_rate.def.markers(s));
  G.plasma_insulin.gauge.set(s.plasma_insulin, s.plasma_insulin.toFixed(1));
  G.reservoir.gauge.set(s.reservoir, Math.round(s.reservoir));
  G.heart_rate.gauge.set(s.heart_rate, Math.round(s.heart_rate));
  G.spo2.gauge.set(s.spo2, Math.round(s.spo2));

  const banner=document.getElementById("statusBanner");
  banner.className="status status-"+s.status.replace(/\s/g,"-");
  document.getElementById("statusText").textContent=s.status;
  document.getElementById("deathReason").textContent =
    s.deceased? s.death_reason : "";

  // play the flatline once, on the transition into deceased (unless muted)
  if(prevDeceased !== undefined && s.deceased && !prevDeceased && !muteAudio.checked){
    try{ deathAudio.currentTime = 0; deathAudio.play().catch(()=>{}); }catch(e){}
  }
  prevDeceased = s.deceased;

  ind("indTherapy", s.therapy_active?"ACTIVE":"STOPPED", s.therapy_active?"good":"warn");
  ind("indUnlock", s.maintenance_unlocked?"UNLOCKED":"locked", s.maintenance_unlocked?"bad":"good");
  ind("indAlarm", s.alarms_silenced?"SILENCED":"active", s.alarms_silenced?"bad":"good");
  ind("indOcc", s.occlusion?"YES":"no", s.occlusion?"bad":"good");

  renderScore(s); renderEvents(s);
}

// ---- death sound ----------------------------------------------------------
// Same flatline as the Pi speaker, played in the dashboard browser too.
// Browsers block autoplay until the page has had a user gesture, so we "prime"
// the audio on the first click/keypress (the facilitator will click Reset etc.).
const deathAudio = new Audio("/assets/flatline.wav");
deathAudio.preload = "auto";
let audioPrimed = false, prevDeceased;
function primeAudio(){
  if(audioPrimed) return;
  audioPrimed = true;
  deathAudio.play().then(()=>{ deathAudio.pause(); deathAudio.currentTime = 0; }).catch(()=>{});
}
["pointerdown","keydown"].forEach(ev => window.addEventListener(ev, primeAudio));

const muteAudio = document.getElementById("muteAudio");
try{ muteAudio.checked = localStorage.getItem("medsim.mute") === "1"; }catch(e){}
muteAudio.onchange = () => {
  try{ localStorage.setItem("medsim.mute", muteAudio.checked ? "1" : "0"); }catch(e){}
  if(muteAudio.checked){ try{ deathAudio.pause(); deathAudio.currentTime = 0; }catch(e){} }
};

// ---- websocket ------------------------------------------------------------
let ws;
function connect(){
  ws=new WebSocket("ws://"+location.host+"/ws");
  ws.onopen=()=>setConn(true);
  ws.onclose=()=>{setConn(false); setTimeout(connect,1000);};
  ws.onmessage=e=>{ try{update(JSON.parse(e.data));}catch(err){console.error(err);} };
}
function setConn(ok){
  document.getElementById("connDot").className="dot"+(ok?" ok":"");
  document.getElementById("connText").textContent=ok?"live":"reconnecting…";
}
function send(o){ if(ws&&ws.readyState===1) ws.send(JSON.stringify(o)); }

// ---- controls -------------------------------------------------------------
document.getElementById("btnReset").onclick=()=>send({cmd:"reset"});
const auto=document.getElementById("autoReset"), autoSec=document.getElementById("autoResetSec");
function pushAuto(){ send({cmd:"autoreset", value: auto.checked? parseInt(autoSec.value)||30 : 0}); }
auto.onchange=pushAuto; autoSec.onchange=pushAuto;

if(new URLSearchParams(location.search).has("debug")){
  const dp=document.getElementById("debugPanel"); dp.classList.remove("hidden");
  dp.querySelectorAll("button").forEach(b=>b.onclick=()=>
    send({cmd:"debug",op:b.dataset.op,value:parseFloat(b.dataset.val)}));
}

connect();
