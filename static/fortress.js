/* =========================================================================
   fortress.js  --  Fortress Mode dashboard
   =========================================================================
   The live-data counterpart to adventurer.js. Where that is a hand-filled
   journal, this is a read-only mirror of whatever DFHack last reported.
   Nothing here is generated or inferred, only refreshed on request. See
   server/fortress.py and server/dfhack_scripts/dwarfwiki_export.lua for
   the pipeline that produces the JSON this renders.

   Namespaced in an IIFE for the same reason wall.js/adventurer.js are.
   ========================================================================= */
(function(){
'use strict';

const API='/api';
const $=s=>document.querySelector(s);

function esc(s){ return window.esc ? window.esc(s) : String(s==null?'':s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function toast(m){ if(window.toast) window.toast(m); }
async function api(p,o){ const r=await fetch(API+p,o); return r; }
async function getJSON(p){ const r=await api(p); if(!r.ok) throw new Error('request failed'); return r.json(); }
function post(p,body){ return api(p,{method:'POST',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined}); }

const PHYS_ATTRS=['STRENGTH','AGILITY','TOUGHNESS','ENDURANCE','RECUPERATION','DISEASE_RESISTANCE'];
const MENT_ATTRS=['ANALYTICAL_ABILITY','FOCUS','WILLPOWER','CREATIVITY','INTUITION','PATIENCE',
  'MEMORY','LINGUISTIC_ABILITY','SPATIAL_SENSE','KINESTHETIC_SENSE','EMPATHY','SOCIAL_AWARENESS','MUSICALITY'];
function shortAttr(a){
  return {STRENGTH:'Str',AGILITY:'Agi',TOUGHNESS:'Tou',ENDURANCE:'End',RECUPERATION:'Rec',
    DISEASE_RESISTANCE:'DisR',ANALYTICAL_ABILITY:'Anl',FOCUS:'Foc',WILLPOWER:'Will',CREATIVITY:'Crea',
    INTUITION:'Intu',PATIENCE:'Pat',MEMORY:'Mem',LINGUISTIC_ABILITY:'Ling',SPATIAL_SENSE:'Spat',
    KINESTHETIC_SENSE:'Kin',EMPATHY:'Emp',SOCIAL_AWARENESS:'SocA',MUSICALITY:'Mus'}[a] || a;
}

const S = {
  slots:[], slotId:null,
  settings:{dfhack_dir:''},
  current:null,       // last-loaded current.json (dwarves, stocks, meta, _warnings)
  history:[],
  tab:'roster',        // roster | stocks | history | squads | jobs | rooms | justice | trade | settings
  loading:false,
  err:null, errDetail:null,
  roster:{filter:'', sortCol:'name', sortDir:1, expanded:null},
  stocks:{filter:'', sortCol:'count', sortDir:-1},
  tables:{},   // per-tab {filter, sortCol, sortDir} for squads/jobs/rooms/nobles/justice/trade
};

/* ---------- boot ---------- */
async function mount(){
  $('#view').innerHTML='<div class="loading">Opening the fortress…</div>';
  try{
    const [slots, settings] = await Promise.all([getJSON('/fortress/slots'), getJSON('/fortress/settings')]);
    S.slots = slots.slots || [];
    S.settings = settings;
    if(!S.slotId && S.slots.length) S.slotId = S.slots[0].id;
    if(S.slotId) await loadCurrent(true);
  }catch(e){ /* fine. Render an empty shell, slot picker still works */ }
  render();
}

async function loadCurrent(quiet){
  if(!S.slotId) return;
  try{
    S.current = await getJSON(`/fortress/${S.slotId}/current`);
    S.history = await getJSON(`/fortress/${S.slotId}/history`);
    S.err=null;
  }catch(e){
    S.current=null; S.history=[];
    if(!quiet) S.err='Failed to get data';
  }
}

/* ---------- slots ---------- */
async function newSlot(){
  const name=prompt('Name this fortress (e.g. the save/fort name):');
  if(!name) return;
  const r=await post('/fortress/slots',{name});
  if(!r.ok){ toast('Could not create slot'); return; }
  const slot=await r.json();
  S.slots.push({id:slot.id, name:slot.name});
  S.slotId=slot.id;
  S.current=null; S.history=[];
  render();
}
async function selectSlot(id){
  S.slotId=id; S.current=null; S.history=[]; S.err=null;
  render();
  await loadCurrent(true);
  render();
}
async function deleteSlot(){
  if(!S.slotId) return;
  const slot=S.slots.find(s=>s.id===S.slotId);
  if(!confirm(`Delete "${slot?slot.name:'this fortress'}" and its saved history? This can't be undone.`)) return;
  await api(`/fortress/${S.slotId}`,{method:'DELETE'});
  S.slots=S.slots.filter(s=>s.id!==S.slotId);
  S.slotId=S.slots.length?S.slots[0].id:null;
  S.current=null; S.history=[];
  await mount();
}

/* ---------- refresh ---------- */
async function refresh(){
  if(!S.slotId){ toast('Create a fortress slot first'); return; }
  S.loading=true; S.err=null; S.errDetail=null; render();
  try{
    const r=await post(`/fortress/${S.slotId}/refresh`);
    const body=await r.json();
    if(!r.ok || !body.ok){ S.err='Failed to get data'; S.errDetail=body.detail||null; }
    else{
      if(body.warnings && body.warnings.length) toast(`Refreshed, ${body.warnings.length} field(s) skipped, see Settings`);
      await loadCurrent(false);
    }
  }catch(e){ S.err='Failed to get data'; S.errDetail=String(e); }
  S.loading=false; render();
}

/* ---------- settings ---------- */
async function saveSettings(){
  const dir=$('#dfhackDir')?.value.trim();
  if(!dir) return;
  const r=await post('/fortress/settings',{dfhack_dir:dir});
  S.settings=await r.json();
  toast('Saved');
}
async function installScript(){
  const r=await post('/fortress/settings/install_script');
  const body=await r.json();
  if(body.ok) toast('Script installed to ' + body.installed_to);
  else toast('Install failed: ' + (body.error||'unknown error'));
}

/* ---------- tabs ---------- */
function setTab(t){ S.tab=t; render(); }

/* ---------- roster ---------- */
function rosterRows(){
  const d=(S.current && S.current.dwarves) || [];
  const f=S.roster.filter.toLowerCase();
  let rows = !f ? d.slice() : d.filter(x=>{
    if((x.name||'').toLowerCase().includes(f)) return true;
    if((x.profession||'').toLowerCase().includes(f)) return true;
    return (x.skills||[]).some(sk=>(sk.name||'').toLowerCase().includes(f));
  });
  const col=S.roster.sortCol, dir=S.roster.sortDir;
  rows.sort((a,b)=>{
    let av, bv;
    if(col==='name'||col==='profession'){ av=(a[col]||'').toLowerCase(); bv=(b[col]||'').toLowerCase(); }
    else if(PHYS_ATTRS.includes(col)||MENT_ATTRS.includes(col)){ av=(a.attributes||{})[col]||0; bv=(b.attributes||{})[col]||0; }
    else { av=a[col]||0; bv=b[col]||0; }
    if(av<bv) return -1*dir; if(av>bv) return 1*dir; return 0;
  });
  return rows;
}
function sortRoster(col){
  if(S.roster.sortCol===col) S.roster.sortDir*=-1;
  else { S.roster.sortCol=col; S.roster.sortDir=1; }
  render();
}
function toggleExpand(id){ S.roster.expanded = S.roster.expanded===id ? null : id; render(); }

function rosterTable(){
  const rows=rosterRows();
  const attrCols=[...PHYS_ATTRS, ...MENT_ATTRS];
  const arrow=c=> S.roster.sortCol===c ? (S.roster.sortDir>0?' \u25B2':' \u25BC') : '';
  return `<div class="ft-toolbar">
      <input class="ft-filter" data-filter="roster" placeholder="Filter by name, profession or skill…" value="${esc(S.roster.filter)}"
        oninput="Fortress.setRosterFilter(this.value,this.selectionStart)">
      <span class="hint">${rows.length} of ${(S.current.dwarves||[]).length} dwarves</span>
    </div>
    <div class="ft-tablewrap">
    <table class="ft-table">
      <thead><tr>
        <th onclick="Fortress.sortRoster('name')">Name${arrow('name')}</th>
        <th onclick="Fortress.sortRoster('profession')">Profession${arrow('profession')}</th>
        <th onclick="Fortress.sortRoster('age')">Age${arrow('age')}</th>
        ${attrCols.map(a=>`<th onclick="Fortress.sortRoster('${a}')" title="${esc(a)}">${shortAttr(a)}${arrow(a)}</th>`).join('')}
        <th onclick="Fortress.sortRoster('stress')">Stress${arrow('stress')}</th>
        <th onclick="Fortress.sortRoster('wound_count')">Wounds${arrow('wound_count')}</th>
      </tr></thead>
      <tbody>
        ${rows.map(d=>rosterRow(d, attrCols)).join('')}
      </tbody>
    </table>
    </div>`;
}
function rosterRow(d, attrCols){
  const exp=S.roster.expanded===d.id;
  const attrs=d.attributes||{};
  const main=`<tr class="ft-row${exp?' expanded':''}" onclick="Fortress.toggleExpand(${d.id})">
      <td class="ft-name">${esc(d.name)}</td>
      <td>${esc(d.profession||'')}</td>
      <td>${d.age!=null?Math.floor(d.age):''}</td>
      ${attrCols.map(a=>`<td>${attrs[a]!=null?attrs[a]:''}</td>`).join('')}
      <td>${d.stress!=null?d.stress:''}</td>
      <td>${d.wound_count||0}</td>
    </tr>`;
  if(!exp) return main;
  const skills=(d.skills||[]).slice().sort((a,b)=>b.level-a.level);
  const detail=`<tr class="ft-detail"><td colspan="${3+attrCols.length+2}">
    <div class="ft-detail-cols">
      <div>
        <div class="as-lab">Skills</div>
        ${skills.length?skills.map(sk=>`<div class="ft-chip">${esc(sk.name)} <b>${sk.level}</b></div>`).join(''):'<span class="hint">None</span>'}
      </div>
      <div>
        <div class="as-lab">Labors enabled</div>
        ${(d.labors||[]).length?(d.labors||[]).map(l=>`<span class="pill">${esc(l)}</span>`).join(' '):'<span class="hint">None</span>'}
      </div>
      <div>
        <div class="as-lab">Needs</div>
        ${(d.needs||[]).length?(d.needs||[]).map(n=>`<div class="ft-chip">${esc(n.need)} <b>${n.level}</b></div>`).join(''):'<span class="hint">None</span>'}
      </div>
    </div>
  </td></tr>`;
  return main+detail;
}
function setRosterFilter(v,caret){ S.roster.filter=v; renderKeepFilterFocus('roster', caret); }

/* ---------- stocks ---------- */
function stocksRows(){
  const s=(S.current && S.current.stocks) || [];
  const f=S.stocks.filter.toLowerCase();
  let rows = !f ? s.slice() : s.filter(x=>(x.label||'').toLowerCase().includes(f) || (x.material||'').toLowerCase().includes(f));
  const col=S.stocks.sortCol, dir=S.stocks.sortDir;
  rows.sort((a,b)=>{
    let av=a[col], bv=b[col];
    if(typeof av==='string'){ av=av.toLowerCase(); bv=(bv||'').toLowerCase(); }
    if(av<bv) return -1*dir; if(av>bv) return 1*dir; return 0;
  });
  return rows;
}
function sortStocks(col){
  if(S.stocks.sortCol===col) S.stocks.sortDir*=-1;
  else { S.stocks.sortCol=col; S.stocks.sortDir=col==='count'?-1:1; }
  render();
}
function setStocksFilter(v,caret){ S.stocks.filter=v; renderKeepFilterFocus('stocks', caret); }
function stocksTable(){
  const rows=stocksRows();
  const arrow=c=> S.stocks.sortCol===c ? (S.stocks.sortDir>0?' \u25B2':' \u25BC') : '';
  return `<div class="ft-toolbar">
      <input class="ft-filter" data-filter="stocks" placeholder="Filter stocks…" value="${esc(S.stocks.filter)}" oninput="Fortress.setStocksFilter(this.value,this.selectionStart)">
      <span class="hint">${rows.length} of ${(S.current.stocks||[]).length} item lines</span>
    </div>
    <div class="ft-tablewrap">
    <table class="ft-table">
      <thead><tr>
        <th onclick="Fortress.sortStocks('label')">Item${arrow('label')}</th>
        <th onclick="Fortress.sortStocks('material')">Material${arrow('material')}</th>
        <th onclick="Fortress.sortStocks('count')">Count${arrow('count')}</th>
      </tr></thead>
      <tbody>
        ${rows.map(r=>`<tr><td>${esc(r.label)}</td><td>${esc(r.material)}</td><td>${r.count}</td></tr>`).join('')}
      </tbody>
    </table>
    </div>`;
}

/* ---------- history graph ---------- */
function historyChart(){
  const h=S.history||[];
  if(h.length<2) return `<div class="empty">Refresh a few times over the course of play to build up a history graph.</div>`;
  const W=760, H=260, PAD=36;
  const xs=h.map(p=>p.ts), ys=h.map(p=>p.population||0);
  const minX=Math.min(...xs), maxX=Math.max(...xs);
  const maxY=Math.max(1, ...ys);
  const px=t=> PAD + (maxX>minX ? (t-minX)/(maxX-minX) : 0) * (W-2*PAD);
  const py=v=> H-PAD - (v/maxY) * (H-2*PAD);
  const pts=h.map(p=>`${px(p.ts).toFixed(1)},${py(p.population||0).toFixed(1)}`).join(' ');
  const yTicks=[0, Math.round(maxY/2), maxY];
  return `<div class="hint" style="margin-bottom:10px">Population over time, one point per refresh.</div>
    <svg viewBox="0 0 ${W} ${H}" class="ft-chart">
      <line x1="${PAD}" y1="${H-PAD}" x2="${W-PAD}" y2="${H-PAD}" class="ft-axis"/>
      <line x1="${PAD}" y1="${PAD}" x2="${PAD}" y2="${H-PAD}" class="ft-axis"/>
      ${yTicks.map(v=>`<text x="${PAD-8}" y="${py(v)+4}" class="ft-tick" text-anchor="end">${v}</text>`).join('')}
      <polyline points="${pts}" class="ft-line"/>
      ${h.map(p=>`<circle cx="${px(p.ts).toFixed(1)}" cy="${py(p.population||0).toFixed(1)}" r="3" class="ft-dot">
        <title>${new Date(p.ts*1000).toLocaleString()}. Pop ${p.population}</title></circle>`).join('')}
    </svg>`;
}

/* ---------- squads / jobs / rooms / nobles / justice / trade ----------
   All six are the same shape. An array of flat records, filterable and
   sortable by clicking a header, so one generic table covers all of
   them instead of six near-identical copies. */
function tableState(key, defaultSort){
  if(!S.tables[key]) S.tables[key] = {filter:'', sortCol:defaultSort, sortDir:1};
  return S.tables[key];
}
function setGenericFilter(key,v,caret){ tableState(key).filter=v; renderKeepFilterFocus(key, caret); }
function sortGeneric(key,col){
  const st=tableState(key);
  if(st.sortCol===col) st.sortDir*=-1; else { st.sortCol=col; st.sortDir=1; }
  render();
}
function genericTable(key, dataKey, columns, filterFields, emptyMsg, filterPlaceholder){
  const all=(S.current && S.current[dataKey]) || [];
  if(!all.length) return `<div class="empty">${emptyMsg}</div>`;
  const st=tableState(key, columns[0].key);
  const f=st.filter.toLowerCase();
  const rows = !f ? all.slice() : all.filter(row=>filterFields.some(fld=>String(row[fld]||'').toLowerCase().includes(f)));
  rows.sort((a,b)=>{
    let av=a[st.sortCol], bv=b[st.sortCol];
    if(typeof av==='string' || typeof bv==='string'){ av=String(av||'').toLowerCase(); bv=String(bv||'').toLowerCase(); }
    else { av=av||0; bv=bv||0; }
    if(av<bv) return -1*st.sortDir; if(av>bv) return 1*st.sortDir; return 0;
  });
  const arrow=c=> st.sortCol===c ? (st.sortDir>0?' \u25B2':' \u25BC') : '';
  return `<div class="ft-toolbar">
      <input class="ft-filter" data-filter="${key}" placeholder="${esc(filterPlaceholder)}" value="${esc(st.filter)}"
        oninput="Fortress.setGenericFilter('${key}',this.value,this.selectionStart)">
      <span class="hint">${rows.length} of ${all.length}</span>
    </div>
    <div class="ft-tablewrap"><table class="ft-table">
      <thead><tr>${columns.map(c=>`<th onclick="Fortress.sortGeneric('${key}','${c.key}')">${esc(c.label)}${arrow(c.key)}</th>`).join('')}</tr></thead>
      <tbody>${rows.map(row=>`<tr>${columns.map(c=>
        `<td${c.name?' class="ft-name"':''}>${c.render ? c.render(row) : esc(row[c.key]!=null?row[c.key]:'')}</td>`
      ).join('')}</tr>`).join('')}</tbody>
    </table></div>`;
}
function squadsTable(){
  return genericTable('squads','squads',
    [{key:'name',label:'Squad',name:true},
     {key:'members',label:'Members',render:s=>(s.members||[]).map(esc).join(', ')||'<span class="hint">None</span>'}],
    ['name'], 'No squads on record.', 'Filter squads…');
}
function jobsTable(){
  return genericTable('jobs','jobs',
    [{key:'name',label:'Job'},
     {key:'worker',label:'Worker',render:j=>j.worker?esc(j.worker):'<span class="hint">Unassigned</span>'}],
    ['name','worker'], 'No active jobs.', 'Filter jobs…');
}
function roomsTable(){
  return genericTable('rooms','rooms',
    [{key:'name',label:'Room',name:true}, {key:'owner',label:'Owner'}],
    ['name','owner'], 'No assigned rooms on record.', 'Filter rooms…');
}
function noblesTable(){
  return genericTable('nobles','nobles',
    [{key:'position',label:'Position',name:true}, {key:'name',label:'Held by'}],
    ['position','name'], 'No noble or administrative positions filled.', 'Filter positions…');
}
function justiceTable(){
  return genericTable('justice','justice',
    [{key:'type',label:'Crime'},
     {key:'culprit',label:'Culprit',render:j=>j.culprit?esc(j.culprit):'<span class="hint">Unknown</span>'},
     {key:'year',label:'Year'}],
    ['type','culprit'], 'No crimes on record.', 'Filter justice…');
}
function tradeTable(){
  return genericTable('trade','trade',
    [{key:'entity',label:'Traders',name:true}, {key:'trade_state',label:'Status'}, {key:'time_remaining',label:'Time remaining'}],
    ['entity','trade_state'], 'No caravans currently at the fortress.', 'Filter trade…');
}

/* ---------- settings panel ---------- */
function settingsPanel(){
  return `<div class="as-col" style="max-width:640px">
    <h3>DFHack setup</h3>
    <div class="hint" style="margin-bottom:10px">One-time setup: point this at the folder that directly
      contains <code>dfhack-run.exe</code>. On a normal Steam install that's DFHack's <code>hack</code>
      subfolder, not the DFHack folder itself. Then install the export script. After that, just hit
      Refresh on a fortress while DF + DFHack are running.</div>
    <label class="as-lab" for="dfhackDir">Folder containing dfhack-run.exe</label>
    <input id="dfhackDir" value="${esc(S.settings.dfhack_dir||'')}" placeholder="C:\\Program Files (x86)\\Steam\\steamapps\\common\\DFHack\\hack">
    <div class="wrow" style="margin-top:10px">
      <button class="btn" onclick="Fortress.saveSettings()">Save</button>
      <button class="btn primary" onclick="Fortress.installScript()">Install / update script</button>
    </div>
    ${S.current && S.current._warnings && S.current._warnings.length ? `
    <h3 style="margin-top:22px">Last refresh: skipped fields</h3>
    <div class="hint">These fields could not be read this time, usually a version or
      structure mismatch. Everything else in the snapshot is still good.</div>
    <div class="ft-warnlist">${S.current._warnings.map(w=>`<div>${esc(w)}</div>`).join('')}</div>` : ''}
  </div>`;
}

/* ---------- shell ---------- */
const TABS=[
  ['roster','Roster'], ['stocks','Stocks'], ['history','History'],
  ['squads','Squads'], ['jobs','Jobs'], ['rooms','Rooms'], ['nobles','Nobles'],
  ['justice','Justice'], ['trade','Trade'], ['settings','Settings'],
];

/* Every filter box calls render() on each keystroke, since the whole tab is
   one innerHTML swap. That destroys and recreates the <input> itself, so
   the browser drops focus and the caret after each character. This
   re-renders, then restores focus and caret position on the filter input
   matching the given data-filter value. */
function renderKeepFilterFocus(filterKey, caret){
  render();
  const el=document.querySelector(`input.ft-filter[data-filter="${filterKey}"]`);
  if(el){ el.focus(); try{ el.setSelectionRange(caret,caret); }catch(e){} }
}
function render(){
  const el=$('#view'); if(!el) return;
  const slot=S.slots.find(s=>s.id===S.slotId);

  const slotPicker = `<select onchange="Fortress.selectSlot(this.value)">
      ${S.slots.length ? S.slots.map(s=>`<option value="${s.id}"${s.id===S.slotId?' selected':''}>${esc(s.name)}</option>`).join('')
        : '<option>No fortresses yet</option>'}
    </select>
    <button class="btn" onclick="Fortress.newSlot()">New</button>
    ${S.slotId?'<button class="btn" onclick="Fortress.deleteSlot()">Delete</button>':''}`;

  let body;
  if(S.tab==='settings'){
    // Settings has to be reachable no matter what state the rest of the
    // page is in. It's how you'd fix a broken slot/refresh in the first
    // place.
    body = settingsPanel();
  } else if(!S.slotId){
    body = `<div class="empty">Create a fortress slot to get started. One per save you want to track.</div>`;
  } else if(S.err){
    body = `<div class="empty">Failed to get Data
      ${S.errDetail?`<pre class="ft-errdetail">${esc(S.errDetail)}</pre>`:''}
    </div>`;
  } else if(!S.current){
    body = `<div class="empty">No data yet for "${esc(slot?slot.name:'')}". Hit Refresh while Dwarf Fortress and DFHack are running.</div>`;
  } else if(S.tab==='roster'){
    body = rosterTable();
  } else if(S.tab==='stocks'){
    body = stocksTable();
  } else if(S.tab==='history'){
    body = historyChart();
  } else if(S.tab==='squads'){
    body = squadsTable();
  } else if(S.tab==='jobs'){
    body = jobsTable();
  } else if(S.tab==='rooms'){
    body = roomsTable();
  } else if(S.tab==='nobles'){
    body = noblesTable();
  } else if(S.tab==='justice'){
    body = justiceTable();
  } else if(S.tab==='trade'){
    body = tradeTable();
  }

  el.innerHTML = `<div class="entity-page ft-page">
    <div class="entity-head">
      <div><div class="kind">Game Tools</div><h1>Fortress</h1></div>
      <div class="ft-head-actions">
        ${slotPicker}
        <button class="btn primary" onclick="Fortress.refresh()" ${S.loading?'disabled':''}>${S.loading?'Refreshing…':'Refresh'}</button>
      </div>
    </div>
    ${S.current && S.current.meta ? `<div class="hint" style="margin-bottom:14px">
      ${esc(S.current.meta.fortress_name||'')}, ${S.current.meta.cur_year!=null?('year '+S.current.meta.cur_year):''}
      &middot; Refreshed ${S.current.meta.exported_at?new Date(S.current.meta.exported_at).toLocaleString():''}
    </div>`:''}
    <div class="as-tabs">
      ${TABS.map(([id,label])=>`<button class="${S.tab===id?'on':''}" onclick="Fortress.setTab('${id}')">${label}</button>`).join('')}
    </div>
    ${body}
  </div>`;
}

window.Fortress = {
  mount, newSlot, selectSlot, deleteSlot, refresh,
  saveSettings, installScript, setTab,
  setRosterFilter, sortRoster, toggleExpand,
  setStocksFilter, sortStocks,
  setGenericFilter, sortGeneric,
};

})();
