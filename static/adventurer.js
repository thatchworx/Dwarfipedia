/* =========================================================================
   adventurer.js  --  the Adventure Mode character manager
   =========================================================================
   A living character sheet. The point is that a paper sheet makes you erase
   a stat every time it goes up; here it's a +/- stepper, and the record
   survives the character.

   DELIBERATELY SEPARATE FROM THE WIKI'S OWN DATA.
   Everything lives in userdata/adventurers.json and is never merged into the
   legends-derived pages. That's not laziness. Re-importing a fresh legends
   dump rebuilds worlds/<world>/parsed/ wholesale, and anything folded in
   there would be overwritten or duplicated. Keeping adventurers outside that
   directory is what guarantees a character you retire today still exists
   after you dump a world that's aged another two hundred years. The wiki
   will grow its own account of them from the real data; this is yours.

   Namespaced in an IIFE for the same reason map.js is: several globals here
   would otherwise collide with the wiki's.
   ========================================================================= */
(function(){
'use strict';

const API='/api';
const $=s=>document.querySelector(s);
const A=()=>window.ADV;

const S = {
  world:null,
  list:[],          // roster for this world
  cur:null,         // the open character
  tab:'sheet',      // sheet | skills | journal | quests | associates | inventory | tools
  skillFilter:'',
  showUnskilled:false,
  dice:{last:null, log:[]},
  calc:{expr:'', out:''},
  dirty:false,
};

function esc(s){ return window.esc ? window.esc(s) : String(s==null?'':s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function toast(m){ if(window.toast) window.toast(m); }
function sfx(k,v){ if(window.playSfx) window.playSfx(k,v); }
async function api(p,o){ const r=await fetch(API+p,o); if(!r.ok) throw new Error(await r.text()); return r.json(); }
function post(p,body){ return api(p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); }
const uid=()=>Math.random().toString(36).slice(2,10);

/* ---------- model ---------- */
function blankCharacter(){
  const d=A();
  const ch={
    id:uid(), name:'', race:'', civ:'', profession:'', status:'Active',
    born:'', homeland:'', deity:'', afflictions:'', wealth:'', notes:'',
    portrait:null, images:[],
    attributes:{}, skills:{},
    journal:[], quests:[], associates:[], companions:[], affiliations:[],
    inventory:[],
    created:new Date().toISOString(),
  };
  d.ALL_ATTRIBUTES.forEach(a=>ch.attributes[a]=d.ATTR_DEFAULT);
  // skills all start Unskilled. A sheet claiming you dabble in 134 things
  // would be a lie, which is exactly why "Unskilled" exists as level 0 here
  d.ALL_SKILLS.forEach(s=>ch.skills[s]=0);
  return ch;
}
/* Older records won't have every field; fill gaps rather than crash on them. */
function normalise(ch){
  const d=A(), b=blankCharacter();
  const out=Object.assign({}, b, ch);
  out.attributes=Object.assign({}, b.attributes, ch.attributes||{});
  out.skills=Object.assign({}, b.skills, ch.skills||{});
  ['journal','quests','associates','companions','affiliations','inventory','images']
    .forEach(k=>{ if(!Array.isArray(out[k])) out[k]=[]; });
  return out;
}

async function loadList(){
  try{ const d=await api('/adventurers/'+S.world); S.list=(d.adventurers||[]).map(normalise); }
  catch(e){ S.list=[]; }
}
async function save(silent){
  if(!S.cur) return;
  S.cur.updated=new Date().toISOString();
  try{
    const d=await post('/adventurers/'+S.world,{action:'save',character:S.cur});
    S.list=(d.adventurers||[]).map(normalise);
    S.dirty=false;
    if(!silent) toast('Saved.');
  }catch(e){ toast('Save failed: '+e.message); }
}
let _saveTimer=null;
function autosave(){
  S.dirty=true; renderDirty();
  clearTimeout(_saveTimer);
  _saveTimer=setTimeout(()=>save(true), 900);   // debounced: steppers fire fast
}
function renderDirty(){
  const el=document.getElementById('advDirty');
  if(el) el.textContent = S.dirty ? 'saving…' : 'saved';
}

/* =========================================================================
   ROSTER
   ========================================================================= */
function renderRoster(){
  const d=A();
  let h=`<div class="crumbs"><a href="#/w/${S.world}/home">${esc((window.STATE&&STATE.meta&&STATE.meta.world_name)||S.world)}</a> &rsaquo; Adventurers</div>
    <div class="adv-head">
      <h1>Adventurers</h1>
      <button class="btn primary" onclick="Adv.newCharacter()">New character</button>
    </div>
    <p class="lead-para">Character sheets for keeping up with your adventurers!</p>`;
  if(!S.list.length){
    h+=`<div class="stats-soon"><h3>No characters yet</h3>
      <p class="hint">Roll someone up in Adventure Mode, then start a sheet for them here.</p></div>`;
  }else{
    h+=`<div class="adv-roster">`+S.list.map(c=>{
      const port=c.portrait?`<div class="ar-port" style="background-image:url('/userdata/images/${esc(c.portrait)}')"></div>`
                           :`<div class="ar-port empty">&#9823;</div>`;
      const top=topSkills(c,3);
      return `<div class="adv-card ${c.status.toLowerCase()}" onclick="Adv.open('${c.id}')">
        ${port}
        <div class="ar-body">
          <div class="ar-name">${esc(c.name||'Unnamed')}</div>
          <div class="ar-sub">${esc([c.race,c.profession].filter(Boolean).join(' · ')||'-')}</div>
          <div class="ar-skills">${top.map(t=>`<span class="pill">${esc(t)}</span>`).join('')||''}</div>
          <div class="ar-foot"><span class="ar-status ${c.status.toLowerCase()}">${esc(c.status)}</span>
            <span class="hint">${(c.journal||[]).length} entries · ${(c.associates||[]).length} known</span></div>
        </div></div>`;
    }).join('')+`</div>`;
  }
  $('#view').innerHTML=h;
}
function topSkills(c,n){
  const d=A();
  return Object.entries(c.skills||{}).filter(([,v])=>v>0)
    .sort((a,b)=>b[1]-a[1]).slice(0,n)
    .map(([k,v])=>`${k}, ${d.SKILL_LEVELS[v].name}`);
}

function newCharacter(){
  S.cur=blankCharacter();
  S.tab='sheet';
  sfx('sectionOpen',0.4);
  renderSheet();
  save(true);
}
function open(id){
  const c=S.list.find(x=>x.id===id);
  if(!c) return;
  S.cur=normalise(JSON.parse(JSON.stringify(c)));
  S.tab='sheet';
  sfx('pageTurn',0.4);
  renderSheet();
}
function backToRoster(){
  save(true);
  S.cur=null;
  sfx('pageTurn',0.4);
  renderRoster();
}
async function deleteCharacter(){
  if(!S.cur) return;
  if(!confirm(`Delete "${S.cur.name||'this character'}" for good?\n\nThis cannot be undone.`)) return;
  await post('/adventurers/'+S.world,{action:'remove',id:S.cur.id});
  await loadList();
  S.cur=null;
  renderRoster();
  toast('Deleted.');
}

/* =========================================================================
   SHEET SHELL
   ========================================================================= */
const TABS=[['sheet','Sheet'],['skills','Skills & attributes'],['journal','Journal'],
            ['quests','Quest log'],['associates','Associates'],['inventory','Inventory'],
            ['tools','Tools']];
function setTab(t){ S.tab=t; sfx('uiClick',0.3); renderSheet(); }

function renderSheet(){
  if(!S.cur){ renderRoster(); return; }
  const c=S.cur;
  const port=c.portrait?`<div class="as-port" style="background-image:url('/userdata/images/${esc(c.portrait)}')"></div>`
                       :`<div class="as-port empty">&#9823;</div>`;
  let h=`<div class="crumbs"><a href="#/w/${S.world}/adventurers" onclick="Adv.backToRoster();return false;">Adventurers</a> &rsaquo; ${esc(c.name||'Unnamed')}</div>
  <div class="adv-sheet">
    <div class="as-top">
      ${port}
      <div class="as-id">
        <input class="as-name" value="${esc(c.name)}" placeholder="Character name"
          oninput="Adv.field('name',this.value)">
        <div class="as-idrow">
          <label>Race <input value="${esc(c.race)}" oninput="Adv.field('race',this.value)" placeholder="dwarf"></label>
          <label>Profession <input value="${esc(c.profession)}" oninput="Adv.field('profession',this.value)" placeholder="wanderer"></label>
          <label>Status <select onchange="Adv.field('status',this.value)">
            ${A().CHAR_STATUS.map(s=>`<option${c.status===s?' selected':''}>${s}</option>`).join('')}
          </select></label>
        </div>
      </div>
      <div class="as-actions">
        <span id="advDirty" class="hint">saved</span>
        <button class="btn" onclick="Adv.save()">Save now</button>
        <button class="btn" onclick="Adv.backToRoster()">All characters</button>
      </div>
    </div>
    <div class="as-tabs">${TABS.map(([k,l])=>
      `<button class="${S.tab===k?'on':''}" onclick="Adv.setTab('${k}')">${l}</button>`).join('')}</div>
    <div class="as-body" id="advBody"></div>
  </div>`;
  $('#view').innerHTML=h;
  renderBody();
  renderDirty();
}
function renderBody(){
  const el=document.getElementById('advBody'); if(!el) return;
  const fn={sheet:bodySheet, skills:bodySkills, journal:bodyJournal, quests:bodyQuests,
            associates:bodyAssociates, inventory:bodyInventory, tools:bodyTools}[S.tab];
  el.innerHTML = fn ? fn(S.cur) : '';
}
/* Filter boxes call renderBody() on every keystroke (the whole tab is one
   innerHTML swap, simplest way to keep the list in sync), but that
   destroys and recreates the <input> itself, so the browser drops focus
   and the caret after each character. This re-renders, then finds the
   still-focused-by-name filter input in the fresh DOM and restores focus
   and the caret position so typing feels continuous. */
function renderBodyKeepFocus(selector, caret){
  renderBody();
  const el=document.querySelector(selector);
  if(el){ el.focus(); try{ el.setSelectionRange(caret,caret); }catch(e){} }
}
function field(k,v){ if(!S.cur) return; S.cur[k]=v; autosave(); }

/* ---------- sheet tab ---------- */
function bodySheet(c){
  return `<div class="as-cols">
    <div class="as-col">
      <h3>Origins</h3>
      ${row('Civilization','civ',c.civ,'the people they belong to')}
      ${row('Homeland','homeland',c.homeland,'where they are from')}
      ${row('Born','born',c.born,'e.g. 12th Granite, 168')}
      ${row('Deity','deity',c.deity,'who they answer to, if anyone')}
      <h3>Condition</h3>
      <label class="as-lab">Afflictions, scars &amp; disabilities</label>
      <textarea rows="4" placeholder="Old wounds, missing parts, curses. Anything permanent worth remembering."
        oninput="Adv.field('afflictions',this.value)">${esc(c.afflictions)}</textarea>
      <label class="as-lab">Wealth</label>
      <textarea rows="3" placeholder="Coins, gems, holdings. However you like to count it."
        oninput="Adv.field('wealth',this.value)">${esc(c.wealth)}</textarea>
    </div>
    <div class="as-col">
      <h3>Notes</h3>
      <textarea rows="16" placeholder="Anything that doesn't fit elsewhere. Goals, oaths, grudges, a description of their face."
        oninput="Adv.field('notes',this.value)">${esc(c.notes)}</textarea>
      <h3>Portrait &amp; images</h3>
      <div class="as-gal">${(c.images||[]).map(im=>
        `<figure class="asg${c.portrait===im.filename?' star':''}">
           <img src="/userdata/images/${esc(im.filename)}" alt="">
           <figcaption>${esc(im.caption||'')}</figcaption>
           <div class="asg-ctl">
             <button title="Use as portrait" onclick="Adv.setPortrait('${esc(im.filename)}')">&#9733;</button>
             <button title="Remove" onclick="Adv.removeImage('${im.id}')">&times;</button>
           </div>
         </figure>`).join('')}
        <button class="asg-add" onclick="Adv.addImage()">+ Add an image</button>
      </div>
      <div class="hint">Portraits, places you've been, things you carry, people you've met.</div>
      <h3 style="margin-top:18px">Danger zone</h3>
      <button class="btn danger" onclick="Adv.deleteCharacter()">Delete this character</button>
    </div>
  </div>`;
}
function row(label,key,val,ph){
  return `<label class="as-lab">${label}</label>
    <input value="${esc(val)}" placeholder="${esc(ph||'')}" oninput="Adv.field('${key}',this.value)">`;
}

/* =========================================================================
   ATTRIBUTES + SKILLS. The steppers
   ========================================================================= */
function bodySkills(c){
  const d=A();
  let h=`<div class="as-sec"><h3>Attributes</h3>
    <div class="hint" style="margin-bottom:8px">Best to worst, the way the game describes them.
      "(no description)" is DF's own word for unremarkable, and the sensible default.</div>`;
  d.ATTRIBUTE_GROUPS.forEach(([grp,attrs])=>{
    h+=`<div class="attr-grp"><div class="attr-gh">${grp}</div><div class="attr-rows">`;
    attrs.forEach(a=>{
      const v=c.attributes[a]!=null?c.attributes[a]:d.ATTR_DEFAULT;
      h+=`<div class="attr-row">
        <span class="attr-n">${a}</span>
        <button class="stp" onclick="Adv.bumpAttr('${a}',1)" title="Worse">&minus;</button>
        <span class="attr-v v${v}">${esc(d.ATTR_SCALE[v])}</span>
        <button class="stp" onclick="Adv.bumpAttr('${a}',-1)" title="Better">+</button>
      </div>`;
    });
    h+=`</div></div>`;
  });
  h+=`</div>`;

  const q=S.skillFilter.toLowerCase();
  h+=`<div class="as-sec"><h3>Skills</h3>
    <div class="sk-tools">
      <input data-filter="skill" placeholder="Filter skills…" value="${esc(S.skillFilter)}" oninput="Adv.filterSkills(this.value,this.selectionStart)">
      <label class="wsnap"><input type="checkbox" ${S.showUnskilled?'checked':''}
        onchange="Adv.toggleUnskilled()"> Show unskilled</label>
      <span class="hint">${Object.values(c.skills).filter(v=>v>0).length} of ${d.ALL_SKILLS.length} learned</span>
    </div>`;
  d.SKILL_GROUPS.forEach(([grp,skills])=>{
    const vis=skills.filter(s=>{
      if(q && !s.toLowerCase().includes(q) && !grp.toLowerCase().includes(q)) return false;
      if(!S.showUnskilled && !q && (c.skills[s]||0)===0) return false;
      return true;
    });
    if(!vis.length) return;
    h+=`<div class="sk-grp"><div class="sk-gh">${esc(grp)}</div><div class="sk-rows">`;
    vis.forEach(s=>{
      const v=c.skills[s]||0;
      h+=`<div class="sk-row${v?'':' zero'}">
        <span class="sk-n">${esc(s)}</span>
        <button class="stp" onclick="Adv.bumpSkill('${esc(s).replace(/'/g,"\\'")}',-1)">&minus;</button>
        <span class="sk-v l${v}">${esc(d.SKILL_LEVELS[v].name)}</span>
        <button class="stp" onclick="Adv.bumpSkill('${esc(s).replace(/'/g,"\\'")}',1)">+</button>
      </div>`;
    });
    h+=`</div></div>`;
  });
  if(!S.showUnskilled && !q)
    h+=`<div class="hint" style="margin-top:10px">Only learned skills are shown.
        Tick “Show unskilled” to raise a new one.</div>`;
  h+=`</div>`;
  return h;
}
/* Attributes run best to worst, so +1 in the array is a step down in
   quality. The buttons are labelled by meaning, not by index direction. */
function bumpAttr(a,dir){
  const d=A(), c=S.cur;
  const v=(c.attributes[a]!=null?c.attributes[a]:d.ATTR_DEFAULT)+dir;
  c.attributes[a]=Math.max(0,Math.min(d.ATTR_SCALE.length-1,v));
  sfx('uiClick',0.18); autosave(); renderBody();
}
function bumpSkill(s,dir){
  const d=A(), c=S.cur;
  const v=(c.skills[s]||0)+dir;
  c.skills[s]=Math.max(0,Math.min(d.SKILL_LEVELS.length-1,v));
  sfx('uiClick',0.18); autosave(); renderBody();
}
function filterSkills(v,caret){ S.skillFilter=v; renderBodyKeepFocus('input[data-filter="skill"]', caret); }
function toggleUnskilled(){ S.showUnskilled=!S.showUnskilled; renderBody(); }

/* =========================================================================
   DATES. The real dwarven calendar
   ========================================================================= */
function dateSelect(prefix, obj){
  const d=A();
  const y=obj[prefix+'_year']||'', m=obj[prefix+'_month']||'', dd=obj[prefix+'_day']||'';
  return `<span class="dt">
    <input class="dt-y" type="number" placeholder="Year" value="${esc(y)}"
      oninput="Adv.setDate('${prefix}','year',this.value)">
    <select onchange="Adv.setDate('${prefix}','month',this.value)">
      <option value="">Month</option>
      ${d.MONTHS.map(mo=>`<option value="${mo.n}"${String(m)===String(mo.n)?' selected':''}>${mo.name} (${mo.season})</option>`).join('')}
    </select>
    <select onchange="Adv.setDate('${prefix}','day',this.value)">
      <option value="">Day</option>
      ${Array.from({length:d.DAYS_IN_MONTH},(_,i)=>i+1).map(n=>`<option value="${n}"${String(dd)===String(n)?' selected':''}>${n}</option>`).join('')}
    </select></span>`;
}
function fmtDate(o,prefix){
  const d=A();
  const y=o[prefix+'_year'], m=o[prefix+'_month'], dd=o[prefix+'_day'];
  if(!y && !m && !dd) return '';
  const mo=d.MONTHS.find(x=>String(x.n)===String(m));
  return [dd?dd+(dd==1?'st':dd==2?'nd':dd==3?'rd':'th'):null, mo?mo.name:null, y?'· '+y:null]
    .filter(Boolean).join(' ');
}
/* sortable key so entries fall in world-chronological order */
function dateKey(o,prefix){
  const y=+(o[prefix+'_year']||0), m=+(o[prefix+'_month']||0), d=+(o[prefix+'_day']||0);
  return y*10000+m*100+d;
}
let _editing=null;   // {list, id, prefix} while a date select is open
function setDate(prefix, part, val){
  if(!_editing) return;
  const arr=S.cur[_editing.list];
  const it=arr.find(x=>x.id===_editing.id);
  if(!it) return;
  it[prefix+'_'+part]= val===''? '' : (isNaN(+val)? val : +val);
  autosave();
}
function beginEdit(list,id){ _editing={list,id}; }

/* =========================================================================
   JOURNAL
   ========================================================================= */
function bodyJournal(c){
  const entries=c.journal.slice().sort((a,b)=>dateKey(b,'when')-dateKey(a,'when'));
  let h=`<div class="as-sec">
    <div class="sec-head"><h3>Journal</h3>
      <button class="btn primary" onclick="Adv.addJournal()">New entry</button></div>
    <div class="hint" style="margin-bottom:10px">Newest first. Use [[Name]] to point at a
      person or place in the annals. The same linking the rest of the wiki uses.</div>`;
  if(!entries.length) h+=`<div class="empty-hint">Nothing written yet.</div>`;
  entries.forEach(e=>{
    const when=fmtDate(e,'when'), due=fmtDate(e,'due');
    h+=`<article class="jr" onfocusin="Adv.beginEdit('journal','${e.id}')">
      <div class="jr-head">
        <input class="jr-t" value="${esc(e.title||'')}" placeholder="Title"
          oninput="Adv.itemField('journal','${e.id}','title',this.value)">
        <button class="jr-x" title="Delete entry" onclick="Adv.removeItem('journal','${e.id}')">&times;</button>
      </div>
      <div class="jr-dates">
        <span class="dt-lab">Written</span>${dateSelect('when',e)}
        <label class="wsnap"><input type="checkbox" ${e.has_due?'checked':''}
          onchange="Adv.beginEdit('journal','${e.id}');Adv.itemField('journal','${e.id}','has_due',this.checked)"> Due by</label>
        ${e.has_due?`<span class="dt-lab">Due</span>${dateSelect('due',e)}`:''}
      </div>
      <textarea rows="5" placeholder="What happened."
        oninput="Adv.itemField('journal','${e.id}','text',this.value)">${esc(e.text||'')}</textarea>
      <div class="jr-foot">${when?`<span>${esc(when)}</span>`:''}${due?`<span class="jr-due">due ${esc(due)}</span>`:''}
        ${renderLinks(e.text)}</div>
    </article>`;
  });
  return h+`</div>`;
}
/* [[Name]] mentions become real links into the wiki's search, so a journal
   line about a person you met is one click from their actual page */
function renderLinks(text){
  const m=(text||'').match(/\[\[([^\]]+)\]\]/g);
  if(!m) return '';
  const seen=[...new Set(m.map(x=>x.slice(2,-2).trim()))].slice(0,8);
  return seen.map(n=>`<a class="jr-link" href="#/search/${encodeURIComponent(n)}">${esc(n)}</a>`).join('');
}
function addJournal(){
  S.cur.journal.unshift({id:uid(), title:'', text:'', when_year:'', when_month:'', when_day:'', has_due:false});
  sfx('sectionOpen',0.35); autosave(); renderBody();
}

/* =========================================================================
   QUEST LOG
   ========================================================================= */
function bodyQuests(c){
  const states=A().QUEST_STATES;
  let h=`<div class="as-sec">
    <div class="sec-head"><h3>Quest log</h3>
      <button class="btn primary" onclick="Adv.addQuest()">New quest</button></div>`;
  states.forEach(st=>{
    const qs=c.quests.filter(q=>q.state===st);
    h+=`<div class="q-grp q-${st}"><div class="q-gh">${st}<span class="q-n">${qs.length}</span></div>`;
    if(!qs.length) h+=`<div class="empty-hint">None.</div>`;
    qs.forEach(q=>{
      const due=fmtDate(q,'due');
      h+=`<div class="q-item" onfocusin="Adv.beginEdit('quests','${q.id}')">
        <div class="q-top">
          <input class="q-t" value="${esc(q.title||'')}" placeholder="What needs doing"
            oninput="Adv.itemField('quests','${q.id}','title',this.value)">
          <select onchange="Adv.itemField('quests','${q.id}','state',this.value)">
            ${states.map(x=>`<option value="${x}"${q.state===x?' selected':''}>${x}</option>`).join('')}
          </select>
          <button class="jr-x" onclick="Adv.removeItem('quests','${q.id}')">&times;</button>
        </div>
        <div class="jr-dates"><span class="dt-lab">Due</span>${dateSelect('due',q)}</div>
        <textarea rows="3" placeholder="Where, who from, what's promised."
          oninput="Adv.itemField('quests','${q.id}','text',this.value)">${esc(q.text||'')}</textarea>
        <div class="jr-foot">${due?`<span class="jr-due">due ${esc(due)}</span>`:''}${renderLinks(q.text)}</div>
      </div>`;
    });
    h+=`</div>`;
  });
  return h+`</div>`;
}
function addQuest(){
  S.cur.quests.unshift({id:uid(), title:'', text:'', state:'active'});
  sfx('sectionOpen',0.35); autosave(); renderBody();
}

/* =========================================================================
   ASSOCIATES / COMPANIONS / AFFILIATIONS
   ========================================================================= */
function bodyAssociates(c){
  const d=A();
  const q=(S.assocFilter||'').toLowerCase();
  const list=c.associates.filter(a=>!q || (a.name||'').toLowerCase().includes(q)
    || (a.kind||'').toLowerCase().includes(q) || (a.reputation||'').toLowerCase().includes(q));
  let h=`<div class="as-sec">
    <div class="sec-head"><h3>Associates</h3>
      <button class="btn primary" onclick="Adv.addAssociate()">Add someone</button></div>
    <div class="sk-tools">
      <input data-filter="assoc" placeholder="Filter by name, kind or standing…" value="${esc(S.assocFilter||'')}"
        oninput="Adv.filterAssoc(this.value,this.selectionStart)">
      <span class="hint">${c.associates.length} known</span>
    </div>`;
  if(!list.length) h+=`<div class="empty-hint">Nobody yet.</div>`;
  h+=list.map(a=>`<div class="assoc">
      <input class="a-n" value="${esc(a.name||'')}" placeholder="Name"
        oninput="Adv.itemField('associates','${a.id}','name',this.value)">
      <select onchange="Adv.itemField('associates','${a.id}','kind',this.value)">
        ${d.ASSOCIATE_KINDS.map(k=>`<option${a.kind===k?' selected':''}>${k}</option>`).join('')}
      </select>
      <select onchange="Adv.itemField('associates','${a.id}','reputation',this.value)">
        ${d.REPUTATION.map(k=>`<option${a.reputation===k?' selected':''}>${k}</option>`).join('')}
      </select>
      <input class="a-note" value="${esc(a.notes||'')}" placeholder="Where you met, what they want…"
        oninput="Adv.itemField('associates','${a.id}','notes',this.value)">
      <a class="a-look" title="Find them in the annals"
        href="#/search/${encodeURIComponent(a.name||'')}">&#128269;</a>
      <button class="jr-x" onclick="Adv.removeItem('associates','${a.id}')">&times;</button>
    </div>`).join('');
  h+=`</div>`;

  h+=`<div class="as-sec">
    <div class="sec-head"><h3>Companions</h3>
      <button class="btn" onclick="Adv.addCompanion()">Add companion</button></div>
    <div class="hint" style="margin-bottom:8px">Whoever is travelling with you right now.</div>`;
  if(!c.companions.length) h+=`<div class="empty-hint">Travelling alone.</div>`;
  h+=c.companions.map(x=>`<div class="assoc">
      <input class="a-n" value="${esc(x.name||'')}" placeholder="Name"
        oninput="Adv.itemField('companions','${x.id}','name',this.value)">
      <input class="a-note" value="${esc(x.notes||'')}" placeholder="Race, weapon, how they joined…"
        oninput="Adv.itemField('companions','${x.id}','notes',this.value)">
      <button class="jr-x" onclick="Adv.removeItem('companions','${x.id}')">&times;</button>
    </div>`).join('');
  h+=`</div>`;

  h+=`<div class="as-sec">
    <div class="sec-head"><h3>Affiliations</h3>
      <button class="btn" onclick="Adv.addAffiliation()">Add affiliation</button></div>
    <div class="hint" style="margin-bottom:8px">Civilizations, guilds, temples, mercenary
      companies, and where you stand with them.</div>`;
  if(!c.affiliations.length) h+=`<div class="empty-hint">Beholden to no one.</div>`;
  h+=c.affiliations.map(x=>`<div class="assoc">
      <input class="a-n" value="${esc(x.name||'')}" placeholder="Group name"
        oninput="Adv.itemField('affiliations','${x.id}','name',this.value)">
      <select onchange="Adv.itemField('affiliations','${x.id}','standing',this.value)">
        ${d.REPUTATION.map(k=>`<option${x.standing===k?' selected':''}>${k}</option>`).join('')}
      </select>
      <input class="a-note" value="${esc(x.notes||'')}" placeholder="Rank, oaths, debts…"
        oninput="Adv.itemField('affiliations','${x.id}','notes',this.value)">
      <a class="a-look" href="#/search/${encodeURIComponent(x.name||'')}">&#128269;</a>
      <button class="jr-x" onclick="Adv.removeItem('affiliations','${x.id}')">&times;</button>
    </div>`).join('');
  return h+`</div>`;
}
function addAssociate(){ S.cur.associates.unshift({id:uid(),name:'',kind:'Acquaintance',reputation:'Neutral',notes:''}); autosave(); renderBody(); }
function addCompanion(){ S.cur.companions.unshift({id:uid(),name:'',notes:''}); autosave(); renderBody(); }
function addAffiliation(){ S.cur.affiliations.unshift({id:uid(),name:'',standing:'Neutral',notes:''}); autosave(); renderBody(); }
function filterAssoc(v,caret){ S.assocFilter=v; renderBodyKeepFocus('input[data-filter="assoc"]', caret); }

/* =========================================================================
   INVENTORY
   ========================================================================= */
function bodyInventory(c){
  const d=A();
  const q=(S.invFilter||'').toLowerCase();
  const list=c.inventory.filter(i=>!q || (i.name||'').toLowerCase().includes(q)
    || (i.category||'').toLowerCase().includes(q) || (i.location||'').toLowerCase().includes(q));
  let h=`<div class="as-sec">
    <div class="sec-head"><h3>Holdings</h3>
      <button class="btn primary" onclick="Adv.addItem()">Add something</button></div>
    <div class="hint" style="margin-bottom:8px">Not just what's on your back. Animals, houses,
      titles and claims all belong here too.</div>
    <div class="sk-tools">
      <input data-filter="inv" placeholder="Filter…" value="${esc(S.invFilter||'')}" oninput="Adv.filterInv(this.value,this.selectionStart)">
      <span class="hint">${c.inventory.length} entries</span>
    </div>
    <div class="inv-head"><span>Item</span><span>Kind</span><span>Where</span><span>Qty</span><span>Notes</span><span></span></div>`;
  if(!list.length) h+=`<div class="empty-hint">Nothing recorded.</div>`;
  h+=list.map(i=>`<div class="inv-row">
      <input value="${esc(i.name||'')}" placeholder="What it is"
        oninput="Adv.itemField('inventory','${i.id}','name',this.value)">
      <select onchange="Adv.itemField('inventory','${i.id}','category',this.value)">
        ${d.ITEM_CATEGORIES.map(k=>`<option${i.category===k?' selected':''}>${k}</option>`).join('')}
      </select>
      <select onchange="Adv.itemField('inventory','${i.id}','location',this.value)">
        ${d.ITEM_LOCATIONS.map(k=>`<option${i.location===k?' selected':''}>${k}</option>`).join('')}
      </select>
      <input class="inv-q" type="number" min="0" value="${esc(i.qty!=null?i.qty:1)}"
        oninput="Adv.itemField('inventory','${i.id}','qty',this.value)">
      <input value="${esc(i.notes||'')}" placeholder="Material, quality, story…"
        oninput="Adv.itemField('inventory','${i.id}','notes',this.value)">
      <button class="jr-x" onclick="Adv.removeItem('inventory','${i.id}')">&times;</button>
    </div>`).join('');
  return h+`</div>`;
}
function addItem(){
  S.cur.inventory.unshift({id:uid(),name:'',category:'Miscellaneous',location:'Carried',qty:1,notes:''});
  autosave(); renderBody();
}
function filterInv(v,caret){ S.invFilter=v; renderBodyKeepFocus('input[data-filter="inv"]', caret); }

/* shared list helpers */
function itemField(list,id,key,val){
  const it=(S.cur[list]||[]).find(x=>x.id===id);
  if(!it) return;
  it[key]=val;
  autosave();
  // re-render only where the change alters layout, so typing doesn't steal focus
  if(key==='state'||key==='has_due') renderBody();
}
function removeItem(list,id){
  S.cur[list]=(S.cur[list]||[]).filter(x=>x.id!==id);
  sfx('sectionClose',0.3); autosave(); renderBody();
}

/* =========================================================================
   TOOLS. Dice + calculator
   ========================================================================= */
function bodyTools(){
  const log=S.dice.log.slice(0,12);
  return `<div class="as-cols">
    <div class="as-col">
      <h3>Dice</h3>
      <div class="hint" style="margin-bottom:8px">Standard notation: <code>2d6+1</code>, <code>d20</code>, <code>2d6+1d4+3</code>.</div>
      <div class="dice-row">
        <input id="diceExpr" value="${esc(S.dice.expr||'1d20')}" placeholder="2d6+1"
          onkeydown="if(event.key==='Enter')Adv.roll()">
        <button class="btn primary" onclick="Adv.roll()">Roll</button>
      </div>
      <div class="dice-quick">
        ${['d4','d6','d8','d10','d12','d20','d100','2d6','3d6'].map(x=>
          `<button onclick="Adv.roll('${x}')">${x}</button>`).join('')}
      </div>
      ${S.dice.last!=null?`<div class="dice-out">
        <div class="dice-total">${S.dice.last.total}</div>
        <div class="dice-detail">${esc(S.dice.last.detail)}</div></div>`:''}
      ${log.length?`<div class="dice-log"><div class="as-lab">Recent</div>
        ${log.map(l=>`<div class="dl"><span>${esc(l.expr)}</span><b>${l.total}</b><span class="hint">${esc(l.detail)}</span></div>`).join('')}
        <button class="btn" onclick="Adv.clearDice()">Clear</button></div>`:''}
    </div>
    <div class="as-col">
      <h3>Calculator</h3>
      <input id="calcExpr" class="calc-in" value="${esc(S.calc.expr)}" placeholder="12 * 28 + 6"
        oninput="Adv.calc(this.value)" onkeydown="if(event.key==='Enter')Adv.calc(this.value)">
      <div class="calc-out">${S.calc.out===''?'<span class="hint">…</span>':esc(S.calc.out)}</div>
      <div class="calc-pad">
        ${['7','8','9','/','4','5','6','*','1','2','3','-','0','.','(',')']
          .map(k=>`<button onclick="Adv.calcKey('${k}')">${k}</button>`).join('')}
        <button onclick="Adv.calcKey('+')">+</button>
        <button class="wide" onclick="Adv.calcClear()">clear</button>
      </div>
    </div>
  </div>`;
}

/* ---- calendar: full standalone page ----
   12 months of 28 days (MONTHS/DAYS_IN_MONTH from adv_data.js. Same
   source the journal/quest date pickers use). Unlike those pickers, this
   is wired to real world data: /api/w/<world>/calendar?year=Y returns
   every event that has a recorded day-of-year (converted server-side from
   DF's own seconds72 tick counter), grouped by month-day. A day with
   events gets a marker; clicking it opens a small list of that day's
   events, rendered with the same clickable-entity tokens the rest of the
   app already uses, so "a war started" links straight to that war. */
const CAL = {
  year:1, month:1, openDay:null,
  loadedYear:null, days:{},   // {"month-day": [{id,cat,type,tokens}, ...]}
  loading:false,
};
async function calLoadYear(year){
  if(CAL.loadedYear===year || CAL.loading) return;
  CAL.loading=true;
  try{
    const r=await fetch(`/api/w/${S.world}/calendar?year=${year}`);
    const body=await r.json();
    CAL.days = body.days||{};
    CAL.loadedYear = year;
  }catch(e){ CAL.days={}; CAL.loadedYear=null; }
  CAL.loading=false;
  renderCalendarPage();
}
function calStep(delta){
  let m=CAL.month+delta, y=CAL.year;
  if(m<1){ m=12; y-=1; } else if(m>12){ m=1; y+=1; }
  CAL.month=m; CAL.year=Math.max(1,y); CAL.openDay=null;
  renderCalendarPage();
  if(CAL.loadedYear!==CAL.year) calLoadYear(CAL.year);
}
function calGotoMonth(m){ CAL.month=m; CAL.openDay=null; renderCalendarPage(); }
function calSetYear(y){
  y=Math.max(1, parseInt(y,10)||1);
  CAL.year=y; CAL.openDay=null;
  renderCalendarPage();
  calLoadYear(y);
}
function calSelectDay(n){ CAL.openDay = CAL.openDay===n ? null : n; renderCalendarPage(); }

function bodyCalendar(){
  const d=A();
  const mo=d.MONTHS.find(m=>m.n===CAL.month) || d.MONTHS[0];
  const days=Array.from({length:d.DAYS_IN_MONTH},(_,i)=>i+1);
  const dayEvents=n => CAL.days[`${CAL.month}-${n}`] || [];
  const openList = CAL.openDay!=null ? dayEvents(CAL.openDay) : null;
  return `<div class="cal-page">
    <div class="cal-toolbar">
      <button onclick="Adv.calStep(-1)" title="Previous month">&#8592;</button>
      <div class="cal-title-big">${esc(mo.name)} <span class="hint">(${esc(mo.season)})</span></div>
      <button onclick="Adv.calStep(1)" title="Next month">&#8594;</button>
      <div class="cal-year-picker">
        <span class="as-lab" style="margin:0">Year</span>
        <input type="number" min="1" value="${CAL.year}" onchange="Adv.calSetYear(this.value)">
      </div>
      ${CAL.loading?'<span class="hint">Loading…</span>':''}
    </div>
    <div class="cal-months-row">
      ${d.MONTHS.map(m=>`<button class="${m.n===CAL.month?'on':''}" onclick="Adv.calGotoMonth(${m.n})">${esc(m.name)}</button>`).join('')}
    </div>
    <div class="cal-grid-big">
      ${['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(w=>`<div class="cal-dow">${w}</div>`).join('')}
      ${days.map(n=>{
        const evs=dayEvents(n);
        return `<button class="cal-cell${evs.length?' has-events':''}${CAL.openDay===n?' open':''}" onclick="Adv.calSelectDay(${n})">
          <span class="cal-daynum">${n}</span>
          ${evs.length?`<span class="cal-marker">${evs.length>1?evs.length:'\u25CF'}</span>`:''}
        </button>`;
      }).join('')}
    </div>
    ${openList ? `<div class="cal-daypanel">
        <div class="as-lab">${esc(mo.name)} ${CAL.openDay}, Year ${CAL.year}</div>
        ${openList.length ? openList.map(ev=>`<div class="cal-event">${calRenderTokens(ev.tokens)}</div>`).join('')
          : `<div class="hint">Nothing on record for this day.</div>`}
      </div>` : ''}
  </div>`;
}
/* renderTokens() (clickable-entity-link prose) is defined globally in
   index.html and shared by every page that shows generated event text.
   Reused as-is rather than duplicated here. */
function calRenderTokens(tokens){ return window.renderTokens ? window.renderTokens(tokens) : ''; }

function renderCalendarPage(){
  const el=document.getElementById('advBody');
  if(el) el.innerHTML = bodyCalendar();
}
function mountCalendarStandalone(world){
  S.world=world;
  CAL.openDay=null;
  $('#view').innerHTML = `<div class="entity-page as-page">
    <div class="entity-head"><div><div class="kind">Game Tools</div><h1>Calendar</h1></div></div>
    <div id="advBody"></div>
  </div>`;
  renderCalendarPage();
  calLoadYear(CAL.year);
}
/* Dice notation parser. Supports a chain of signed terms rather than just
   one die group and one flat modifier, so things like 2d6+1d4+3 or
   d20+5-2 work, not just 2d6+1. Anything left over after matching valid
   terms is rejected rather than silently ignored. */
function parseDice(expr){
  const s=(expr||'').replace(/\s+/g,'').toLowerCase();
  if(!s) return null;
  const re=/([+-]?)(\d*d\d+|\d+)/gi;
  let m, terms=[], matchedLen=0;
  while((m=re.exec(s))){
    matchedLen+=m[0].length;
    const sign = m[1]==='-' ? -1 : 1;
    const tok = m[2];
    const dMatch=/^(\d*)d(\d+)$/i.exec(tok);
    if(dMatch){
      const n=Math.min(100, Math.max(1, +(dMatch[1]||1)));
      const sides=Math.min(1000, Math.max(2, +dMatch[2]));
      terms.push({type:'dice', sign, n, sides});
    }else{
      terms.push({type:'flat', sign, value:Math.min(100000, +tok)});
    }
  }
  if(!terms.length || matchedLen!==s.length) return null;
  return terms;
}
function roll(expr){
  if(expr) S.dice.expr=expr;
  else{
    const el=document.getElementById('diceExpr');
    if(el) S.dice.expr=el.value;
  }
  const terms=parseDice(S.dice.expr);
  if(!terms){ toast('Try something like 2d6+1, d20, or 2d6+1d4+3.'); return; }
  let total=0;
  const parts=[];
  terms.forEach(t=>{
    const lead = parts.length ? (t.sign<0?' - ':' + ') : (t.sign<0?'-':'');
    if(t.type==='dice'){
      const rolls=[]; for(let i=0;i<t.n;i++) rolls.push(1+Math.floor(Math.random()*t.sides));
      total += rolls.reduce((a,b)=>a+b,0)*t.sign;
      parts.push(`${lead}${t.n}d${t.sides} [${rolls.join(', ')}]`);
    }else{
      total += t.value*t.sign;
      parts.push(`${lead}${t.value}`);
    }
  });
  const detail=parts.join('');
  S.dice.last={total, detail};
  S.dice.log.unshift({expr:S.dice.expr, total, detail});
  if(S.dice.log.length>40) S.dice.log.pop();
  sfx('uiClick',0.35);
  renderBody();
}
function clearDice(){ S.dice.log=[]; S.dice.last=null; renderBody(); }
/* Calculator: whitelist the expression before evaluating it. Nothing here is
   user-hostile, but evaluating arbitrary text is a bad habit regardless. */
function calc(v){
  S.calc.expr=v;
  const clean=(v||'').replace(/\s+/g,'');
  if(!clean){ S.calc.out=''; renderCalcOut(); return; }
  // Whitelist first, evaluate second. Only digits and arithmetic get through,
  // so identifiers like alert() or process.exit() are rejected before they can
  // reach the evaluator. (** slips through as two \*, which is fine, that is
  // exponentiation, a legitimate thing to want from a calculator.)
  if(!/^[0-9+\-*/().%]+$/.test(clean)){ S.calc.out='error'; renderCalcOut(); return; }
  try{
    const r=Function('"use strict";return ('+clean+')')();
    S.calc.out = (typeof r==='number' && isFinite(r))
      ? (Math.round(r*1e6)/1e6).toLocaleString() : 'error';
  }catch(e){ S.calc.out='error'; }
  renderCalcOut();
}
function renderCalcOut(){
  const el=document.querySelector('.calc-out');
  if(el) el.innerHTML = S.calc.out==='' ? '<span class="hint">…</span>' : esc(S.calc.out);
}
function calcKey(k){
  const el=document.getElementById('calcExpr');
  const v=(el?el.value:S.calc.expr)+k;
  if(el) el.value=v;
  calc(v);
}
function calcClear(){
  const el=document.getElementById('calcExpr');
  if(el) el.value='';
  calc('');
}

/* =========================================================================
   IMAGES
   ========================================================================= */
async function addImage(){
  const inp=document.createElement('input');
  inp.type='file'; inp.accept='image/*';
  inp.onchange=async()=>{
    const f=inp.files[0]; if(!f) return;
    const fd=new FormData(); fd.append('file',f);
    try{
      const r=await fetch(API+'/upload',{method:'POST',body:fd});
      if(!r.ok) throw new Error(await r.text());
      const j=await r.json();
      const cap=prompt('Caption (optional):')||'';
      S.cur.images.push({id:uid(), filename:j.filename, caption:cap});
      if(!S.cur.portrait) S.cur.portrait=j.filename;
      autosave(); renderBody();
      toast('Image added.');
    }catch(e){ toast('Upload failed: '+e.message); }
  };
  inp.click();
}
function setPortrait(fn){ S.cur.portrait=fn; sfx('uiClick',0.3); autosave(); renderBody(); }
function removeImage(id){
  const im=S.cur.images.find(x=>x.id===id);
  S.cur.images=S.cur.images.filter(x=>x.id!==id);
  if(im && S.cur.portrait===im.filename) S.cur.portrait=(S.cur.images[0]||{}).filename||null;
  autosave(); renderBody();
}

window.Adv = {
  _S:S, blankCharacter, normalise, topSkills,
  renderRoster, renderSheet, renderBody, setTab, field,
  newCharacter, open, backToRoster, deleteCharacter, save,
  bumpAttr, bumpSkill, filterSkills, toggleUnskilled,
  loadList, dateSelect, fmtDate, dateKey, setDate, beginEdit,
  addJournal, addQuest, addAssociate, addCompanion, addAffiliation, addItem,
  itemField, removeItem, filterAssoc, filterInv,
  roll, parseDice, clearDice, calc, calcKey, calcClear,
  calStep, calGotoMonth, calSelectDay, calSetYear,
  addImage, setPortrait, removeImage,
  mount: async function(world){
    S.world=world;
    if(!window.ADV){ $('#view').innerHTML='<div class="empty">Reference data failed to load.</div>'; return; }
    await loadList();
    S.cur=null;
    renderRoster();
  },
  /* A standalone copy of the dice/calculator pair for the Game Tools menu
. Same module state and handlers as the ones inside a character
     sheet's Tools tab, just mounted on their own page so they're reachable
     without opening a character first. Reuses #advBody / renderBody()
     as-is rather than a second render path. */
  mountToolsStandalone: function(){
    S.tab='tools';
    $('#view').innerHTML = `<div class="entity-page as-page">
      <div class="entity-head"><div><div class="kind">Game Tools</div><h1>Dice &amp; Calculator</h1></div></div>
      <div id="advBody"></div>
    </div>`;
    renderBody();
  },
  mountCalendarStandalone,
};

})();
