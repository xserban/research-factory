/* Explore page: sentence query, rings with semantic zoom, DNA wall, compare tray, trail.
   Payloads: shell (works, cites, sets), explore (per-work DNA values with quotes, layer order). */
HUB.load(['shell', 'explore']).then(d => {
HUB.init(d.shell);
const main = HUB.mount({ page: 'explore', crumb: 'Explore' });
const RF = { works: d.explore.works.map(x => ({ ...x, ...x.dna, cic: x.cited_here || 0 })), layer_order: d.explore.layer_order };
if (!document.getElementById('xp-style')) { const st = document.createElement('style'); st.id = 'xp-style'; st.textContent = String.raw`
.xhead{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,6fr);gap:32px;align-items:end;padding:6px 0 18px}
.xhead .lead{max-width:46ch;font-size:25px}
.xhead .lead b{color:var(--fg)}
.xhead .lead small{display:block;margin-top:8px;font:400 var(--t-s)/1.45 var(--f-ui);color:var(--dim)}

/* sentence query */
.sentence{padding:18px 22px 14px;margin-bottom:14px;position:relative}
.sq{font:400 24px/2 var(--f-display);margin:0}
.slot{position:relative;display:inline-block;vertical-align:baseline}
.slot .face{font:inherit;color:var(--mut);background:transparent;border:0;border-bottom:2px dotted var(--dim);padding:0 2px;cursor:pointer;line-height:1.25}
.slot .face:hover{color:var(--fg);border-bottom-color:var(--mut)}
.slot.on .face{color:var(--fg);border-bottom:2px solid var(--acc);background:var(--acc-soft);border-radius:4px 4px 0 0;padding:0 6px}
.slot .face sup{font:500 11px var(--f-mono);color:var(--dim);margin-left:4px;vertical-align:super}
.slot .face .car{display:inline-block;width:7px;height:7px;border-right:1.5px solid var(--dim);border-bottom:1.5px solid var(--dim);transform:rotate(45deg) translateY(-3px);margin-left:7px}
.spop{position:absolute;left:0;top:calc(100% + 6px);z-index:40;min-width:260px;max-width:min(420px,88vw);max-height:340px;overflow:auto;background:var(--raised);border-radius:var(--r);box-shadow:var(--shadow);padding:6px;font:400 var(--t-s)/1.3 var(--f-ui)}
.spop[hidden]{display:none}
.spop input{width:100%;margin:2px 0 6px;background:var(--bg)}
.spop .opt{display:grid;grid-template-columns:1fr auto;gap:2px 12px;width:100%;text-align:left;border:0;background:transparent;color:var(--fg);padding:7px 9px;border-radius:5px;cursor:pointer;font:inherit;position:relative}
.spop .opt:hover,.spop .opt:focus-visible{background:var(--line)}
.spop .opt[aria-selected=true]{box-shadow:inset 2px 0 0 var(--acc)}
.spop .opt[disabled]{color:var(--dim);cursor:default}
.spop .opt .c{font:500 12px var(--f-mono);color:var(--mut);text-align:right}
.spop .opt .obar{grid-column:1/3;height:2px;background:var(--hair);border-radius:2px;overflow:hidden}
.spop .opt .obar i{display:block;height:100%;background:var(--mut)}
.spop .hd{font-size:11px;color:var(--dim);padding:4px 9px 6px}
.sq-res{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;margin:2px 0 0;font-size:var(--t-s);color:var(--mut)}
.sq-res b{color:var(--fg);font-size:var(--t-m);font-weight:600}

/* stage */
.stage{position:relative}
.xbar{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;margin-bottom:10px}
.xbar .grow{flex:1}
.trail{display:flex;gap:4px;align-items:center;flex-wrap:wrap;justify-content:flex-end;max-width:100%}
.trail .tl{font-size:11px;color:var(--dim);margin-right:2px}
.trail .chip{padding:5px 8px;max-width:210px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;display:inline-block}
.trail .chip[aria-current=step]{background:var(--acc-soft);box-shadow:inset 0 0 0 1px var(--acc);color:var(--fg)}
.trail .sep{color:var(--dim);font-size:11px}
.cv{position:relative;height:clamp(560px,80vh,820px);background:var(--bg);border-radius:var(--r);overflow:hidden;box-shadow:inset 0 0 0 1px var(--hair);touch-action:none;outline:none}
.cv:focus-visible{box-shadow:inset 0 0 0 2px var(--acc)}
.cv canvas{position:absolute;left:0;top:0;width:100%;height:100%;display:block}
.cv .ctl{position:absolute;left:10px;top:10px;display:flex;flex-direction:column;gap:4px}
.cv .ctl .btn{width:34px;padding:0;justify-content:center;font-size:17px;background:var(--raised)}
.cv .zi{position:absolute;left:10px;bottom:10px;font-size:var(--t-xs);color:var(--mut);background:color-mix(in srgb,var(--surface) 88%,transparent);padding:6px 9px;border-radius:6px;pointer-events:none;max-width:60%}
.cv .zi b{color:var(--fg);font-weight:500}
.cv #mm{position:absolute;left:auto;top:auto;right:10px;bottom:10px;width:132px;height:132px;border-radius:8px;background:color-mix(in srgb,var(--surface) 92%,transparent);cursor:pointer}
.cv .hint{position:absolute;right:10px;top:10px;font-size:var(--t-xs);color:var(--dim);text-align:right;pointer-events:none;max-width:260px}
.cv .empty{position:absolute;inset:0;display:none;align-items:center;justify-content:center;text-align:center;pointer-events:none}
.cv .empty div{background:var(--surface);padding:16px 20px;border-radius:var(--r);max-width:44ch;font-size:var(--t-s);color:var(--mut)}
.cv .empty b{display:block;color:var(--fg);font-size:var(--t-m);margin-bottom:4px}
.legend{display:flex;flex-wrap:wrap;gap:6px 8px;align-items:center;margin:12px 0 4px}
.legend .chip{background:transparent;padding:4px 8px 4px 4px}
.legend .chip:hover{background:var(--raised)}
.legend .sz{margin-left:auto;display:flex;gap:10px;align-items:center;font-size:var(--t-xs);color:var(--mut)}
.legend .sz svg{vertical-align:middle}
.foot{margin:18px 0 0}

/* DNA */
.dna{display:inline-flex;gap:1px;vertical-align:middle}
.dna i{display:block;width:var(--sw,14px);height:var(--sh,10px);border-radius:2px;background:var(--c)}
.tdna{display:grid;grid-template-columns:auto 1fr;gap:3px 8px;margin-top:6px;font-size:var(--t-xs);align-items:center}
.tdna i{display:block;width:10px;height:10px;border-radius:2px}
.tdna span{color:var(--mut)}
.tdna b{font-weight:500;color:var(--fg)}
.tip .t1{font-weight:600;font-size:var(--t-s);margin-bottom:2px}
.tip .t2{color:var(--mut);font-size:var(--t-xs);margin-bottom:6px}
.tip .t3{color:var(--dim);font-size:11px;margin-top:6px}

/* DNA wall */
.wall{height:clamp(560px,80vh,820px);overflow:auto;background:var(--surface);border-radius:var(--r);position:relative}
.wall[hidden]{display:none}
.wall .wh{position:sticky;top:0;z-index:3;background:var(--surface);display:flex;align-items:flex-end;gap:0;padding:10px 12px 8px;box-shadow:0 1px 0 var(--line)}
.wall .wh .sb{width:64px;flex:none;font:500 11px var(--f-ui);color:var(--mut);background:transparent;border:0;padding:4px 0;text-align:left;cursor:pointer;border-radius:4px}
.wall .wh .sb:hover{color:var(--fg)}
.wall .wh .sb[aria-sort]{color:var(--fg);box-shadow:inset 0 -2px 0 var(--acc)}
.wall .wh .sb small{color:var(--dim);font-size:10px}
.wall .wh .tc{flex:1;font-size:11px;color:var(--dim);padding-left:10px}
.wall .wk{padding:8px 12px 0;font-size:var(--t-xs);color:var(--mut)}
.wall .wk summary{cursor:pointer}
.wall .wk .kg{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;padding:8px 0;max-width:110ch}
.wall .wk .kg b{font-weight:500;color:var(--fg)}
.wall .wk .kg span{display:inline-flex;align-items:center;gap:4px;margin-right:12px;white-space:nowrap}
.wall .wk .kg i{display:inline-block;width:9px;height:9px;border-radius:2px}
.wall .wk .kg div{line-height:1.8}
.wr{display:flex;align-items:center;gap:0;padding:0 12px;height:17px;cursor:pointer;font-size:12px;color:var(--mut)}
.wr:hover,.wr:focus-visible{background:var(--raised);color:var(--fg)}
.wr[aria-selected=true]{background:var(--acc-soft)}
.wr .dna{flex:none;gap:0}
.wr .dna i{width:64px;height:13px;border-radius:0;border-right:1px solid var(--surface)}
.wr .tt{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-left:10px}
.wr .m{font:400 11px var(--f-mono);color:var(--dim);width:70px;text-align:right;flex:none}
.wr .ci{font:400 11px var(--f-mono);width:38px;text-align:right;flex:none;color:var(--mut)}
.wr .pb{width:22px;flex:none;border:0;background:transparent;color:var(--dim);cursor:pointer;font-size:12px;padding:0}
.wr .pb:hover,.wr .pb.on{color:var(--acc)}
.wall .empty2{padding:40px;color:var(--mut);text-align:center}

/* compare tray */
.tray{position:fixed;left:var(--rail);right:0;bottom:0;z-index:30;background:var(--surface);box-shadow:0 -8px 32px rgba(0,0,0,.35);max-height:58vh;overflow:auto;padding:0 24px 12px}
.tray .th{position:sticky;top:0;background:var(--surface);z-index:2;display:flex;gap:12px;align-items:center;padding:10px 0;flex-wrap:wrap}
.tray .th .h3{white-space:nowrap}
.tray .th .grow{flex:1}
.tray .tb{display:grid;gap:0 18px;font-size:var(--t-s)}
.tray .rl{color:var(--dim);font-size:var(--t-xs);padding:8px 0;border-top:1px solid var(--hair)}
.tray .rl.d{color:var(--fg)}
.tray .rl .g{font-family:var(--f-mono)}
.tray .cl{padding:8px 0;border-top:1px solid var(--hair);min-width:0}
.tray .cl.hd{border-top:0;padding-top:0}
.tray .cl.diff .v{font-weight:600;background:var(--raised);border-radius:4px;padding:1px 6px;margin-left:-6px}
.tray .cl .v{display:inline-block}
.tray .cl q{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;font:italic 400 var(--t-s)/1.4 var(--f-display);color:var(--mut);margin-top:3px;quotes:'\201C' '\201D'}
.tray .cl.diff q{color:var(--fg)}
.tray .ptitle{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-weight:600;cursor:pointer}
.tray .ptitle:hover{text-decoration:underline}
.badge{display:inline-flex;width:18px;height:18px;border-radius:50%;background:var(--acc);color:var(--acc-ink);font:600 11px var(--f-ui);align-items:center;justify-content:center;margin-right:6px;flex:none}
.tray .acts{display:flex;gap:6px;margin-top:6px;flex-wrap:wrap}
.tray .acts .btn{height:26px;padding:0 9px;font-size:var(--t-xs)}
.tray .lower{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:14px}
.tray .lower ul{margin:6px 0 0;padding:0;list-style:none}
.tray .lower li{padding:5px 0;border-top:1px solid var(--hair);display:flex;gap:10px;align-items:baseline}
.tray .lower li .s{font:500 12px var(--f-mono);color:var(--mut);white-space:nowrap}
.tray .lower li a{color:var(--fg);text-decoration:none;cursor:pointer}
.tray .lower li a:hover{text-decoration:underline}
.tray .slim{display:flex;gap:4px 12px;align-items:center;flex-wrap:wrap;padding:9px 0;font-size:var(--t-s);color:var(--mut)}
.srsc{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}

@media (max-width:900px){
  .xhead{grid-template-columns:1fr}
  .xhead .lead{font-size:21px}
  .sq{font-size:21px;line-height:2.1}
  .tray .lower{grid-template-columns:1fr}
}
@media (max-width:760px){
  .tray{left:0;bottom:52px;padding:0 14px 10px;max-height:50vh}
  .tray .tb{overflow-x:auto}
  .cv{height:520px}.wall{height:520px}
  .cv #mm{width:72px;height:72px}
  .cv .ctl{flex-direction:row}.cv .ctl .btn{height:30px}
  .cv .hint{display:none}
  .wr .dna i{width:34px}.wall .wh .sb{width:34px;font-size:9px}.wr .m,.wr .ci{display:none}
  .legend .sz{margin-left:0}
  .trail{justify-content:flex-start}
}
`; document.head.appendChild(st); }
const {esc,fmt,HUMAN,LAYERS,byId,citesOut,citesIn,cssv,pretty,humanLabel,layerLabel}=HUB;
const REDUCED=matchMedia('(prefers-reduced-motion: reduce)').matches;

/* ======================= data prep (all computed) ======================= */
const MN=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const MY0=Math.min(...RF.works.map(w=>w.year||9999));
const mIdx=w=>((w.year||MY0)-MY0)*12+((w.month||1)-1);
const NM=Math.max(...RF.works.map(mIdx))+1;
const mLabel=i=>MN[i%12]+' '+(MY0+Math.floor(i/12));
const eraOf=i=>{const y=MY0+Math.floor(i/12);return y+'-H'+((i%12)<6?1:2)};
const eraLabel=e=>{const[y,h]=e.split('-H');return(h==='1'?'Jan–Jun ':'Jul–Dec ')+y};
const ERAS=[];for(let i=0;i<NM;i++){const e=eraOf(i);if(!ERAS.includes(e))ERAS.push(e)}
const RINGS=[['core','Core',36,150],['benchmark','Benchmark',150,240],['applied','Applied',240,370],['adjacent','Adjacent',370,440],['outer','Outer',440,500]];
const RR=500;
const ringOf=l=>['core','benchmark','applied','adjacent'].includes(l)?l:'outer';
const hash32=s=>{let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)}return(h>>>0)/4294967296};
const D=RF.works.map((w,i)=>({w,i,id:w.id,title:w.title,cic:w.cic||0,mi:mIdx(w),tech:HUB.val(w,'technique'),arch:HUB.val(w,'architecture'),span:HUB.val(w,'span'),hum:HUB.val(w,'human'),layer:w.layer,ring:ringOf(w.layer),m:true}));
D.forEach(d=>{d.era=eraOf(d.mi);d.rr=3.2+1.15*Math.sqrt(d.cic)});
const DB=new Map(D.map(d=>[d.id,d]));
/* sectors = technique: 7 named values, then everything else (incl. 'other' and unclassified) */
const dist=k=>{const c=new Map();for(const w of RF.works){const v=HUB.val(w,k);if(v)c.set(v,(c.get(v)||0)+1)}return[...c.entries()].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]))};
const techCounts=dist('technique').filter(([v])=>v!=='other');
const TOP=techCounts.slice(0,7).map(a=>a[0]);
const NICE={'training-finetuning-rl':'Training / RL','code-execution-tools':'Code execution','retrieval-grounding':'Retrieval','memory-skills':'Memory & skills','iterative-loop':'Iterative loop','tree-search':'Tree search','multi-agent':'Multi-agent'};
const SECT=[...TOP.map(v=>({key:v,label:NICE[v]||pretty(v)})),{key:'~rest',label:'Other & smaller'}];
D.forEach(d=>{d.sec=TOP.includes(d.tech)?d.tech:'~rest'});
SECT.forEach(s=>{s.n=D.filter(d=>d.sec===s.key).length});
(function layout(){
  const N=D.length,GAP=.03;let a=-Math.PI/2;
  SECT.forEach(s=>{const wt=.5*s.n/N+.5/SECT.length;s.a0=a+GAP/2;s.a1=a+wt*2*Math.PI-GAP/2;s.am=(s.a0+s.a1)/2;a+=wt*2*Math.PI});
  const SK=Object.fromEntries(SECT.map(s=>[s.key,s]));
  for(const d of D){const s=SK[d.sec],b=RINGS.find(r=>r[0]===d.ring);d.s=s;d.b=b;
    d.tA=s.a0+(s.a1-s.a0)*(.05+.9*(d.mi+.5)/NM);d.tR=b[2]+(b[3]-b[2])*(.1+.8*hash32(d.id));
    d.ang=d.tA;d.rad=d.tR;d.x=d.rad*Math.cos(d.ang);d.y=d.rad*Math.sin(d.ang)}
  for(let it=0;it<150;it++){
    const cell=34,g=new Map();for(const d of D){const k=Math.floor(d.x/cell)+','+Math.floor(d.y/cell);(g.get(k)||g.set(k,[]).get(k)).push(d)}
    for(const d of D){const cx=Math.floor(d.x/cell),cy=Math.floor(d.y/cell);
      for(let ox=-1;ox<=1;ox++)for(let oy=-1;oy<=1;oy++){const l=g.get((cx+ox)+','+(cy+oy));if(!l)continue;
        for(const e of l){if(e.i<=d.i)continue;const dx=e.x-d.x,dy=e.y-d.y,dd=Math.hypot(dx,dy)||.01,mn=(d.rr+e.rr)*.95+1.2;
          if(dd<mn){const p=(mn-dd)/2/dd;d.x-=dx*p;d.y-=dy*p;e.x+=dx*p;e.y+=dy*p}}}}
    for(const d of D){let r=Math.hypot(d.x,d.y),a=Math.atan2(d.y,d.x);if(a<-Math.PI/2-.2)a+=2*Math.PI;
      a+=(d.tA-a)*.06;r+=(d.tR-r)*.012;
      const am=(d.rr+1)/Math.max(r,20);a=Math.max(d.s.a0+am,Math.min(d.s.a1-am,a));
      r=Math.max(d.b[2]+d.rr*.6,Math.min(d.b[3]-d.rr*.6,r));d.x=r*Math.cos(a);d.y=r*Math.sin(a)}
  }
  for(const d of D){d.rad=Math.hypot(d.x,d.y);d.ang=Math.atan2(d.y,d.x)}
})();

/* ======================= DNA: six segments ======================= */
const ORD={technique:dist('technique').map(a=>a[0]),architecture:dist('architecture').map(a=>a[0]),span:dist('span').map(a=>a[0]),human:HUMAN.map(h=>h[0]),layer:RF.layer_order&&RF.layer_order.length?[...RF.layer_order,'unlayered']:LAYERS.map(l=>l[0]),era:ERAS};
const SEGS=[
 {k:'technique',l:'Technique',s:'Tech',get:d=>d.tech,lab:v=>pretty(v),h0:20},
 {k:'architecture',l:'Architecture',s:'Arch',get:d=>d.arch,lab:v=>pretty(v),h0:150},
 {k:'span',l:'Automated span',s:'Span',get:d=>d.span,lab:v=>pretty(v),h0:280},
 {k:'human',l:'Human role',s:'Human',get:d=>d.hum,lab:v=>humanLabel(v)},
 {k:'layer',l:'Layer',s:'Layer',get:d=>d.layer,lab:v=>layerLabel(v)},
 {k:'era',l:'Era (half-year)',s:'Era',get:d=>d.era,lab:v=>eraLabel(v)},
];
const hex=h=>{h=h.trim();if(h[0]!=='#')return[128,128,128];if(h.length===4)h='#'+[...h.slice(1)].map(c=>c+c).join('');return[1,3,5].map(i=>parseInt(h.substr(i,2),16))};
const lerpC=(a,b,t)=>{const A=hex(a),B=hex(b);return'rgb('+A.map((x,i)=>Math.round(x+(B[i]-x)*t)).join(',')+')'};
let SC={};
function segColor(k,v){
  if(v==null)return SC.nul;
  if(k==='human')return HUB.humanColor(v);
  if(k==='layer')return HUB.layerColor(v);
  if(k==='era')return lerpC(SC.s2,SC.s4,ORD.era.indexOf(v)/Math.max(1,ORD.era.length-1));
  const seg=SEGS.find(s=>s.k===k),i=ORD[k].indexOf(v),light=document.documentElement.dataset.theme==='light';
  const hue=(seg.h0+i*137.508)%360;return light?`hsl(${hue} 52% ${i%2?36:46}%)`:`hsl(${hue} 56% ${i%2?58:70}%)`;
}
function refreshColors(){SC={nul:cssv('--h-null'),s2:cssv('--seq-2'),s4:cssv('--seq-4')}}
const dnaHTML=(d,sw=14,sh=10)=>`<span class="dna" style="--sw:${sw}px;--sh:${sh}px">${SEGS.map(s=>`<i style="--c:${segColor(s.k,s.get(d))}"></i>`).join('')}</span>`;
const segName=(s,v)=>v==null?'not coded':s.lab(v);
const tipDNA=d=>`${dnaHTML(d,18,12)}<div class="tdna">${SEGS.map(s=>`<i style="background:${segColor(s.k,s.get(d))}"></i><span>${s.l} · <b>${esc(segName(s,s.get(d)))}</b></span>`).join('')}</div>`;

/* ======================= state ======================= */
const ST={t:'',h:'',l:'',s:'',r:'in',x:'',view:'rings',col:'human',pins:[],sim:'',sort:[],sec:'',o:''};
const SLOTKEYS=['t','h','l','s','r','x'];
const sk=v=>v==null?'∅':v;
function pass(d,skip){
  if(skip!=='t'&&ST.t&&sk(d.tech)!==ST.t)return false;
  if(skip!=='h'&&ST.h&&sk(d.hum)!==ST.h)return false;
  if(skip!=='l'&&ST.l&&d.ring!==ST.l)return false;
  if(skip!=='s'&&ST.s!==''&&d.mi<+ST.s)return false;
  if(skip!=='x'&&ST.x){if(d.id===ST.x)return false;const lst=(ST.r==='in'?citesOut:citesIn).get(d.id)||[];if(!lst.includes(ST.x))return false}
  return true;
}
const anyFilter=()=>!!(ST.t||ST.h||ST.l||ST.s!==''||ST.x);
const ROLE={none:'is absent','sets-goal':'sets the goal','reviews-or-approves':'reviews or approves','expert-feedback-in-loop':'gives expert feedback',collaborator:'collaborates','runs-physical-steps':'runs physical steps','∅':'is not coded'};
const techVals=[...ORD.technique,'∅'];
const SLOT={
 t:{any:'any technique',vals:()=>techVals,label:v=>v==='∅'?'not coded':pretty(v),get:d=>sk(d.tech)},
 h:{any:'any role',vals:()=>[...ORD.human,'∅'],label:v=>ROLE[v],get:d=>sk(d.hum)},
 l:{any:'any layer',vals:()=>RINGS.map(r=>r[0]),label:v=>v==='outer'?'outer (background, off-topic, unlayered)':v,get:d=>d.ring},
 s:{any:'any month',vals:()=>Array.from({length:NM},(_,i)=>String(i)),label:v=>mLabel(+v),get:d=>String(d.mi)},
};
function counts(key){
  const S=D.filter(d=>pass(d,key));const c=new Map();
  if(key==='s'){const a=Array(NM).fill(0);for(const d of S)a[d.mi]++;let r=0;for(let i=NM-1;i>=0;i--){r+=a[i];c.set(String(i),r)}}
  else if(key==='x'){for(const d of S){for(const id of((ST.r==='in'?citesOut:citesIn).get(d.id)||[]))c.set(id,(c.get(id)||0)+1)}}
  else if(key==='r'){let a=0,b=0;for(const d of S){if((citesOut.get(d.id)||[]).length)a++;if((citesIn.get(d.id)||[]).length)b++}c.set('in',a);c.set('by',b)}
  else for(const d of S)c.set(SLOT[key].get(d),(c.get(SLOT[key].get(d))||0)+1);
  return{c,total:S.length};
}
function options(key){
  const{c,total}=counts(key);
  if(key==='r')return{total,opts:[{v:'in',label:'citing',n:c.get('in')},{v:'by',label:'cited by',n:c.get('by')}],any:null};
  if(key==='x'){const o=[...c.entries()].filter(([id])=>DB.has(id)).map(([id,n])=>({v:id,label:DB.get(id).title,n})).sort((a,b)=>b.n-a.n||a.label.localeCompare(b.label));
    return{total,opts:o,any:'any paper'}}
  const o=SLOT[key].vals().map(v=>({v,label:SLOT[key].label(v),n:c.get(v)||0}));
  return{total,opts:o,any:SLOT[key].any};
}
const faceText=key=>{
  const v=ST[key];
  if(key==='r')return ST.r==='in'?'citing':'cited by';
  if(key==='x')return v?(DB.get(v)?'“'+DB.get(v).title.replace(/:.*/,'').slice(0,34)+(DB.get(v).title.length>34?'…':'')+'”':'any paper'):'any paper';
  return v!==''&&v!=null&&(v||key==='s')?SLOT[key].label(v):SLOT[key].any;
};

/* ======================= sentence UI ======================= */
const $=s=>document.querySelector(s);
const SIMTXT0='Score = identical values across the six DNA squares (a field that is not coded never counts) + papers in this review that both cite';
const root=document.createElement('div');
root.innerHTML=`
<div class="xhead">
  <div id="ph"></div>
  <p class="lead" id="lead"></p>
</div>
<section class="sentence card" aria-label="Sentence query">
  <p class="sq" id="sq">Show <span data-s="t"></span> systems where the ${HUB.term('human','human')} <span data-s="h"></span>, in <span data-s="l"></span> papers, since <span data-s="s"></span>, <span data-s="r"></span> <span data-s="x"></span>.</p>
  <p class="sq-res" id="sqres"></p>
</section>
<div id="sh"></div>
<section class="stage" aria-label="Field map">
  <div class="xbar">
    <div class="seg" role="group" aria-label="View"><button data-view="rings" aria-pressed="true">Rings</button><button data-view="wall">DNA wall</button></div>
    <div class="seg" role="group" aria-label="Colour" id="colseg"><button data-col="human">Colour: human role</button><button data-col="era">Era</button><button data-col="none">None</button></div>
    <span class="grow"></span>
    <nav class="trail" id="trail" aria-label="Trail of steps"></nav>
  </div>
  <div class="cv" id="cv" tabindex="0" role="application" aria-label="Rings of the field. Plus and minus zoom, arrows pan, zero fits, brackets step through sectors, comma and full stop step through papers, P pins the selected paper, Enter opens it.">
    <canvas id="c"></canvas>
    <div class="ctl"><button class="btn" id="zin" aria-label="Zoom in">+</button><button class="btn" id="zout" aria-label="Zoom out">−</button><button class="btn" id="zfit" aria-label="Fit whole field" style="font-size:12px">Fit</button></div>
    <div class="hint">Wheel or pinch to zoom · drag to pan · click a sector label to fly there · comma and full stop step through papers</div>
    <div class="zi" id="zi"></div>
    <canvas id="mm" aria-label="Minimap" width="132" height="132"></canvas>
    <div class="empty" id="empty"><div><b>No paper matches this sentence.</b>Loosen one slot to bring papers back.</div></div>
  </div>
  <div class="wall" id="wall" hidden></div>
  <div class="legend" id="legend"></div>
</section>
<p class="meta foot" id="foot"></p>
<div class="srsc" aria-live="polite" id="live"></div>`;
main.appendChild(root);
const ringN=RINGS.map(r=>`${r[1].toLowerCase()} ${D.filter(d=>d.ring===r[0]).length}`).join(', ');
const INFO_PAGE=`<b>What it shows</b> Where in the field a kind of system sits, and how the papers relate.
<p><span class=k>How to read it.</span> Complete the sentence by picking an option in each slot; the rings, the wall, the counts and the compare tray all follow it. Each option shows how many papers it would keep.</p>
<p><span class=k>How it's computed.</span> Filtering runs on the fields the miners recorded. Counts and percentages are calculated from the papers that match; no model is involved.</p>`;
const INFO_RINGS=`<b>What it shows</b> Every paper as a dot, placed by how central it is, what ${HUB.term('technique','technique')} it uses and when it appeared.
<p><span class=k>How to read it.</span> Rings are the ${HUB.term('layer','layer')}, core at the centre (${ringN}; outer holds background, off-topic and unlayered papers). Sectors are the technique, widest where there are most papers. Inside a sector the angle is the publication month, ${mLabel(0)} to ${mLabel(NM-1)}, older to newer clockwise; the distance within a ring is jitter and means nothing. Size is ${HUB.term('cic','how often other papers here cite it')}; colour follows the buttons above. Faded dots are papers the sentence leaves out. Zooming adds detail: dots, then titles, then cards with month and role, then cards with the first evidence ${HUB.term('quote','quote')}.</p>
<p><span class=k>How it's computed.</span> Sector widths, ring counts and sizes are counted from the recorded fields. Positions inside a ring are spread to avoid overlap. Scores and similar lists use shared field values and shared citations only.</p>`;
const INFO_WALL=`<b>What it shows</b> One row per matching paper, with its ${HUB.term('dna','DNA')}: six coloured squares, one per field.
<p><span class=k>How to read it.</span> The squares are technique, architecture, automated span, human role, layer and half-year, left to right. Click a column name to sort; click again to reverse. Hover a square for its value; the key below the header lists the colours.</p>
<p><span class=k>How it's computed.</span> Colours come from the recorded values; a grey square means the field was not coded. Sorting is by the value order shown in the key.</p>`;
const INFO_TRAY=`<b>What it shows</b> Up to four pinned papers side by side: DNA, every field with its evidence quote, and shared citations.
<p><span class=k>How to read it.</span> Rows that differ between papers are marked with ≠ and shown in bold. Press P over a paper, or use Pin, to add it. "Similar to this" ranks all papers against one pinned paper.</p>
<p><span class=k>How it's computed.</span> Differences are plain comparisons of recorded values. Shared citations count papers in this review that two or more pinned papers cite, or that cite them.</p>`;
const INFO_SIM=`<b>What it shows</b> Papers most like the chosen one.
<p><span class=k>How it's computed.</span> ${SIMTXT0}.</p>`;
const I_PAGE=HUB.info(INFO_PAGE,'About Explore'),I_RINGS=HUB.info(INFO_RINGS,'About Rings'),I_WALL=HUB.info(INFO_WALL,'About the DNA wall'),I_TRAY=HUB.info(INFO_TRAY,'About Compare'),I_SIM=HUB.info(INFO_SIM,'About similar papers');
$('#ph').innerHTML=HUB.header({title:'Explore',sub:'Complete the sentence; everything below follows it.',infoHtml:INFO_PAGE,level:1});
const SH={rings:HUB.header({title:'Rings',infoHtml:INFO_RINGS}),wall:HUB.header({title:'DNA wall',infoHtml:INFO_WALL})};
$('#foot').innerHTML='Counts are '+HUB.term('mined','papers read in full')+' '+HUB.info(HUB.SETS_NOTE,'About these counts');
const tray=document.createElement('section');tray.className='tray';tray.id='tray';tray.setAttribute('aria-label','Compare tray');document.body.appendChild(tray);

const SLOTS={};let openSlot=null;
function buildSlot(key){
  const host=document.querySelector(`[data-s="${key}"]`);
  host.className='slot';
  host.innerHTML=`<button class="face" aria-haspopup="listbox" aria-expanded="false"><span class="ft"></span><sup class="n"></sup><span class="car"></span></button><div class="spop" role="listbox" hidden></div>`;
  const face=host.querySelector('.face'),pop=host.querySelector('.spop');
  SLOTS[key]={host,face,pop};
  face.onclick=e=>{e.stopPropagation();openSlot===key?closeSlots():openPop(key)};
  host.addEventListener('keydown',e=>{
    if(e.key==='Escape'&&openSlot===key){closeSlots();face.focus();e.stopPropagation()}
    else if((e.key==='ArrowDown'||e.key==='ArrowUp')&&openSlot===key){const o=[...pop.querySelectorAll('.opt:not([disabled])')];const i=o.indexOf(document.activeElement);const n=e.key==='ArrowDown'?Math.min(o.length-1,i+1):Math.max(0,i-1);(o[n]||o[0])?.focus();e.preventDefault()}
    else if(e.key==='ArrowDown'&&document.activeElement===face){openPop(key);e.preventDefault()}
  });
}
function closeSlots(){if(!openSlot)return;const s=SLOTS[openSlot];s.pop.hidden=true;s.face.setAttribute('aria-expanded','false');openSlot=null}
document.addEventListener('click',e=>{if(openSlot&&!SLOTS[openSlot].host.contains(e.target))closeSlots()});
function openPop(key,filter=''){
  closeSlots();openSlot=key;const{host,face,pop}=SLOTS[key];const{opts,total,any}=options(key);
  const cur=key==='s'?ST.s:ST[key];const max=Math.max(1,...opts.map(o=>o.n||0),total);
  const shown=(key==='x'&&filter?opts.filter(o=>o.label.toLowerCase().includes(filter.toLowerCase())):opts).slice(0,key==='x'?60:99);
  const head=key==='x'?`<input type="search" placeholder="Find a paper…" aria-label="Find a paper" value="${esc(filter)}">`:'';
  const optHTML=(v,label,n,sel,dis)=>`<button class="opt" role="option" data-v="${esc(v)}" aria-selected="${sel}" ${dis?'disabled':''}><span>${esc(label)}</span><span class="c">${n==null?'':n}</span><span class="xbar"><i style="width:${n?100*n/max:0}%"></i></span></button>`;
  const anyOpt=any?optHTML('',any,total,cur===''||cur==null,false):'';
  pop.innerHTML=head+`<div class="hd">${key==='x'?'Papers with a citation link here, with the count each keeps':'Papers each option would keep, given the other slots'}</div>`+anyOpt+
    shown.map(o=>optHTML(o.v,o.label.length>70?o.label.slice(0,68)+'…':o.label,o.n,String(cur)===String(o.v),key!=='r'&&key!=='x'&&!o.n&&String(cur)!==String(o.v))).join('')
    +(key==='x'&&!shown.length?'<div class="hd">No paper matches.</div>':'');
  pop.hidden=false;face.setAttribute('aria-expanded','true');
  const r=pop.getBoundingClientRect();if(r.right>innerWidth-8)pop.style.left=Math.min(0,innerWidth-8-r.right)-(0)+'px';
  pop.querySelectorAll('.opt').forEach(b=>b.onclick=()=>{const v=b.dataset.v;closeSlots();pickSlot(key,v)});
  const inp=pop.querySelector('input');
  if(inp){inp.oninput=()=>{const pos=inp.selectionStart;openPop(key,inp.value);const i2=SLOTS[key].pop.querySelector('input');i2.focus();i2.setSelectionRange(pos,pos)};inp.focus();inp.setSelectionRange(filter.length,filter.length)}
  else(pop.querySelector('.opt[aria-selected=true]:not([disabled])')||pop.querySelector('.opt:not([disabled])'))?.focus();
}
function pickSlot(key,v){
  const was=ST[key];
  if(key==='r'){ST.r=v;commit(`direction: ${v==='in'?'citing':'cited by'}`,true)}
  else{ST[key]=v;
    const lab=key==='x'?(v?'“'+DB.get(v).title.slice(0,28)+'”':'any paper'):(v===''?SLOT[key].any:SLOT[key].label(v));
    const nm={t:'technique',h:'human role',l:'layer',s:'since',x:(ST.r==='in'?'citing':'cited by')}[key];
    commit(`${nm}: ${lab}`,true)}
  if(was!==ST[key]||key==='r')refresh();
}
['t','h','l','s','r','x'].forEach(buildSlot);

/* ======================= trail + hash ======================= */
let trail=[],applying=false;
const r2=n=>Math.round(n*100)/100;
function stateHash(){
  const p=new URLSearchParams();
  for(const k of ['t','h','l','x'])if(ST[k])p.set(k,ST[k]);
  if(ST.s!=='')p.set('s',ST.s);
  if(ST.r!=='in')p.set('r',ST.r);
  if(ST.view!=='rings')p.set('view',ST.view);
  if(ST.col!=='human')p.set('col',ST.col);
  if(ST.pins.length)p.set('pin',ST.pins.join(','));
  if(ST.sim)p.set('sim',ST.sim);
  if(ST.sort.length)p.set('sort',ST.sort.join(','));
  if(ST.sec)p.set('sec',ST.sec);
  if(ST.o)p.set('o',ST.o);
  if(ST.view==='rings'&&(cam.z!==1||cam.cx||cam.cy||cam.rot))p.set('v',[r2(cam.cx),r2(cam.cy),r2(cam.z),Math.round(cam.rot*180/Math.PI)].join(','));
  return p.toString();
}
function writeHash(){history.replaceState(null,'','#'+stateHash())}
let hashT=0;const writeHashSoon=()=>{clearTimeout(hashT);hashT=setTimeout(writeHash,200)};
function commit(label,force){
  if(applying)return;writeHash();const h=stateHash();
  if(trail.length&&trail[trail.length-1].h===h&&!force)return;
  if(trail.length&&trail[trail.length-1].h===h)return;
  trail.push({l:label,h});if(trail.length>40)trail.shift();
  try{sessionStorage.setItem('explore-trail',JSON.stringify(trail))}catch(e){}
  renderTrail();
}
function renderTrail(){
  const el=$('#trail');if(trail.length<2){el.innerHTML='<span class="tl">Trail: your first step will appear here</span>';return}
  const cur=stateHash();const lastIdx=(()=>{for(let i=trail.length-1;i>=0;i--)if(trail[i].h===cur)return i;return trail.length-1})();
  const from=Math.max(0,trail.length-6);
  el.innerHTML='<span class="tl">Trail</span>'+(from?`<span class="sep" title="${from} earlier steps">…${from}</span>`:'')+
    trail.slice(from).map((s,j)=>`${j||from?'<span class="sep">›</span>':''}<button class="chip" data-tr="${from+j}" ${from+j===lastIdx?'aria-current="step"':''} title="${esc(s.l)} — click to return">${esc(s.l)}</button>`).join('');
  el.querySelectorAll('[data-tr]').forEach(b=>b.onclick=()=>{const s=trail[+b.dataset.tr];if(location.hash.slice(1)===s.h){applyHash(true)}else location.hash='#'+s.h});
}
function applyHash(animate){
  const p=new URLSearchParams(location.hash.slice(1));applying=true;
  ST.t=p.get('t')||'';ST.h=p.get('h')||'';ST.l=p.get('l')||'';ST.s=p.get('s')??'';ST.x=p.get('x')||'';ST.r=p.get('r')||'in';
  ST.view=p.get('view')==='wall'?'wall':'rings';ST.col=['era','none'].includes(p.get('col'))?p.get('col'):'human';
  ST.pins=(p.get('pin')||'').split(',').filter(id=>DB.has(id)).slice(0,4);ST.sim=ST.pins.includes(p.get('sim'))?p.get('sim'):'';
  ST.sort=(p.get('sort')||'').split(',').filter(Boolean);ST.sec=p.get('sec')||'';
  const o=p.get('o')||'';
  const v=(p.get('v')||'').split(',').map(Number);
  const hasV=v.length===4&&v.every(isFinite);let target=hasV?{cx:v[0],cy:v[1],z:v[2],rot:v[3]*Math.PI/180}:{cx:0,cy:0,z:1,rot:0};
  const ss=SECT.find(x=>x.key===ST.sec);
  if(!hasV&&ss){if(sized)target=sectorCam(ss);else pendingSec={s:ss}}
  if(animate&&sized)flyTo(target);else Object.assign(cam,target);
  if(o&&o!==ST.o){ST.o=o;HUB.openDrawer(o)}else if(!o&&ST.o){ST.o='';HUB.closeDrawer()}
  ST.o=o;
  applying=false;refresh();
}
window.addEventListener('hashchange',()=>applyHash(true));

/* ======================= match, lead, legend ======================= */
const secLabel=k=>(SECT.find(s=>s.key===k)||{}).label||k;
function refresh(){
  for(const d of D)d.m=pass(d);
  const M=D.filter(d=>d.m),n=M.length,N=D.length;
  // sentence faces
  for(const k of SLOTKEYS){const s=SLOTS[k],on=k==='r'?!!ST.x:(k==='s'?ST.s!=='':!!ST[k]);s.host.classList.toggle('on',on);
    s.face.querySelector('.ft').textContent=faceText(k);
    const sup=s.face.querySelector('.n');
    if(k==='r'||k==='x'){sup.textContent=''}else{const{c,total}=counts(k);sup.textContent=on?c.get(ST[k])??0:''}}
  $('#sqres').innerHTML=`<b>${fmt(n)} of ${fmt(N)} papers match this sentence.</b>${anyFilter()&&n?`<a class="btn" href="${esc(pathsHref([...M].sort((a,b)=>b.cic-a.cic).map(d=>d.id)))}">See their paths</a>`:''}${anyFilter()?'<button class="btn" id="clr">Clear the sentence</button>':''}`;
  const clr=$('#clr');if(clr)clr.onclick=()=>{ST.t=ST.h=ST.l=ST.s=ST.x='';commit('cleared the sentence');refresh()};
  // lead
  $('#lead').innerHTML=leadHTML(M);
  // view toggles
  document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.view===ST.view));
  document.querySelectorAll('[data-col]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.col===ST.col));
  $('#colseg').style.display=ST.view==='rings'?'':'none';
  $('#cv').style.display=ST.view==='rings'?'':'none';$('#wall').hidden=ST.view!=='wall';
  $('#empty').style.display=n===0&&ST.view==='rings'?'flex':'none';
  $('#sh').innerHTML=SH[ST.view];renderLegend(M);renderTray();
  if(ST.view==='wall')renderWall();else{resize();dirty()}
  writeHashSoon();renderTrail();
  $('#live').textContent=`${n} papers match`;
}
function topOf(M,f){const c=new Map();for(const d of M){const v=f(d);if(v!=null)c.set(v,(c.get(v)||0)+1)}return[...c.entries()].sort((a,b)=>b[1]-a[1])[0]||[null,0]}
function leadHTML(M){
  const n=M.length,N=D.length;
  if(!n)return `<b>Nothing matches.</b> Loosen a slot to bring papers back.`;
  const [rg]=topOf(M,d=>d.ring),[sc]=topOf(M,d=>d.sec);
  const best=M.reduce((a,d)=>d.cic>a.cic?d:a,M[0]);
  const noH=M.filter(d=>d.hum==='none').length;
  const rname=RINGS.find(r=>r[0]===rg)[1].toLowerCase();
  const head=n===N?`All <b>${fmt(N)}</b> papers are in view.`:`<b>${fmt(n)}</b> of ${fmt(N)} papers match.`;
  return `${head} Most sit in the <b>${rname}</b> ${HUB.term('layer','layer')}, led by <b>${esc(secLabel(sc).toLowerCase())}</b>; ${HUB.pct(noH,n)}% run with no ${HUB.term('human','human')} in the loop.<small>Most ${HUB.term('cic','cited here')}: “${esc(best.title.slice(0,70))}${best.title.length>70?'…':''}” (${best.cic}).</small>`;
}
function renderLegend(M){
  const el=$('#legend');
  const sz=[0,10,50,112].map(v=>v).filter((v,i,a)=>true);const maxc=Math.max(...D.map(d=>d.cic));
  const szHTML=`<span class="sz" aria-label="Size key">Size = ${HUB.term('cic','cited here')} ${[0,10,50,maxc].map(v=>{const r=Math.max(2,(3.2+1.15*Math.sqrt(v))*.62);return`<span><svg width="${2*r+2}" height="${2*r+2}" aria-hidden="true"><circle cx="${r+1}" cy="${r+1}" r="${r}" fill="none" stroke="currentColor"/></svg> ${v}</span>`}).join('')}</span>`;
  if(ST.view==='wall'){el.innerHTML=`<span class="meta">One row per paper, squares are its ${HUB.term('dna','DNA')} · click a column name to sort</span>`;return}
  if(ST.col==='human'){
    const vals=[...HUMAN.map(h=>h[0]),'∅'];
    el.innerHTML=vals.map(v=>{const tot=D.filter(d=>sk(d.hum)===v).length,mm=M.filter(d=>sk(d.hum)===v).length;
      const col=v==='∅'?cssv('--h-null'):HUB.humanColor(v);
      return `<button class="chip" data-hl="${v}" aria-pressed="${ST.h===v}"><span class="dot" style="background:${col}"></span>${esc(humanLabel(v==='∅'?null:v))} <span class="n">${anyFilter()?mm+'/':''}${tot}</span></button>`}).join('')+szHTML;
    el.querySelectorAll('[data-hl]').forEach(b=>b.onclick=()=>{ST.h=ST.h===b.dataset.hl?'':b.dataset.hl;commit('human: '+(ST.h?ROLE[ST.h]:'any role'));refresh()});
  }else if(ST.col==='era'){
    el.innerHTML=ERAS.map(e=>{const tot=D.filter(d=>d.era===e).length,mm=M.filter(d=>d.era===e).length;return`<span class="chip" style="cursor:default;background:transparent"><span class="dot" style="background:${segColor('era',e)}"></span>${eraLabel(e)} <span class="n">${anyFilter()?mm+'/':''}${tot}</span></span>`}).join('')+szHTML;
  }else el.innerHTML=`<span class="meta">No colour coding</span>`+szHTML;
}

/* ======================= canvas: rings with semantic zoom ======================= */
const cv=$('#cv'),cnv=$('#c'),ctx=cnv.getContext('2d'),mm=$('#mm'),mctx=mm.getContext('2d');
let pendingSec=null,W=0,H=0,dpr=1,k0=1,sized=false,raf=0,hover=null,cur=null,CL={};
const cam={cx:0,cy:0,z:1,rot:0};
const proj=(x,y,c=cam)=>{const k=c.z*k0,dx=(x-c.cx)*k,dy=(y-c.cy)*k,cs=Math.cos(c.rot),sn=Math.sin(c.rot);return[W/2+dx*cs-dy*sn,H/2+dx*sn+dy*cs]};
const unproj=(sx,sy,c=cam)=>{const k=c.z*k0,dx=sx-W/2,dy=sy-H/2,cs=Math.cos(-c.rot),sn=Math.sin(-c.rot);return[c.cx+(dx*cs-dy*sn)/k,c.cy+(dx*sn+dy*cs)/k]};
function colors(){CL={bg:cssv('--bg'),surface:cssv('--surface'),raised:cssv('--raised'),line:cssv('--line'),hair:cssv('--hair'),fg:cssv('--fg'),mut:cssv('--mut'),dim:cssv('--dim'),acc:cssv('--acc'),accSoft:cssv('--acc-soft'),accInk:cssv('--acc-ink')};refreshColors()}
function resize(){
  if(ST.view!=='rings')return;const r=cv.getBoundingClientRect();if(!r.width)return;
  const nw=Math.round(r.width),nh=Math.round(r.height);if(nw===W&&nh===H&&sized)return;
  W=nw;H=nh;dpr=Math.min(2,devicePixelRatio||1);cnv.width=W*dpr;cnv.height=H*dpr;
  k0=Math.min(W,H)/2/(RR+75);sized=true;if(pendingSec){Object.assign(cam,sectorCam(pendingSec.s));pendingSec=null}dirty();
}
new ResizeObserver(()=>{resize();dirty()}).observe(cv);
const dirty=()=>{if(!raf)raf=requestAnimationFrame(()=>{raf=0;draw()})};
const lodOf=z=>z<2.2?0:z<4?1:z<7?2:3;
const colorFor=d=>ST.col==='human'?(d.hum==null?cssv('--h-null'):HUB.humanColor(d.hum)):ST.col==='era'?segColor('era',d.era):CL.mut;
const wcache=new Map();
function wrap(text,maxW,font,maxL){const key=font+'|'+maxW+'|'+maxL+'|'+text;if(wcache.has(key))return wcache.get(key);
  ctx.font=font;const words=text.split(/\s+/);const lines=[];let line='';
  for(const w of words){const t=line?line+' '+w:w;if(ctx.measureText(t).width>maxW&&line){lines.push(line);line=w;if(lines.length===maxL)break}else line=t}
  if(lines.length<maxL&&line)lines.push(line);
  const used=lines.join(' ').length;if(used<text.length-1){let l=lines[lines.length-1];while(l.length>2&&ctx.measureText(l+'…').width>maxW)l=l.slice(0,-1);lines[lines.length-1]=l.replace(/[ ,:;]+$/,'')+'…'}
  wcache.set(key,lines);return lines}
const FU='Inter, system-ui, sans-serif',FD='Newsreader, Georgia, serif';
const firstQuote=d=>{for(const f of['technique','architecture','span','human']){const q=HUB.quote(d.w,f);if(q)return[f,q]}return[null,'']};
let rects=[],cardRects=[],labelRects=[];
const boxHit=(a,b,pad=3)=>a.x<b.x+b.w+pad&&b.x<a.x+a.w+pad&&a.y<b.y+b.h+pad&&b.y<a.y+a.h+pad;
function draw(){
  if(!sized)return;colors();
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,H);
  const k=cam.z*k0,z=cam.z,LOD=lodOf(z);
  // geometry in world space
  ctx.save();ctx.translate(W/2,H/2);ctx.rotate(cam.rot);ctx.scale(k,k);ctx.translate(-cam.cx,-cam.cy);
  const fills=[CL.raised,CL.surface,CL.bg,CL.surface,CL.bg];
  for(let i=RINGS.length-1;i>=0;i--){ctx.beginPath();ctx.arc(0,0,RINGS[i][3],0,7);ctx.fillStyle=fills[i];ctx.fill();ctx.lineWidth=1/k;ctx.strokeStyle=CL.line;ctx.stroke()}
  ctx.beginPath();ctx.arc(0,0,RINGS[0][2],0,7);ctx.fillStyle=CL.bg;ctx.fill();ctx.strokeStyle=CL.line;ctx.stroke();
  if(ST.sec){const s=SECT.find(x=>x.key===ST.sec);if(s){ctx.beginPath();ctx.arc(0,0,RINGS[0][2],s.a0,s.a1);ctx.arc(0,0,RR,s.a1,s.a0,true);ctx.closePath();ctx.globalAlpha=.45;ctx.fillStyle=CL.accSoft;ctx.fill();ctx.globalAlpha=1}}
  ctx.strokeStyle=CL.line;ctx.lineWidth=1/k;
  for(const s of SECT){for(const a of[s.a0,s.a1]){ctx.beginPath();ctx.moveTo(RINGS[0][2]*Math.cos(a),RINGS[0][2]*Math.sin(a));ctx.lineTo((RR+6)*Math.cos(a),(RR+6)*Math.sin(a));ctx.stroke()}}
  ctx.restore();
  // dots
  const ds=Math.pow(z,.55)*k0,vis=[];
  for(const d of D){const[sx,sy]=proj(d.x,d.y);d.sx=sx;d.sy=sy;d.rs=Math.max(2,d.rr*ds);d.on=sx>-60&&sx<W+60&&sy>-60&&sy<H+60;if(d.on)vis.push(d)}
  const pinSet=new Set(ST.pins);
  ctx.globalAlpha=1;
  for(const d of vis){if(d.m)continue;ctx.beginPath();ctx.arc(d.sx,d.sy,d.rs,0,7);ctx.fillStyle=CL.dim;ctx.globalAlpha=.2;ctx.fill();ctx.globalAlpha=1}
  const mt=vis.filter(d=>d.m).sort((a,b)=>b.rs-a.rs);
  for(const d of mt){ctx.beginPath();ctx.arc(d.sx,d.sy,d.rs,0,7);ctx.fillStyle=colorFor(d);ctx.globalAlpha=.92;ctx.fill();ctx.globalAlpha=1;ctx.lineWidth=1;ctx.strokeStyle=CL.bg;ctx.stroke()}
  // relation anchor
  if(ST.x){const a=DB.get(ST.x);if(a&&a.on){ctx.beginPath();ctx.arc(a.sx,a.sy,a.rs+5,0,7);ctx.setLineDash([3,3]);ctx.strokeStyle=CL.acc;ctx.lineWidth=1.5;ctx.stroke();ctx.setLineDash([])}}
  rects=[];cardRects=[];labelRects=[];
  // sector + ring labels
  drawSectorLabels();
  if(LOD<2)drawRingLabels();
  // titles / cards
  const placed=[];ctx.textBaseline='alphabetic';
  const cand=mt.filter(d=>d.on&&d.sx>0&&d.sx<W&&d.sy>0&&d.sy<H).sort((a,b)=>(pinSet.has(b.id)-pinSet.has(a.id))||(b.id===(hover&&hover.id))-(a.id===(hover&&hover.id))||b.cic-a.cic);
  let nCards=0;
  for(const d of cand){
    if(LOD===0)break;
    if(LOD===1){ if(d.cic<3&&!pinSet.has(d.id))continue;
      const t=d.title.replace(/:.*/,'').slice(0,42);ctx.font=`500 12px ${FU}`;const w=ctx.measureText(t).width;
      const b={x:d.sx+d.rs+4,y:d.sy-7,w:w,h:14};if(b.x+w>W-4)b.x=d.sx-d.rs-4-w;
      if(placed.some(p=>boxHit(p,b,4)))continue;placed.push(b);
      ctx.lineWidth=3;ctx.strokeStyle=CL.bg;ctx.strokeText(t,b.x,b.y+11);ctx.fillStyle=CL.fg;ctx.fillText(t,b.x,b.y+11);continue}
    if(nCards>=60)break;
    const big=LOD===3,cw=big?250:178;
    const [qf,q]=big?firstQuote(d):[null,''];
    const tl=wrap(d.title,cw-20,`600 12px ${FU}`,big?2:2);
    const ql=big&&q?wrap('“'+q+'”',cw-20,`italic 400 12.5px ${FD}`,4):[];
    const ch=10+tl.length*15+16+(big?8:6)+ (big?0:0)+8+(ql.length?(14+ql.length*16+4):0)+4;
    let b={x:d.sx+d.rs+6,y:d.sy-ch/2,w:cw,h:ch};
    if(b.x+cw>W-4){b.x=d.sx-d.rs-6-cw}
    b.y=Math.max(4,Math.min(H-ch-4,b.y));
    if(placed.some(p=>boxHit(p,b,5)))continue;
    placed.push(b);nCards++;
    drawCard(d,b,tl,ql,qf,big,pinSet);
  }
  // pins and hover rings
  ST.pins.forEach((id,i)=>{const d=DB.get(id);if(!d||!d.on)return;ctx.beginPath();ctx.arc(d.sx,d.sy,d.rs+4,0,7);ctx.lineWidth=2;ctx.strokeStyle=CL.acc;ctx.stroke();
    ctx.fillStyle=CL.acc;ctx.beginPath();ctx.arc(d.sx+d.rs+3,d.sy-d.rs-3,8,0,7);ctx.fill();ctx.fillStyle=CL.accInk;ctx.font=`600 10px ${FU}`;ctx.textAlign='center';ctx.fillText('ABCD'[i],d.sx+d.rs+3,d.sy-d.rs);ctx.textAlign='left'});
  if(hover&&hover.on){ctx.beginPath();ctx.arc(hover.sx,hover.sy,hover.rs+3,0,7);ctx.lineWidth=1.5;ctx.strokeStyle=CL.fg;ctx.stroke()}
  // fresh hit rects (dots)
  rects=mt.filter(d=>d.on).concat(vis.filter(d=>!d.m));
  drawMini();updateZI(LOD);
}
function drawCard(d,b,tl,ql,qf,big,pinSet){
  const{x,y,w,h}=b;ctx.fillStyle=CL.raised;ctx.beginPath();ctx.roundRect(x,y,w,h,6);ctx.fill();
  ctx.strokeStyle=pinSet.has(d.id)?CL.acc:CL.line;ctx.lineWidth=pinSet.has(d.id)?1.5:1;ctx.stroke();
  ctx.fillStyle=colorFor(d);ctx.fillRect(x,y+6,3,h-12);
  let yy=y+17;ctx.font=`600 12px ${FU}`;ctx.fillStyle=CL.fg;for(const l of tl){ctx.fillText(l,x+12,yy);yy+=15}
  ctx.font=`400 11px ${FU}`;ctx.fillStyle=CL.mut;
  const meta=mLabel(d.mi)+' · '+(d.hum==null?'role not coded':humanLabel(d.hum));
  let mt=meta;while(ctx.measureText(mt).width>w-62&&mt.length>8)mt=mt.slice(0,-2);if(mt!==meta)mt=mt.trim()+'…';
  ctx.fillText(mt,x+12,yy+1);
  // pin button
  const pb={x:x+w-44,y:y+yy-y-11,w:36,h:15};ctx.font=`500 10.5px ${FU}`;ctx.fillStyle=ST.pins.includes(d.id)?CL.acc:CL.dim;ctx.textAlign='right';ctx.fillText(ST.pins.includes(d.id)?'Pinned':'+ Pin',x+w-8,yy+1);ctx.textAlign='left';
  const pbw=48;pb.x=x+w-pbw-4;pb.w=pbw;
  yy+=9;
  const dna={x:x+12,y:yy,w:SEGS.length*14,h:8};
  SEGS.forEach((s,i)=>{ctx.fillStyle=segColor(s.k,s.get(d));ctx.beginPath();ctx.roundRect(dna.x+i*14,yy,13,8,2);ctx.fill()});
  yy+=8;
  if(ql.length){yy+=14;ctx.font=`500 10.5px ${FU}`;ctx.fillStyle=CL.dim;ctx.fillText('Evidence · '+({technique:'technique',architecture:'architecture',span:'span',human:'human role'}[qf]||''),x+12,yy);
    ctx.font=`italic 400 12.5px ${FD}`;ctx.fillStyle=CL.mut;yy+=3;for(const l of ql){yy+=16;ctx.fillText(l,x+12,yy)}}
  cardRects.push({d,x,y,w,h,pin:pb,dna});
}
function drawSectorLabels(){
  const items=SECT.map(s=>{const[px,py]=proj((RR+26)*Math.cos(s.am),(RR+26)*Math.sin(s.am));const a=s.am+cam.rot,cs=Math.cos(a);
    const tot=s.n,mt=D.filter(d=>d.sec===s.key&&d.m).length;const nm=s.label,sub=anyFilter()?`${mt} of ${tot}`:`${tot} papers`;
    ctx.font=`600 12.5px ${FU}`;const w1=ctx.measureText(nm).width;ctx.font=`400 11px ${FU}`;const w2=ctx.measureText(sub).width;const w=Math.max(w1,w2);
    const side=cs>.35?1:cs<-.35?-1:0;let x=side>0?px+4:side<0?px-4-w:px-w/2;let y=py+(Math.sin(a)>.5?14:Math.sin(a)<-.5?-24:-10);
    return{s,nm,sub,w,x,y,side}});
  items.sort((a,b)=>a.y-b.y);
  for(let i=0;i<items.length;i++)for(let j=0;j<i;j++){const a=items[j],b=items[i];if(boxHit({x:a.x,y:a.y,w:a.w,h:28},{x:b.x,y:b.y,w:b.w,h:28},4))b.y=a.y+30}
  for(const it of items){it.x=Math.max(6,Math.min(W-it.w-6,it.x));it.y=Math.max(6,Math.min(H-34,it.y));
    const act=ST.sec===it.s.key;
    ctx.font=`600 12.5px ${FU}`;ctx.fillStyle=act?CL.acc:CL.fg;ctx.fillText(it.nm,it.x,it.y+11);
    ctx.font=`400 11px ${FU}`;ctx.fillStyle=CL.mut;ctx.fillText(it.sub,it.x,it.y+25);
    labelRects.push({s:it.s,x:it.x-4,y:it.y-3,w:it.w+8,h:34});
    if(hover&&hover.lab===it.s.key){ctx.fillStyle=CL.acc;ctx.fillRect(it.x,it.y+28,it.w,1.5)}}
}
function drawRingLabels(){
  ctx.font=`500 11px ${FU}`;
  for(const r of RINGS){const rm=(r[2]+r[3])/2+(r[0]==='core'?0:0);
    const[px,py]=proj(0,-rm);const n=D.filter(d=>d.ring===r[0]).length,mt=D.filter(d=>d.ring===r[0]&&d.m).length;
    const t=r[1]+' '+(anyFilter()?mt+'/'+n:n);const w=ctx.measureText(t).width;
    if(px<-40||px>W+40||py<-20||py>H+20)continue;
    // anchor on the divider that points up in world space; rotate-safe because we use screen coords of the projected point
    ctx.lineWidth=4;ctx.strokeStyle=CL.bg;ctx.strokeText(t,px-w/2,py+4);ctx.fillStyle=CL.mut;ctx.fillText(t,px-w/2,py+4)}
}
function updateZI(LOD){const z=cam.z;$('#zi').innerHTML=`Zoom <b>×${z.toFixed(1)}</b> · showing <b>${['dots','dots and short titles','cards: month and role','cards with the first evidence quote'][LOD]}</b>${LOD<3?' · zoom in for more':''}`}
function drawMini(){
  const S=mm.width,c=S/2,sc=(S/2-6)/RR;mctx.clearRect(0,0,S,S);const surf=CL.surface;
  mctx.strokeStyle=CL.line;mctx.lineWidth=1;for(const r of RINGS){mctx.beginPath();mctx.arc(c,c,r[3]*sc,0,7);mctx.stroke()}
  for(const d of D){mctx.fillStyle=d.m?colorFor(d):CL.dim;mctx.globalAlpha=d.m?.95:.25;mctx.fillRect(c+d.x*sc-1,c+d.y*sc-1,2,2)}
  mctx.globalAlpha=1;
  const corners=[[0,0],[W,0],[W,H],[0,H]].map(([x,y])=>unproj(x,y));
  mctx.beginPath();corners.forEach(([x,y],i)=>{i?mctx.lineTo(c+x*sc,c+y*sc):mctx.moveTo(c+x*sc,c+y*sc)});mctx.closePath();mctx.lineWidth=1.5;mctx.strokeStyle=CL.acc;mctx.stroke();
  mctx.fillStyle=CL.accSoft;mctx.fill();
}
mm.addEventListener('pointerdown',e=>{const r=mm.getBoundingClientRect(),S=mm.width,sc=(S/2-6)/RR;const x=((e.clientX-r.left)*S/r.width-S/2)/sc,y=((e.clientY-r.top)*S/r.height-S/2)/sc;
  const move=ev=>{const xx=((ev.clientX-r.left)*S/r.width-S/2)/sc,yy=((ev.clientY-r.top)*S/r.height-S/2)/sc;cam.cx=xx;cam.cy=yy;dirty();writeHashSoon()};
  move(e);const up=()=>{removeEventListener('pointermove',move);removeEventListener('pointerup',up)};addEventListener('pointermove',move);addEventListener('pointerup',up);e.stopPropagation()});

/* camera moves */
let anim=0;
function flyTo(t,label){
  cancelAnimationFrame(anim);
  let dr=t.rot-cam.rot;dr=Math.atan2(Math.sin(dr),Math.cos(dr));const tr=cam.rot+dr;
  if(REDUCED){Object.assign(cam,t);dirty();writeHashSoon();return}
  const f={...cam},t0=performance.now(),T=650;
  const step=now=>{let p=Math.min(1,(now-t0)/T);p=p<.5?4*p*p*p:1-Math.pow(-2*p+2,3)/2;
    // zoom interpolates in log space so the move feels even
    cam.z=Math.exp(Math.log(f.z)+(Math.log(t.z)-Math.log(f.z))*p);cam.cx=f.cx+(t.cx-f.cx)*p;cam.cy=f.cy+(t.cy-f.cy)*p;cam.rot=f.rot+(tr-f.rot)*p;dirty();
    if(p<1)anim=requestAnimationFrame(step);else{writeHash()}};
  anim=requestAnimationFrame(step);
}
function sectorCam(s){const rc=300;return{cx:rc*Math.cos(s.am),cy:rc*Math.sin(s.am),z:Math.min(H*.9/430,W*.92/(2*RR*Math.sin(Math.min(s.a1-s.a0,Math.PI)/2)))/k0,rot:-Math.PI/2-s.am}}
function zoomSector(s){ST.sec=s.key;flyTo(sectorCam(s));commit('zoom: '+s.label.toLowerCase(),true);refresh()}
function fitAll(){ST.sec='';flyTo({cx:0,cy:0,z:1,rot:0});commit('fit all',true);refresh()}
function zoomAt(f,mx=W/2,my=H/2){const wp=unproj(mx,my);const zn=Math.max(.8,Math.min(30,cam.z*f));cam.z=zn;const[ux,uy]=unproj(mx,my,{cx:0,cy:0,z:zn,rot:cam.rot});cam.cx=wp[0]-ux;cam.cy=wp[1]-uy;dirty();writeHashSoon()}
$('#zin').onclick=()=>zoomAt(1.5);$('#zout').onclick=()=>zoomAt(1/1.5);$('#zfit').onclick=fitAll;

/* pointer: pan, pinch, hover, click */
const ptrs=new Map();let drag=null,pinch=0;
const pos=e=>{const r=cnv.getBoundingClientRect();return[e.clientX-r.left,e.clientY-r.top]};
function hitAt(mx,my){
  for(let i=cardRects.length-1;i>=0;i--){const c=cardRects[i];if(mx>=c.x&&mx<=c.x+c.w&&my>=c.y&&my<=c.y+c.h){
    if(mx>=c.pin.x&&my>=c.pin.y-2&&my<=c.pin.y+c.pin.h)return{d:c.d,part:'pin',card:c};
    if(mx>=c.dna.x&&mx<=c.dna.x+c.dna.w&&my>=c.dna.y-2&&my<=c.dna.y+c.dna.h+2)return{d:c.d,part:'dna',seg:Math.min(SEGS.length-1,Math.floor((mx-c.dna.x)/14)),card:c};
    return{d:c.d,part:'card',card:c}}}
  for(const l of labelRects)if(mx>=l.x&&mx<=l.x+l.w&&my>=l.y&&my<=l.y+l.h)return{lab:l.s};
  let best=null,bd=1e9;for(const d of rects){const dd=Math.hypot(d.sx-mx,d.sy-my);const lim=Math.max(d.rs+3,6);if(dd<lim&&dd-d.rs<bd){bd=dd-d.rs;best=d}}
  return best?{d:best,part:'dot'}:null;
}
cnv.addEventListener('pointerdown',e=>{cv.focus({preventScroll:true});cnv.setPointerCapture(e.pointerId);const p=pos(e);ptrs.set(e.pointerId,p);
  if(ptrs.size===1)drag={x:p[0],y:p[1],moved:0,cx:cam.cx,cy:cam.cy};else{drag=null;pinch=0}});
cnv.addEventListener('pointermove',e=>{const p=pos(e);
  if(ptrs.has(e.pointerId)){ptrs.set(e.pointerId,p);
    if(ptrs.size===2){const[a,b]=[...ptrs.values()];const dist=Math.hypot(a[0]-b[0],a[1]-b[1]);if(pinch)zoomAt(dist/pinch,(a[0]+b[0])/2,(a[1]+b[1])/2);pinch=dist;return}
    if(drag){const dx=p[0]-drag.x,dy=p[1]-drag.y;drag.moved=Math.max(drag.moved,Math.hypot(dx,dy));if(drag.moved>4){cancelAnimationFrame(anim);const k=cam.z*k0,cs=Math.cos(-cam.rot),sn=Math.sin(-cam.rot);cam.cx=drag.cx-(dx*cs-dy*sn)/k;cam.cy=drag.cy-(dx*sn+dy*cs)/k;cnv.style.cursor='grabbing';dirty();writeHashSoon();HUB.tip('',e)}return}}
  const h=hitAt(p[0],p[1]);
  const nh=h&&h.d?h.d:null;const lab=h&&h.lab?h.lab.key:null;
  if(nh!==hover||(hover&&hover.lab!==lab)){hover=nh;if(nh)cur=nh;if(!nh&&lab)hover=null;dirty()}
  cnv.style.cursor=h?'pointer':'grab';
  if(h&&h.part==='dna'){const s=SEGS[h.seg];HUB.tip(`<div class="t2" style="margin:0">${s.l}</div><b>${esc(segName(s,s.get(h.d)))}</b>`,e)}
  else if(h&&h.part==='pin')HUB.tip('Pin to the compare tray (P)',e);
  else if(h&&h.d)HUB.tip(tipHTML(h.d),e);
  else if(h&&h.lab)HUB.tip(`<div class="t1">${esc(h.lab.label)}</div><div class="t2">${h.lab.n} papers use this technique. Click to fly here.</div>`,e);
  else HUB.tip('',e);
});
cnv.addEventListener('pointerleave',e=>{HUB.tip('',e);if(hover){hover=null;dirty()}});
const endPtr=e=>{const p=pos(e);const was=drag;ptrs.delete(e.pointerId);if(ptrs.size<2)pinch=0;
  if(was&&was.moved<=4&&e.type==='pointerup'){const h=hitAt(p[0],p[1]);
    if(h&&h.part==='pin')togglePin(h.d.id);else if(h&&h.d)HUB.openDrawer(h.d.id);else if(h&&h.lab)zoomSector(h.lab)}
  drag=null;cnv.style.cursor='grab'};
cnv.addEventListener('pointerup',endPtr);cnv.addEventListener('pointercancel',endPtr);
cnv.addEventListener('wheel',e=>{e.preventDefault();const p=pos(e);zoomAt(Math.exp(-e.deltaY*(e.ctrlKey?.01:.0016)),p[0],p[1])},{passive:false});
cv.addEventListener('keydown',e=>{
  const step=60/(cam.z*k0);const cs=Math.cos(-cam.rot),sn=Math.sin(-cam.rot);const pan=(dx,dy)=>{cam.cx+=(dx*cs-dy*sn)*step;cam.cy+=(dx*sn+dy*cs)*step;dirty();writeHashSoon()};
  if(e.key==='+'||e.key==='=')zoomAt(1.4);else if(e.key==='-'||e.key==='_')zoomAt(1/1.4);else if(e.key==='0')fitAll();
  else if(e.key==='ArrowLeft')pan(-1,0);else if(e.key==='ArrowRight')pan(1,0);else if(e.key==='ArrowUp')pan(0,-1);else if(e.key==='ArrowDown')pan(0,1);
  else if(e.key==='['||e.key===']'){const i=SECT.findIndex(s=>s.key===ST.sec);const n=(i<0?(e.key===']'?0:SECT.length-1):(i+(e.key===']'?1:-1)+SECT.length)%SECT.length);zoomSector(SECT[n])}
  else if(e.key==='.'||e.key===','){const M=D.filter(d=>d.m).sort((a,b)=>b.cic-a.cic||a.i-b.i);if(M.length){const i=M.indexOf(cur);cur=M[i<0?0:(i+(e.key==='.'?1:-1)+M.length)%M.length];hover=cur;dirty();$('#live').textContent=cur.title+'. Press P to pin, Enter to open.'}}
  else if(e.key==='Enter'&&cur)HUB.openDrawer(cur.id);else return;e.preventDefault()});
function tipHTML(d){return `<div class="t1">${esc(d.title)}</div><div class="t2">${mLabel(d.mi)} · ${esc(layerLabel(d.layer))} · cited here ${d.cic}×${d.m?'':' · <b>outside the sentence</b>'}</div>${tipDNA(d)}<div class="t3">Click to open · P to pin to the compare tray</div>`}

/* ======================= DNA wall ======================= */
const ordIndex=(s,d)=>{const v=s.get(d);if(v==null)return 999;const i=ORD[s.k].indexOf(v);return i<0?998:i};
function sortedRows(M){
  const keys=ST.sort.length?ST.sort:['technique','human'];
  return[...M].sort((a,b)=>{for(const kk of keys){const desc=kk[0]==='-',k=desc?kk.slice(1):kk,s=SEGS.find(x=>x.k===k);if(!s)continue;const r=ordIndex(s,a)-ordIndex(s,b);if(r)return desc?-r:r}return b.cic-a.cic});
}
function renderWall(){
  const M=D.filter(d=>d.m),rows=sortedRows(M);const w=$('#wall');
  const keys=ST.sort.length?ST.sort:['technique','human'];
  const rank=k=>keys.findIndex(x=>x.replace('-','')===k);
  const sc=w.scrollTop;
  w.innerHTML=`<div class="wh">${SEGS.map(s=>{const i=rank(s.k),desc=i>=0&&keys[i][0]==='-';return`<button class="sb" data-sb="${s.k}" ${i>=0?`aria-sort="${desc?'descending':'ascending'}"`:''} title="Sort by ${s.l.toLowerCase()}">${s.s}${i>=0?` <small>${i+1}${desc?'↓':'↑'}</small>`:''}</button>`}).join('')}<span class="tc">title · month · cited here · pin</span></div>
  <details class="wk"><summary>Key to the six squares</summary><div class="kg">${SEGS.map(s=>`<b>${s.l}</b><div>${[...ORD[s.k],null].filter(v=>v!==null||D.some(d=>s.get(d)==null)).map(v=>`<span><i style="background:${segColor(s.k,v)}"></i>${esc(segName(s,v))}</span>`).join('')}</div>`).join('')}</div></details>
  ${rows.length?rows.map(d=>`<div class="wr" role="button" tabindex="0" data-id="${esc(d.id)}" aria-selected="${ST.pins.includes(d.id)}" aria-label="${esc(d.title)}">${dnaHTML(d,64,13).replace(/<i /g,'<i data-seg="1" ')}<span class="tt">${esc(d.title)}</span><span class="m">${mLabel(d.mi)}</span><span class="ci">${d.cic}</span><button class="pb ${ST.pins.includes(d.id)?'on':''}" tabindex="-1" aria-label="Pin to compare tray" title="Pin (P)">${ST.pins.includes(d.id)?'●':'+'}</button></div>`).join(''):'<div class="empty2"><b>No paper matches this sentence.</b><br>Loosen a slot above.</div>'}`;
  w.scrollTop=sc;
}
$('#wall').addEventListener('click',e=>{
  const sb=e.target.closest('[data-sb]');
  if(sb){const k=sb.dataset.sb;const cur=ST.sort.length?ST.sort:['technique','human'];const i=cur.findIndex(x=>x.replace('-','')===k);
    let next;if(i===0)next=[(cur[0][0]==='-'?'':'-')+k,...cur.slice(1)];else next=[k,...cur.filter(x=>x.replace('-','')!==k)];
    ST.sort=next.slice(0,3);commit('sort: '+SEGS.find(s=>s.k===k).l.toLowerCase(),true);refresh();return}
  const r=e.target.closest('.wr');if(!r)return;
  if(e.target.closest('.pb'))togglePin(r.dataset.id);else HUB.openDrawer(r.dataset.id)});
$('#wall').addEventListener('keydown',e=>{const r=e.target.closest&&e.target.closest('.wr');if(!r)return;
  if(e.key==='Enter'||e.key===' '){e.preventDefault();HUB.openDrawer(r.dataset.id)}
  else if(e.key==='ArrowDown'){r.nextElementSibling?.focus();e.preventDefault()}else if(e.key==='ArrowUp'){r.previousElementSibling?.focus?.();e.preventDefault()}});
$('#wall').addEventListener('mousemove',e=>{
  const i=e.target.closest('i[data-seg]');const r=e.target.closest('.wr');if(!r){HUB.tip('',e);return}
  const d=DB.get(r.dataset.id);cur=d;
  if(i){const idx=[...i.parentNode.children].indexOf(i),s=SEGS[idx];HUB.tip(`<div class="t2" style="margin:0">${s.l}</div><b>${esc(segName(s,s.get(d)))}</b><div class="t3">${esc(d.title.slice(0,70))}</div>`,e)}
  else HUB.tip(tipHTML(d),e)});
$('#wall').addEventListener('mouseleave',e=>HUB.tip('',e));
$('#wall').addEventListener('focusin',e=>{const r=e.target.closest&&e.target.closest('.wr');if(r)cur=DB.get(r.dataset.id)});

/* ======================= pins, compare tray, similar ======================= */
let trayCollapsed=false;

function togglePin(id){
  const i=ST.pins.indexOf(id);
  if(i>=0){ST.pins.splice(i,1);if(ST.sim===id)ST.sim='';commit('unpinned '+DB.get(id).title.slice(0,24)+'…',true)}
  else if(ST.pins.length>=4){$('#live').textContent='The tray holds four papers; unpin one first.';flash('The tray holds four papers. Unpin one first.');return}
  else{ST.pins.push(id);commit('pinned '+DB.get(id).title.replace(/:.*/,'').slice(0,26),true)}
  refresh();
}
const pathsHref=ids=>'flow.html#lanes='+ids.slice(0,20).map(encodeURIComponent).join(',');
function flash(t){const el=$('#tray');const s=document.createElement('div');s.className='slim';s.style.color='var(--exc)';s.textContent='− '+t;el.prepend(s);setTimeout(()=>s.remove(),2200)}
function similarTo(id){
  const a=DB.get(id),oa=new Set(citesOut.get(id)||[]);
  return D.filter(d=>d.id!==id).map(d=>{let f=0;for(const s of SEGS){const v=s.get(a);if(v!=null&&v===s.get(d))f++}
    let sh=0;for(const c of(citesOut.get(d.id)||[]))if(oa.has(c))sh++;return{d,f,sh,s:f+sh}}).sort((x,y)=>y.s-x.s||y.d.cic-x.d.cic).slice(0,8);
}
function renderTray(){
  const P=ST.pins.map(id=>DB.get(id)).filter(Boolean);const el=$('#tray');
  if(!P.length){el.innerHTML=`<div class="slim"><span class="h3">Compare ${I_TRAY}</span><span>0 of 4 pinned. Press <span class="kbd">P</span> over a paper to pin it.</span></div>`;document.body.style.paddingBottom=el.offsetHeight+'px';return}
  const n=P.length;
  const rowsF=[['technique','Technique',d=>d.tech,v=>pretty(v)],['architecture','Architecture',d=>d.arch,v=>pretty(v)],['span','Automated span',d=>d.span,v=>pretty(v)],['human','Human role',d=>d.hum,v=>humanLabel(v)]];
  const rowsS=[['Layer',d=>d.layer,v=>layerLabel(v)],['Month',d=>mLabel(d.mi),v=>v],['Cited here',d=>d.cic,v=>v+' times']];
  const gt=`grid-template-columns:128px repeat(${n},minmax(210px,1fr))`;
  let h=`<div class="th"><span class="h3">Compare ${I_TRAY}</span><span class="meta">${n} of 4 pinned</span><span class="grow"></span><a class="btn" href="${esc(pathsHref(P.map(d=>d.id)))}">See their paths</a><button class="btn" id="tcol" aria-expanded="${!trayCollapsed}">${trayCollapsed?'Expand':'Collapse'}</button><button class="btn" id="tclr">Unpin all</button></div><div class="tb" style="${gt}">`;
  h+=`<div class="rl"></div>`+P.map((d,i)=>`<div class="cl hd"><div style="display:flex;align-items:flex-start"><span class="badge">${'ABCD'[i]}</span><span class="ptitle" data-o="${esc(d.id)}">${esc(d.title)}</span></div><div class="acts"><button class="btn" data-sim="${esc(d.id)}" aria-pressed="${ST.sim===d.id}">${ST.sim===d.id?'Similar to this: shown':'Similar to this'}</button><button class="btn" data-un="${esc(d.id)}" aria-label="Unpin">− Unpin</button></div></div>`).join('');
  h+=`<div class="rl">DNA</div>`+P.map(d=>`<div class="cl" data-dna="${esc(d.id)}">${dnaHTML(d,26,16).replace(/<i /g,'<i data-seg="1" ')}</div>`).join('');
  for(const[k,l,get,lab] of rowsF){const vals=P.map(d=>get(d)??null);const diff=new Set(vals).size>1&&n>1;
    h+=`<div class="rl ${diff?'d':''}">${diff?'<span class="g">≠</span> ':''}${l}</div>`+P.map((d,i)=>`<div class="cl ${diff?'diff':''}"><span class="v">${esc(vals[i]==null?'Not coded':lab(vals[i]))}</span>${HUB.quote(d.w,k)?`<q title="${esc(HUB.quote(d.w,k))}">${esc(HUB.quote(d.w,k))}</q>`:`<div class="meta">no ${HUB.term('quote','quote')} recorded</div>`}</div>`).join('')}
  for(const[l,get,lab] of rowsS){const vals=P.map(d=>get(d.w&&l==='Layer'?d:(l==='Month'?d.w:d)));
    const raw=P.map(d=>l==='Layer'?d.layer:l==='Month'?d.mi:d.cic);const diff=new Set(raw).size>1&&n>1;
    h+=`<div class="rl ${diff?'d':''}">${diff?'<span class="g">≠</span> ':''}${l}</div>`+raw.map(v=>`<div class="cl ${diff?'diff':''}"><span class="v">${esc(l==='Layer'?layerLabel(v):l==='Month'?mLabel(v):l==='Cited here'?v+' times':v)}</span></div>`).join('')}
  h+='</div>';
  if(trayCollapsed){h=h.slice(0,h.indexOf('<div class="tb"'))}
  // shared citations
  const cited=new Map(),citers=new Map();
  P.forEach((d,i)=>{for(const c of(citesOut.get(d.id)||[])){(cited.get(c)||cited.set(c,[]).get(c)).push(i)}for(const c of(citesIn.get(d.id)||[])){(citers.get(c)||citers.set(c,[]).get(c)).push(i)}});
  const sharedRef=[...cited.entries()].filter(([c,l])=>l.length>1).sort((a,b)=>b[1].length-a[1].length);
  const sharedBy=[...citers.entries()].filter(([c,l])=>l.length>1).sort((a,b)=>b[1].length-a[1].length);
  const direct=[];P.forEach((a,i)=>P.forEach((b,j)=>{if(i!==j&&(citesOut.get(a.id)||[]).includes(b.id))direct.push(`${'ABCD'[i]} cites ${'ABCD'[j]}`)}));
  const L=(arr,nm)=>arr.length?`<ul>${arr.slice(0,6).map(([c,l])=>`<li><span class="s">${l.map(i=>'ABCD'[i]).join('+')}</span><a data-o="${esc(c)}">${esc((DB.get(c)||{title:c}).title)}</a></li>`).join('')}</ul>${arr.length>6?`<div class="meta">and ${arr.length-6} more</div>`:''}`:`<div class="meta" style="margin-top:6px">${n>1?'None inside the corpus.':'Pin a second paper to compare.'}</div>`;
  h+=`<div class="lower"><div><div class="h3">Shared citations</div>
    <div class="meta" style="margin-top:4px">Cited by two or more pinned papers (${sharedRef.length}):</div>${L(sharedRef)}
    <div class="meta" style="margin-top:10px">Cite two or more pinned papers (${sharedBy.length}):</div>${L(sharedBy)}
    ${direct.length?`<div class="meta" style="margin-top:10px">Direct links: ${direct.join('; ')}</div>`:''}</div>
    <div><div class="h3">${ST.sim?`Similar to ${'ABCD'[ST.pins.indexOf(ST.sim)]}`:HUB.term('similar','Similar papers')} ${I_SIM}</div>
    ${ST.sim?`<ul>${similarTo(ST.sim).map(r=>`<li><span class="s" title="${r.f} identical segments + ${r.sh} shared cited works">${r.f}+${r.sh}=${r.s}</span>${dnaHTML(r.d,9,9)}<a data-o="${esc(r.d.id)}">${esc(r.d.title.slice(0,64))}${r.d.title.length>64?'…':''}</a><button class="btn" data-pin="${esc(r.d.id)}" style="height:22px;padding:0 8px;font-size:11px;margin-left:auto;white-space:nowrap">${ST.pins.includes(r.d.id)?'Pinned':'+ Pin'}</button></li>`).join('')}</ul>`:'<div class="meta" style="margin-top:6px">Press “Similar to this” on a pinned paper.</div>'}</div></div>`;
  if(trayCollapsed){el.innerHTML=h;el.querySelector('#tcol').onclick=()=>{trayCollapsed=false;renderTray()};el.querySelector('#tclr').onclick=()=>{ST.pins=[];ST.sim='';commit('unpinned all',true);refresh()};return}
  el.innerHTML=h;el.querySelector('#tcol').onclick=()=>{trayCollapsed=true;renderTray()};
  el.querySelector('#tclr').onclick=()=>{ST.pins=[];ST.sim='';commit('unpinned all',true);refresh()};
  el.querySelectorAll('[data-o]').forEach(a=>a.onclick=()=>HUB.openDrawer(a.dataset.o));
  el.querySelectorAll('[data-un]').forEach(b=>b.onclick=()=>togglePin(b.dataset.un));
  el.querySelectorAll('[data-pin]').forEach(b=>b.onclick=()=>togglePin(b.dataset.pin));
  el.querySelectorAll('[data-sim]').forEach(b=>b.onclick=()=>{ST.sim=ST.sim===b.dataset.sim?'':b.dataset.sim;commit(ST.sim?'similar to '+'ABCD'[ST.pins.indexOf(ST.sim)]:'similar closed',true);refresh()});
  document.body.style.paddingBottom=el.offsetHeight+'px';
}
new ResizeObserver(()=>{document.body.style.paddingBottom=tray.offsetHeight+'px'}).observe(tray);
tray.addEventListener('mousemove',e=>{const i=e.target.closest('i[data-seg]');if(!i){HUB.tip('',e);return}const d=DB.get(i.closest('.cl').dataset.dna);
  if(!d)return;const idx=[...i.parentNode.children].indexOf(i),s=SEGS[idx];HUB.tip(`<div class="t2" style="margin:0">${s.l}</div><b>${esc(segName(s,s.get(d)))}</b>`,e)});
tray.addEventListener('mouseleave',e=>HUB.tip('',e));

/* ======================= global wiring ======================= */
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{ST.view=b.dataset.view;commit(ST.view==='wall'?'DNA wall':'rings',true);refresh()});
document.querySelectorAll('[data-col]').forEach(b=>b.onclick=()=>{ST.col=b.dataset.col;commit('colour: '+b.dataset.col,true);refresh()});
document.addEventListener('keydown',e=>{
  if(/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)||e.ctrlKey||e.metaKey||e.altKey)return;
  if(e.key==='p'||e.key==='P'){const d=cur||hover;if(d){togglePin(d.id);e.preventDefault()}}
});
document.addEventListener('hub:theme',()=>{wcache.clear();colors();refresh()});
document.addEventListener('hub:open',e=>{if(applying)return;ST.o=e.detail;cur=DB.get(e.detail)||cur;commit('opened '+(DB.get(e.detail)||{title:''}).title.replace(/:.*/,'').slice(0,28),true);writeHash()});
document.addEventListener('hub:close',()=>{if(applying)return;ST.o='';writeHash()});

/* init */
colors();
try{trail=JSON.parse(sessionStorage.getItem('explore-trail')||'[]')}catch(e){trail=[]}
applyHash(false);
if(!trail.length||trail[trail.length-1].h!==stateHash())trail.push({l:trail.length?'loaded a link':'start',h:stateHash()});
renderTrail();

}).catch(e => { document.body.textContent = 'Explore failed to load: ' + e.message; });
