/* Factory feed page (main hub /feed/): reactions, save, train, weak line, filters, project picker.
   Plain JS. Writes go to the hub's own routes with the hub token (meta factory-token); Send and
   Add go to the chosen project's routes with that project's token. Nothing is read from storage
   except the weak line (in try/catch). */
(function(){
'use strict';
var meta=document.querySelector('meta[name=factory-token]');
var HUB=meta?meta.content:'';
var root=document.getElementById('fx');
if(!root)return;
var PROJECTS=[];try{PROJECTS=JSON.parse(root.dataset.projects||'[]');}catch(e){}
var RANKING=root.dataset.rankingId||'';
var $=function(s,r){return (r||document).querySelector(s);};
var $$=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s));};

/* toast */
var toastEl=null,toastT=0;
function toast(text){
  if(!toastEl){toastEl=document.createElement('div');toastEl.className='fx-toast';toastEl.setAttribute('role','status');document.body.appendChild(toastEl);}
  toastEl.textContent=text;toastEl.hidden=false;clearTimeout(toastT);
  toastT=setTimeout(function(){toastEl.hidden=true;},3500);
}
function issues(r){return ((r&&r.issues)||[]).map(function(i){return i.field+': '+i.reason;}).join('; ')||'refused';}
function post(url,token,body){
  return fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-Factory-Token':token},body:JSON.stringify(body)})
  .then(function(r){return r.json().catch(function(){return {ok:false,issues:[{field:'response',reason:'status '+r.status}]};});})
  .catch(function(e){return {ok:false,issues:[{field:'request',reason:String(e)}]};});
}

/* info panels: (i) buttons with a short explanation */
var pop=document.createElement('div');pop.className='pop';pop.setAttribute('role','tooltip');document.body.appendChild(pop);
function showPop(el){
  pop.textContent=el.dataset.tip||'';pop.style.display='block';
  var b=el.getBoundingClientRect();
  pop.style.left=Math.max(8,Math.min(innerWidth-pop.offsetWidth-8,b.left))+'px';
  pop.style.top=(b.bottom+6)+'px';
}
document.addEventListener('mouseover',function(e){var t=e.target.closest&&e.target.closest('.info');if(t)showPop(t);});
document.addEventListener('mouseout',function(e){if(e.target.closest&&e.target.closest('.info'))pop.style.display='none';});
document.addEventListener('focusin',function(e){var t=e.target.closest&&e.target.closest('.info');if(t)showPop(t);});
document.addEventListener('focusout',function(){pop.style.display='none';});
document.addEventListener('click',function(e){var t=e.target.closest&&e.target.closest('.info');if(t)showPop(t);else pop.style.display='none';});

/* counts in the sidebar */
function bump(key,delta){
  var el=$('[data-count="'+key+'"]');if(!el)return;
  el.textContent=String(Math.max(0,(parseInt(el.textContent,10)||0)+delta));
}

/* weak line */
var KEY='factory-feed-weak',weak=0.5;
try{var v=parseFloat(localStorage.getItem(KEY));if(v>=0&&v<=1)weak=v;}catch(e){}
function applyWeak(){
  $$('.fx-badges [data-score]').forEach(function(b){b.hidden=parseFloat(b.dataset.score)<weak&&!b.hasAttribute('data-held');});
  var out=$('#fx-weak-out');if(out)out.textContent=weak.toFixed(2);
  var d=$('#fx-divider');
  if(d){
    var cards=$$('.fx-card[data-score]');
    var first=cards.filter(function(c){return !c.hidden&&parseFloat(c.dataset.score)<weak;})[0];
    if(first){d.hidden=false;first.parentNode.insertBefore(d,first);var x=$('#fx-divider-x');if(x)x.textContent=weak.toFixed(2);}
    else d.hidden=true;
  }
}
var slider=$('#fx-weak');
if(slider){
  slider.value=String(weak);
  slider.addEventListener('input',function(){
    weak=parseFloat(slider.value)||0;
    try{localStorage.setItem(KEY,String(weak));}catch(e){}
    applyWeak();
  });
}

/* filters: text and category (this page's cards) */
var cat='';
function filter(){
  var q=(($('#fx-q')||{}).value||'').trim().toLowerCase();
  $$('.fx-card,.fx-row[data-entry-id]').forEach(function(c){
    var text=(c.dataset.text||'').toLowerCase();
    var cats=(c.dataset.cats||'').split(' ');
    c.hidden=(q&&text.indexOf(q)<0)||(cat&&cats.indexOf(cat)<0);
  });
  applyWeak();
}
var q=$('#fx-q');if(q)q.addEventListener('input',filter);
$$('.chip[data-cat]').forEach(function(ch){
  ch.addEventListener('click',function(){
    var on=ch.getAttribute('aria-pressed')==='true';
    $$('.chip[data-cat]').forEach(function(o){o.setAttribute('aria-pressed','false');});
    cat=on?'':ch.dataset.cat;
    if(!on)ch.setAttribute('aria-pressed','true');
    filter();
  });
});
$$('.fx-cat').forEach(function(b){b.addEventListener('click',function(){
  var ch=$('.chip[data-cat="'+CSS.escape(b.dataset.cat)+'"]');if(ch)ch.click();
});});
var sort=$('#fx-sort');
if(sort)sort.addEventListener('change',function(){location.href=sort.dataset.base+'?sort='+encodeURIComponent(sort.value);});
var win=$('#fx-window');
if(win)win.addEventListener('change',function(){location.href=win.dataset.base+'?window='+encodeURIComponent(win.value);});

/* settings panel */
var gear=$('#fx-gear'),panel=$('#fx-settings');
if(gear&&panel)gear.addEventListener('click',function(){
  panel.hidden=!panel.hidden;gear.setAttribute('aria-expanded',panel.hidden?'false':'true');
});

/* train */
var train=$('#fx-train');
if(train)train.addEventListener('click',function(){
  if(train.disabled)return;
  train.disabled=true;var out=$('#fx-train-out');if(out)out.textContent='Training…';
  post('/api/feed/train',HUB,{}).then(function(r){
    if(r.ok){toast('Trained: ranker v'+r.ranker_version);if(out)out.textContent='Trained: ranker v'+r.ranker_version+'. Reload the page to see the new order.';}
    else{if(out)out.textContent=issues(r);train.disabled=false;}
  });
});

/* card controls */
function msg(card,text){
  var el=$('.fx-msg',card);
  if(!el){el=document.createElement('p');el.className='fx-msg';card.appendChild(el);}
  el.textContent=text;
}
function react(card,reaction){
  var body={entry_id:card.dataset.entryId,reaction:reaction};
  if(RANKING)body.ranking_id=RANKING;
  if(card.dataset.rank)body.rank_shown=parseInt(card.dataset.rank,10);
  if(card.dataset.pred)body.score_shown=parseFloat(card.dataset.pred);
  return post('/api/feed/react',HUB,body);
}
var page=root.dataset.page||'';
function onReacted(card,reaction){
  if(reaction==='like'||reaction==='dislike'){
    if(page==='today'){card.remove();bump('today',-1);}
    else{$$('[data-act=like],[data-act=dislike]',card).forEach(function(b){b.setAttribute('aria-pressed',b.dataset.act===reaction?'true':'false');});}
    bump(reaction==='like'?'liked':'disliked',1);
    toast(reaction==='like'?'Liked. It trains the ranker when you press Train.':'Disliked. It trains the ranker when you press Train.');
  }else if(reaction==='save'||reaction==='unsave'){
    var b=$('[data-act=save]',card);var on=reaction==='save';
    if(b){b.setAttribute('aria-pressed',on?'true':'false');b.textContent=on?'Saved':'Save';b.dataset.next=on?'unsave':'save';}
    bump('reading',on?1:-1);toast(on?'Added to the reading list.':'Removed from the reading list.');
  }
}
$$('button[data-act]').forEach(function(b){
  b.addEventListener('click',function(){
    var card=b.closest('[data-entry-id]'),act=b.dataset.act;
    if(act==='send'||act==='add'){return pick(card,act);}
    var reaction=act==='save'?(b.dataset.next||'save'):act==='undo'?'unset':act==='remove'?'unsave':act;
    b.disabled=true;
    react(card,reaction).then(function(r){
      b.disabled=false;
      if(!r.ok){msg(card,issues(r));return;}
      if(act==='undo'){var was=card.dataset.was;card.remove();bump(was,-1);toast('Undone.');}
      else if(act==='remove'){card.remove();bump('reading',-1);toast('Removed from the reading list.');}
      else onReacted(card,reaction);
    });
  });
});

/* show more */
$$('.fx-more').forEach(function(b){b.addEventListener('click',function(){
  var c=b.closest('.fx-card'),open=c.classList.toggle('open');b.textContent=open?'Show less':'Show more';
  b.setAttribute('aria-expanded',open?'true':'false');
});});

/* send or add to a project: a picker, then the project's own route with its own token */
function pick(card,act){
  var host=$('.fx-acts',card);if($('.fx-pick',card))return;
  var wrap=document.createElement('span');wrap.className='fx-pick';
  var sel=document.createElement('select');sel.setAttribute('aria-label','Project');
  PROJECTS.forEach(function(p){var o=document.createElement('option');o.value=p.slug;o.textContent=p.title||p.slug;sel.appendChild(o);});
  var go=document.createElement('button');go.type='button';go.className='btn primary';go.textContent=act==='send'?'Send':'Add';
  var no=document.createElement('button');no.type='button';no.className='btn';no.textContent='Cancel';
  wrap.appendChild(sel);wrap.appendChild(go);wrap.appendChild(no);host.appendChild(wrap);
  no.addEventListener('click',function(){wrap.remove();});
  go.addEventListener('click',function(){
    var p=PROJECTS.filter(function(x){return x.slug===sel.value;})[0];if(!p)return;
    go.disabled=true;
    post('/p/'+p.slug+'/api/feed/'+(act==='send'?'send':'add'),p.token,{entry_id:card.dataset.entryId}).then(function(r){
      go.disabled=false;
      if(!r.ok){msg(card,issues(r));return;}
      wrap.remove();
      msg(card,act==='send'?('Sent to '+(p.title||p.slug)+' (inbox item '+r.inbox_item_id+')'):('Added to '+(p.title||p.slug)+': '+r.outcome+(r.reason?' ('+r.reason+')':'')));
    });
  });
}

/* Fetch now: the hub's feed run (fetch anything new, then rank), polled until it ends */
function localTimes(){
  $$('time[datetime]').forEach(function(t){
    var d=new Date(t.getAttribute('datetime'));
    if(!isNaN(d))t.textContent=d.toLocaleString(undefined,{day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'});
  });
}
function fetcher(){
  var btn=$('#fx-fetch'),line=$('#fx-fetch-line');
  if(!btn)return;
  function idle(){btn.disabled=false;btn.textContent='Fetch now';}
  function poll(waiting){
    fetch('/api/feed/runner',{cache:'no-store'}).then(function(r){return r.json();}).then(function(s){
      if(s.running){
        btn.disabled=true;btn.textContent='Fetching…';
        line.textContent='fetching new papers, then ranking; this can take a few minutes';
        setTimeout(function(){poll(true);},3000);return;
      }
      idle();
      if(!waiting)return;
      var last=s.last||{};
      if(last.error){line.textContent='The run failed: '+last.error;return;}
      if(last.factory_ranking&&last.factory_ranking.indexOf('failed')===0){line.textContent='Fetched, but ranking '+last.factory_ranking;return;}
      line.textContent='Done: '+(last.factory_ranking||'finished')+'. Reloading…';
      location.reload();
    }).catch(function(){idle();line.textContent='Could not read the run state.';});
  }
  btn.addEventListener('click',function(){
    btn.disabled=true;line.textContent='starting…';
    post('/api/feed/run',HUB,{}).then(function(r){
      var busy=(r.issues||[]).some(function(i){return /in progress/.test(i.reason||'');});
      if(r.ok||busy){poll(true);return;}
      idle();line.textContent=issues(r);
    });
  });
  poll(false);
}

localTimes();
fetcher();
applyWeak();
})();
