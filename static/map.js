/* =========================================================================
   map.js  --  the DFCart map view, as a module inside DwarfWiki
   =========================================================================
   Formerly a standalone app with its own page, server and port. Folded in
   here so the map and the wiki are one program.

   Everything lives inside an IIFE because DFCart and DwarfWiki both defined
   globals named STATE, API, api, apiPost, el, esc and toast, as separate
   pages that was fine; in one page it would be a silent collision. Only the
   functions that inline onclick= handlers actually need are published, on
   window.MapView.

   Lifecycle: MapView.mount(world) wires up a map that the router has already
   injected into the page; MapView.unmount() drops listeners so navigating
   away doesn't leave them firing.
   ========================================================================= */
(function(){
'use strict';


const API="/api";
let STATE={world:null,worlds:[],meta:null,zoom:1,offsetX:0,offsetY:0,tool:'pan',
  territoryMode:'none',
  layers:{bleedMode:true,topographic:false,climate:false,drainage:false,simpleMap:false,
          markers:true,routes:true,campaigns:false,sites:true,capitalLabels:true,coastline:true,
          activity:false},
  legendOff:new Set(), legendAll:false, territory:null, capitals:null, sites:[], factions:[],
  campaigns:[], markers:[], routes:[], selectedCiv:null, selectedCampaign:null,
  routeFirstSite:null, distFirst:null, areaPoints:[], mapGrid:null};
// the 3D globe lives in a separate <script type="module"> block (Three.js
// ships ES-module-only builds now). Module scripts don't share scope with
// classic scripts, so hand these across explicitly rather than relying on
// bare identifiers leaking to window the way `var`/functions do.
window.MapState=STATE; window.MapAPI=API;   // the 3D globe module reads these

const $=s=>document.querySelector(s);
const esc=s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function api(path){const r=await fetch(API+path); if(!r.ok) throw new Error(await r.text()); return r.json();}
window.api=api;
window.apiPost=apiPost;   // the 3D globe module posts globe-layout edits through this
async function apiPost(path,body){const r=await fetch(API+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})}); return r.json();}
function el(h){const d=document.createElement('div');d.innerHTML=h.trim();return d.firstChild;}
function toast(msg){
  const t=el('<div style="position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#241f18;color:#f4efe4;padding:10px 18px;border-radius:20px;z-index:400;font-size:13px;box-shadow:0 4px 14px rgba(0,0,0,.3)">'+esc(msg)+'</div>');
  document.body.appendChild(t); setTimeout(()=>t.remove(),2600);
}
function closeModal(){ $('#mapModalBg').style.display='none'; }
/* Backdrop-click closes the modal.
   This USED to bind directly to #mapModalBg at load time, which worked when
   DFCart was its own page and that element existed from the start. Inside
   DwarfWiki the map markup is injected only when you navigate to the map, so
   at load time the element is null, and the resulting throw killed the whole
   module before window.MapView was ever assigned, silently disabling the map
   AND leaving the globe with no world data. Delegating from document binds
   once, safely, and keeps working every time the markup is rebuilt.
   (The id test also still said 'modalBg' here, from before the rename.) */
document.addEventListener('click', function(e){
  if(e.target && e.target.id==='mapModalBg') closeModal();
});

const SITE_COLORS={
  fortress:'#8a2e2e',fort:'#8a2e2e',castle:'#8a2e2e','dark fortress':'#3a1616',tower:'#3a1616',
  town:'#2e5a3a',hamlet:'#2e5a3a',hillocks:'#2e5a3a',camp:'#8a6a2a',
  monastery:'#5a3a7a',shrine:'#5a3a7a',tomb:'#5a3a7a',
  cave:'#4a453a','mountain halls':'#4a453a',labyrinth:'#4a453a',
  lair:'#8a3a3a','mysterious lair':'#8a3a3a','dark pits':'#2a2030','mysterious dungeon':'#2a2030',
  'forest retreat':'#3a5a2e','mysterious palace':'#7a5a2a',
};
function siteColor(t){ return SITE_COLORS[t]||'#5a5248'; }

/* ============================================================
   CARTOGRAPHY ICONS (Kenney, CC0)
   Hand-drawn parchment map symbols, one per DF site type. These
   replace the flat colored dots on the flat Map view. The whole
   point of a fantasy cartography tool is that a castle looks like
   a castle. Icons lazy-load and cache; until an icon is ready the
   old colored dot draws in its place, so nothing pops or blanks.
   ============================================================ */
const SITE_ICONS={
  fortress:'castle', fort:'castleWide', castle:'castleTall', 'dark fortress':'castle',
  tower:'tower', town:'houses', hamlet:'house', hillocks:'houseSmall', camp:'tent',
  monastery:'church', shrine:'church', tomb:'graveyard',
  cave:'rocksMountain', 'mountain halls':'mine', labyrinth:'gate',
  lair:'skull', 'mysterious lair':'skull', 'dark pits':'skull', 'mysterious dungeon':'runis',
  'forest retreat':'treePines', 'mysterious palace':'castleTall',
  vault:'well', 'mysterious palace ':'castleTall',
};
const _iconCache={};
function getSiteIcon(type){
  const name=SITE_ICONS[type];
  if(!name) return null;
  if(_iconCache[name]!==undefined) return _iconCache[name];   // null while loading, Image once ready
  _iconCache[name]=null;
  const img=new Image();
  img.onload=function(){ _iconCache[name]=img; if(typeof draw==='function') draw(); };
  img.onerror=function(){ _iconCache[name]=false; };           // false = don't retry, fall back to dot
  img.src='/icons/carto/'+name+'.png';
  return null;
}

/* boot() from standalone DFCart is replaced by mount() at the bottom of
   this file. DwarfWiki owns the page chrome and the world selector now. */

async function loadWorld(name){
  STATE.world=name;
  STATE.meta=await api('/w/'+name+'/meta');
  STATE.mapGrid=await api('/w/'+name+'/map_grid.json');
  STATE.mapImg=new Image(); STATE.mapImg.onload=()=>draw(); STATE.mapImg.src=API+'/w/'+name+'/map.png?'+Date.now();
  STATE.heightImg=new Image(); STATE.heightImg.onload=()=>draw(); STATE.heightImg.src=API+'/w/'+name+'/heightmap.png';
  STATE.climateImg=new Image(); STATE.climateImg.onload=()=>draw(); STATE.climateImg.src=API+'/w/'+name+'/overlay/climate.png';
  STATE.drainageImg=new Image(); STATE.drainageImg.onload=()=>draw(); STATE.drainageImg.src=API+'/w/'+name+'/overlay/drainage.png';
  STATE.detailedImg=new Image();
  STATE.detailedReady=false;
  toast('Rendering detailed terrain… (one-time per world, ~20-30s, then instant)');
  STATE.detailedImg.onload=()=>{ STATE.detailedReady=true; draw(); };
  STATE.detailedImg.src=API+'/w/'+name+'/detailed_map.png';
  _territoryDirty=true; _borderPathsDirty=true; _coastPaths=null;
  STATE.selectedCiv=null; STATE.selectedCampaign=null;
  await Promise.all([loadSites(), loadTerritory(), loadCapitals(), loadFactions(),
                     loadCampaigns(), loadMarkers(), loadRoutes(), loadActivityPoints(), loadTradeHubs()]);
  zoomReset();
  renderLegend(); renderFactionsPanel(); renderCampaignsPanel(); renderCommercePanel();
  draw();
}
async function loadSites(){ const d=await api('/w/'+STATE.world+'/sites'); STATE.sites=d.sites; }
async function loadTerritory(){
  const mode = STATE.territoryMode || 'political';
  if(mode==='none'){ STATE.ownerGrid=null; STATE.distGrid=null; STATE.territory=null; _territoryDirty=true; return; }
  let d;
  if(mode==='race'){
    d = await api('/w/'+STATE.world+'/race_layer'+(STATE.legendAll?'?all=1':''));
    const colorFor={}; d.legend.forEach(function(l){ colorFor[l.race]=l.color; });
    d.civs = Object.keys(d.race_by_civ).map(function(cid){
      const race=d.race_by_civ[cid];
      return {id:cid, name:race.charAt(0).toUpperCase()+race.slice(1), color:colorFor[race]||'#6a6154'};
    });
  }else if(mode==='religion'){
    d = await api('/w/'+STATE.world+'/territory?preset=religion');
  }else if(mode==='faction'){
    d = await api('/w/'+STATE.world+'/territory?preset=faction');
  }else{
    d = await api('/w/'+STATE.world+'/territory'+(STATE.legendAll?'?all=1':''));
  }
  STATE.territory=d;
  // meta carries the grid dimensions; if a territory fetch resolves before
  // it (or after navigating away) there is nothing to size against
  if(!STATE.meta) return;
  const W=STATE.meta.width,H=STATE.meta.height;
  const owner=new Int32Array(W*H);
  // Territory-centroid computation folds into this same pass rather than a
  // second full-grid loop: each RLE segment already knows its own x-range,
  // so its contribution to a centroid is one arithmetic-series sum, not a
  // per-pixel accumulation. This is also what gives every territory mode a
  // label anchor point, not just the ones with a matching capital (capitals
  // are tied to the default political civ set, so "Faction control" and
  // other presets had territory color but no label to go with it).
  const centroidSum={};
  for(let y=0;y<H;y++){
    let x=0;
    for(const seg of d.owner_rle[y]){
      const val=seg[0], cnt=seg[1];
      if(val>=0){
        const startX=x, endX=x+cnt-1;
        const c=centroidSum[val] || (centroidSum[val]=[0,0,0]);
        c[0]+=cnt*(startX+endX)/2; c[1]+=cnt*y; c[2]+=cnt;
      }
      for(let i=0;i<cnt;i++){ owner[y*W+x]=val; x++; }
    }
  }
  const centroids={};
  for(const k in centroidSum){
    const c=centroidSum[k];
    if(c[2]>0) centroids[k]={x:c[0]/c[2], y:c[1]/c[2]};
  }
  STATE.territoryCentroids=centroids;
  // Built once per territory load rather than doing civs.find(...) inside
  // drawCapitals' per-capital loop, which runs every animation frame
  // (the capital ring has a pulse animation) against a list that can run
  // into the hundreds for a legendary-length world.
  const civsById={};
  (d.civs||[]).forEach(function(c){ civsById[c.id]=c; });
  STATE.civsById=civsById;
  STATE.ownerGrid=owner; STATE.distGrid=d.dist; _territoryDirty=true;
}
async function loadCapitals(){ const d=await api('/w/'+STATE.world+'/capitals'+(STATE.legendAll?'?all=1':'')); STATE.capitals=d.capitals; }
async function loadFactions(){ const d=await api('/w/'+STATE.world+'/factions'); STATE.factions=d.factions; }
async function loadCampaigns(){ const d=await api('/w/'+STATE.world+'/campaigns'); STATE.campaigns=d.campaigns; }
async function loadMarkers(){ const d=await api('/w/'+STATE.world+'/markers'); STATE.markers=d.markers; }
async function loadRoutes(){ const d=await api('/w/'+STATE.world+'/routes'); STATE.routes=d.routes; }
async function loadActivityPoints(){ const d=await api('/w/'+STATE.world+'/activity_points'); STATE.activityPoints=d.points; }
async function loadTradeHubs(){ const d=await api('/w/'+STATE.world+'/trade_hubs'); STATE.tradeHubs=d.hubs; }

/* the layout editor lives inside the 3D globe view now. Opening it renders
   the grid, closing it re-stitches the globe so edits show up immediately */
function toggleLayoutPanel(){
  const p=$('#layoutPanel'), opening=!p.classList.contains('open');
  p.classList.toggle('open', opening);
  if(opening){ renderGlobe(); syncPlanetControls(); }
  else if(window.stitchGridToTexture) window.stitchGridToTexture();
}

/* World Stats. Placeholder for now, as asked. It does show the real
   headline counts already sitting in meta.json rather than being a bare
   "coming soon" wall, since that data costs nothing to display. */
function renderStatsPanel(){
  if(!$('#statsBody')) return;   // view torn down (navigated away mid-load)
  const m=STATE.meta||{}, c=m.counts||{};
  const cards=[
    ['Historical figures', c.figures], ['Sites', c.sites], ['Artifacts', c.artifacts],
    ['Civilizations & groups', c.entities], ['Recorded events', c.events],
    ['Written works', c.written], ['Regions', c.regions], ['Creature types', c.bestiary],
  ].filter(function(x){ return x[1]!=null; });
  let html='<div class="stat-cards">'+cards.map(function(x){
    return '<div class="stat-card"><div class="sc-n">'+Number(x[1]).toLocaleString()+'</div><div class="sc-l">'+esc(x[0])+'</div></div>';
  }).join('')+'</div>';
  html+='<div class="stats-soon"><h3>More coming soon</h3>'+
    '<p class="hint">Population over time, war and battle timelines, race distribution charts, '+
    'site-type breakdowns, and trade-network analysis.</p></div>';
  $('#statsBody').innerHTML=html;
}

/* ---- planet size controls ---------------------------------------------
   The slider changes how large every region reads on the globe. Readouts are
   in real units derived from the same 1873m-per-tile figure the scaling uses,
   so "a Large region spans 45 degrees / takes 8 to circle the world" is a real
   statement about your planet, not a made-up number. ---- */
function syncPlanetControls(){
  const g=window.MapState.globe||{};
  const sl=document.getElementById('planetSlider'); if(!sl) return;
  const r=Math.round(window.planetRadiusKm());
  if(Number(sl.value)!==r) sl.value=Math.max(sl.min,Math.min(sl.max,r));
  renderPlanetReadout(r);
}
function renderPlanetReadout(r){
  const el=document.getElementById('planetReadout'); if(!el) return;
  const circ=2*Math.PI*r;
  const largeKm=window.REFERENCE_TILES*window.METERS_PER_TILE/1000;
  const deg=largeKm/circ*360;
  const across=circ/largeKm;
  el.innerHTML='Radius <b>'+r.toLocaleString()+' km</b> · equator <b>'+Math.round(circ).toLocaleString()+' km</b><br>'+
    'A Large region (257 tiles, '+Math.round(largeKm)+' km) spans <b>'+deg.toFixed(1)+'°</b>. '+
    '<b>'+across.toFixed(1)+'</b> of them circle the world.';
}
let _planetStitchTimer=null;
function onPlanetSlider(v){
  const g=window.MapState.globe||{}; g.planet_radius_km=Number(v);
  window.MapState.globe=g;
  renderPlanetReadout(Number(v));
  clearTimeout(_planetStitchTimer);
  _planetStitchTimer=setTimeout(function(){ if(window.stitchGridToTexture) window.stitchGridToTexture(); },90);
}
async function commitPlanetSize(v){
  await apiPost('/globe',{action:'set_planet', planet_radius_km:Number(v)});
  if(window.stitchGridToTexture) window.stitchGridToTexture();
}
async function autoFitPlanet(){
  const g=window.MapState.globe||{};
  const r=Math.round(window.defaultPlanetRadiusKm(g));
  g.planet_radius_km=r; window.MapState.globe=g;
  syncPlanetControls();
  await apiPost('/globe',{action:'set_planet', planet_radius_km:r});
  if(window.stitchGridToTexture) window.stitchGridToTexture();
}

function resizeCanvas(){
  const wrap=$('#mapWrap'), cv=$('#mapCanvas');
  if(!wrap || !cv || !wrap.clientWidth || !wrap.clientHeight) return;
  cv.width=wrap.clientWidth; cv.height=wrap.clientHeight;
  draw();
}
function zoomBy(dir){ STATE.zoom=Math.max(0.5,Math.min(40,STATE.zoom*(dir>0?1.25:0.8))); draw(); }
function zoomReset(){
  if(!STATE.meta) return;
  const cv=$('#mapCanvas');
  STATE.zoom=Math.min(cv.width/STATE.meta.width, cv.height/STATE.meta.height)*0.94;
  STATE.offsetX=(cv.width-STATE.meta.width*STATE.zoom)/2;
  STATE.offsetY=(cv.height-STATE.meta.height*STATE.zoom)/2;
  draw();
}
function tileToScreen(x,y){ return [STATE.offsetX+x*STATE.zoom, STATE.offsetY+y*STATE.zoom]; }
function screenToTile(sx,sy){ return [(sx-STATE.offsetX)/STATE.zoom, (sy-STATE.offsetY)/STATE.zoom]; }

let _territoryCanvas=null, _territoryDirty=true;
function buildTerritoryLayer(){
  if(!STATE.ownerGrid || !STATE.meta) return null;
  const W=STATE.meta.width,H=STATE.meta.height;
  const oc=document.createElement('canvas'); oc.width=W; oc.height=H;
  const octx=oc.getContext('2d');
  const img=octx.createImageData(W,H);
  const maxInfl=STATE.territory.max_influence||42;
  const civColor={};
  STATE.territory.civs.forEach(c=>{
    civColor[c.id]=[parseInt(c.color.slice(1,3),16),parseInt(c.color.slice(3,5),16),parseInt(c.color.slice(5,7),16)];
  });
  const owner=STATE.ownerGrid, dist=STATE.distGrid;
  // visCid tracks which realm is ACTUALLY PAINTED at each tile (-1 = nothing
  // visible here). The border pass below traces this rather than the raw
  // owner grid. In hard-border mode the fill stops well short of the true
  // owner boundary, and outlining the owner grid drew lines floating out in
  // open space away from the color they were supposed to be wrapping.
  const visCid=new Int32Array(W*H).fill(-1);
  for(let y=0;y<H;y++){
    for(let x=0;x<W;x++){
      const idx=y*W+x, cid=owner[idx];
      if(cid===-1) continue;
      const rgb=civColor[cid]; if(!rgb) continue;
      const d=dist[y][x];
      // Base opacity raised ~20% from its original values (175/200) so a
      // selected map mode reads clearly at a glance; turning the mode off
      // entirely is how you see the plain tiles underneath now, rather than
      // leaning on a faint wash that tried to do both at once.
      let alpha = STATE.layers.bleedMode
        ? Math.max(0,1-(d/maxInfl))*210
        : (d<=maxInfl*0.55 ? 240 : 0);
      if(alpha<=0) continue;
      visCid[idx]=cid;
      if(STATE.selectedCiv && cid!=STATE.selectedCiv) alpha*=0.18;
      const p=idx*4;
      img.data[p]=rgb[0]; img.data[p+1]=rgb[1]; img.data[p+2]=rgb[2]; img.data[p+3]=alpha;
    }
  }
  // NOTE: the border is NOT drawn into this raster any more. It used to be a
  // 1-tile-thick pass here, which meant the outline was baked at tile
  // resolution and got blockier the further you zoomed in. Borders are now
  // traced as real vector paths (see buildBorderPaths / drawVectorBorders)
  // and stroked in screen space, so they stay smooth at any zoom.
  octx.putImageData(img,0,0);
  _borderPathsDirty=true;
  return oc;
}

let _capAnimRunning=false;
function draw(){
  // the canvas is gone entirely once you navigate off the map route; an
  // in-flight world load can still land here afterwards
  const cv=$('#mapCanvas'); if(!cv || !cv.width) return;
  const ctx=cv.getContext('2d');
  ctx.imageSmoothingEnabled=false;
  ctx.fillStyle='#12213a'; ctx.fillRect(0,0,cv.width,cv.height);
  if(!STATE.meta) return;
  const W=STATE.meta.width,H=STATE.meta.height;
  const sxy=tileToScreen(0,0), sx=sxy[0], sy=sxy[1];
  const dw=W*STATE.zoom, dh=H*STATE.zoom;

  const baseImg = STATE.layers.topographic ? STATE.heightImg
    : STATE.layers.simpleMap ? STATE.mapImg
    : (STATE.detailedReady ? STATE.detailedImg : STATE.mapImg);
  if(baseImg && baseImg.complete && baseImg.naturalWidth) ctx.drawImage(baseImg, sx, sy, dw, dh);
  // (the animated water shimmer that used to draw here has been removed.
  //  The flat map is now a still map. Site coronas still glow.)

  // heatmap-style overlays use 'multiply' so real terrain detail still
  // shows through the color instead of being washed out by flat alpha
  if(STATE.layers.climate && STATE.climateImg && STATE.climateImg.complete && STATE.climateImg.naturalWidth){
    ctx.globalCompositeOperation='multiply'; ctx.globalAlpha=0.82;
    ctx.drawImage(STATE.climateImg, sx, sy, dw, dh);
    ctx.globalAlpha=1; ctx.globalCompositeOperation='source-over';
  }
  if(STATE.layers.drainage && STATE.drainageImg && STATE.drainageImg.complete && STATE.drainageImg.naturalWidth){
    ctx.globalCompositeOperation='multiply'; ctx.globalAlpha=0.82;
    ctx.drawImage(STATE.drainageImg, sx, sy, dw, dh);
    ctx.globalAlpha=1; ctx.globalCompositeOperation='source-over';
  }
  drawCoastline(ctx);
  if(STATE.layers.activity) drawActivityHeatmap(ctx);

  if(STATE.territoryMode!=='none' && STATE.ownerGrid){
    if(_territoryDirty || !_territoryCanvas){ _territoryCanvas=buildTerritoryLayer(); _territoryDirty=false; }
    if(_territoryCanvas) ctx.drawImage(_territoryCanvas, sx, sy, dw, dh);
    drawVectorBorders(ctx);
  }

  if(STATE.layers.campaigns) drawCampaigns(ctx);
  if(STATE.layers.routes) drawRoutes(ctx);
  if(STATE.layers.sites) drawSites(ctx);
  if(STATE.layers.markers) drawCustomMarkers(ctx);
  drawCapitals(ctx);
  if(STATE.areaPoints.length) drawAreaInProgress(ctx);

  if(!_capAnimRunning){ _capAnimRunning=true; requestAnimationFrame(pulseLoop); }
}
function pulseLoop(){ _capAnimRunning=false; if(STATE.capitals && Object.keys(STATE.capitals).length) draw(); }
/* =========================================================================
   VECTOR BORDERS
   The territory FILL stays a raster (it carries the soft influence gradient,
   which is genuinely per-tile data). The OUTLINE is traced once into real
   curves and stroked in screen space, so zooming in shows a smoother line
   rather than bigger pixels.

   Cached per (world, mode, scope). Tracing 41 civs costs ~130ms, which is
   fine once but not every frame.
   ========================================================================= */
let _borderPaths=null, _borderPathsDirty=true, _borderPathsKey=null;

function buildBorderPaths(){
  if(!window.VectorBorders || !STATE.ownerGrid || !STATE.meta) return null;
  const W=STATE.meta.width, H=STATE.meta.height;
  const owner=STATE.ownerGrid, dist=STATE.distGrid;
  const maxInfl=(STATE.territory && STATE.territory.max_influence) || 42;

  // Reproduce exactly what buildTerritoryLayer() paints, so the outline
  // traces the shape you can actually see. In hard-border mode the fill
  // stops well short of the true ownership boundary, and tracing ownership
  // would float the line out in open space away from its colour.
  const visCid=new Int32Array(W*H).fill(-1);
  for(let y=0;y<H;y++){
    for(let x=0;x<W;x++){
      const idx=y*W+x, cid=owner[idx];
      if(cid===-1||cid==null) continue;
      const d=dist[y][x];
      const alpha = STATE.layers.bleedMode ? Math.max(0,1-(d/maxInfl))*175
                                           : (d<=maxInfl*0.55 ? 200 : 0);
      if(alpha>0) visCid[idx]=cid;
    }
  }
  const cellsByCiv={};
  for(let y=0;y<H;y++){
    for(let x=0;x<W;x++){
      const cid=visCid[y*W+x];
      if(cid===-1) continue;
      (cellsByCiv[cid]=cellsByCiv[cid]||[]).push([x,y]);
    }
  }
  const out=[];
  for(const cid in cellsByCiv){
    const cells=cellsByCiv[cid];
    if(cells.length<4) continue;
    const want=Number(cid);
    const inside=function(x,y){
      if(x<0||y<0||x>=W||y>=H) return false;
      return visCid[y*W+x]===want;
    };
    const loops=window.VectorBorders.smoothRegion(inside,W,H,cells,
      {iterations:3, minLoop:8, tol:0.28, eps:1.8});
    if(loops.length) out.push({cid:cid, loops:loops});
  }
  return out;
}

function drawVectorBorders(ctx){
  const key=[STATE.world,STATE.territoryMode,STATE.legendAll,STATE.layers.bleedMode].join('|');
  if(_borderPathsDirty || !_borderPaths || _borderPathsKey!==key){
    _borderPaths=buildBorderPaths();
    _borderPathsDirty=false; _borderPathsKey=key;
  }
  if(!_borderPaths) return;
  const z=STATE.zoom;
  ctx.save();
  ctx.lineJoin='round'; ctx.lineCap='round';
  for(const grp of _borderPaths){
    const dimmed = STATE.selectedCiv && grp.cid!=STATE.selectedCiv;
    ctx.globalAlpha = dimmed ? 0.22 : 0.95;
    // hairline at low zoom, a real drawn line when zoomed in, but never so
    // thick it swallows small territories
    ctx.lineWidth = Math.max(0.8, Math.min(2.6, z*0.16));
    ctx.strokeStyle = '#191410';
    for(const loop of grp.loops){
      ctx.beginPath();
      for(let i=0;i<loop.length;i++){
        const p=tileToScreen(loop[i][0],loop[i][1]);
        if(i===0) ctx.moveTo(p[0],p[1]); else ctx.lineTo(p[0],p[1]);
      }
      ctx.closePath();
      ctx.stroke();
    }
  }
  ctx.restore();
}

/* =========================================================================
   VECTOR COASTLINE
   Same tracing as the borders, run on the land/water mask from the real
   terrain grid. Drawn with a classic cartographic treatment: a soft pale
   halo just outside the land, then the coast stroke itself. That halo is
   what makes hand-drawn maps read as "sea meets shore" rather than "two
   colours meet"; it costs one extra stroke pass.
   ========================================================================= */
let _coastPaths=null, _coastKey=null;

function buildCoastPaths(){
  if(!window.VectorBorders || !STATE.mapGrid) return null;
  const g=STATE.mapGrid, W=g.width, H=g.height, types=g.types;
  const waterIdx={};
  types.forEach(function(t,i){ if(t==='Ocean'||t==='Lake') waterIdx[i]=1; });
  const land=new Uint8Array(W*H);
  const cells=[];
  for(let y=0;y<H;y++){
    for(let x=0;x<W;x++){
      const v=g.grid[y][x];
      if(v>=0 && !waterIdx[v]){ land[y*W+x]=1; cells.push([x,y]); }
    }
  }
  if(!cells.length) return null;
  const inside=function(x,y){
    if(x<0||y<0||x>=W||y>=H) return false;
    return land[y*W+x]===1;
  };
  // minLoop is 4 here, not 8 as for territory: a 4-point loop is a real
  // one-tile island, which is genuine terrain worth drawing, whereas a
  // 1-tile speck of "territory" is just noise in the influence falloff.
  return window.VectorBorders.smoothRegion(inside,W,H,cells,
    {iterations:3, minLoop:4, tol:0.34, eps:1.8});
}

function drawCoastline(ctx){
  if(!STATE.layers.coastline) return;
  if(!_coastPaths || _coastKey!==STATE.world){
    _coastPaths=buildCoastPaths(); _coastKey=STATE.world;
  }
  if(!_coastPaths) return;
  const z=STATE.zoom;
  ctx.save();
  ctx.lineJoin='round'; ctx.lineCap='round';
  const trace=function(){
    for(const loop of _coastPaths){
      ctx.beginPath();
      for(let i=0;i<loop.length;i++){
        const p=tileToScreen(loop[i][0],loop[i][1]);
        if(i===0) ctx.moveTo(p[0],p[1]); else ctx.lineTo(p[0],p[1]);
      }
      ctx.closePath();
      ctx.stroke();
    }
  };
  // pale halo first, then the darker coast on top of it
  ctx.globalAlpha=0.5;
  ctx.lineWidth=Math.max(2.5, Math.min(11, z*0.75));
  ctx.strokeStyle='#f2e9cf';
  trace();
  ctx.globalAlpha=0.9;
  ctx.lineWidth=Math.max(0.7, Math.min(2.2, z*0.13));
  ctx.strokeStyle='#2c3f52';
  trace();
  ctx.restore();
}

function invalidateTerritory(){ _territoryDirty=true; _borderPathsDirty=true; draw(); }

function drawActivityHeatmap(ctx){
  if(!STATE.activityPoints || !STATE.activityPoints.length) return;
  ctx.save();
  ctx.globalCompositeOperation='lighter';   // overlapping hot spots genuinely brighten, like a real heatmap
  const maxW=Math.max.apply(null, STATE.activityPoints.map(function(p){return p.weight;}));
  for(const p of STATE.activityPoints){
    const pos=tileToScreen(p.x+0.5,p.y+0.5), x=pos[0], y=pos[1];
    if(x<-60||y<-60||x>ctx.canvas.width+60||y>ctx.canvas.height+60) continue;
    const strength=Math.min(1,p.weight/Math.max(maxW*0.4,1));
    const r=(10+strength*24)*Math.min(1.4,Math.max(0.6,STATE.zoom/3));
    const grad=ctx.createRadialGradient(x,y,0,x,y,r);
    grad.addColorStop(0,'rgba(255,120,40,'+(0.35*strength)+')');
    grad.addColorStop(1,'rgba(255,120,40,0)');
    ctx.fillStyle=grad; ctx.beginPath(); ctx.arc(x,y,r,0,7); ctx.fill();
  }
  ctx.restore();
}
function drawSites(ctx){
  const off=STATE.legendOff;
  // icons scale with zoom but stay within a sane pixel range so they neither
  // vanish when zoomed out nor swallow the map when zoomed in
  const iconOn = STATE.zoom >= 2.2;   // below this, dots read better than tiny icons
  for(const s of STATE.sites){
    if(off.has(s.type)) continue;
    const p=tileToScreen(s.x+0.5,s.y+0.5), x=p[0], y=p[1];
    if(x<-20||y<-20||x>ctx.canvas.width+20||y>ctx.canvas.height+20) continue;
    const icon = iconOn ? getSiteIcon(s.type) : null;
    if(icon){
      // more historically-active sites draw a touch larger
      const sz=Math.max(14, Math.min(30, 16+s.events/60)) * Math.min(1.6, Math.max(0.85, STATE.zoom/6));
      ctx.save();
      ctx.shadowColor='rgba(0,0,0,.55)'; ctx.shadowBlur=3; ctx.shadowOffsetY=1;
      ctx.drawImage(icon, x-sz/2, y-sz*0.8, sz, sz);   // anchor near the base of the symbol
      ctx.restore();
    }else{
      const r=Math.max(1.6, Math.min(5, 2+s.events/80));
      ctx.beginPath(); ctx.arc(x,y,r,0,7);
      ctx.fillStyle=siteColor(s.type); ctx.fill();
      ctx.lineWidth=1; ctx.strokeStyle='rgba(255,255,255,.7)'; ctx.stroke();
    }
  }
}
function drawCrownIcon(ctx,x,y,scale){
  ctx.save();
  ctx.translate(x,y); ctx.scale(scale,scale);
  // dark outline pass first (drawn slightly larger via stroke width) for
  // contrast against both bright desert and dark forest biomes
  ctx.beginPath();
  ctx.moveTo(-7,4); ctx.lineTo(-7,-1); ctx.lineTo(-4,2); ctx.lineTo(-2,-4);
  ctx.lineTo(0,1); ctx.lineTo(2,-4); ctx.lineTo(4,2); ctx.lineTo(7,-1);
  ctx.lineTo(7,4); ctx.closePath();
  ctx.lineWidth=2.6; ctx.strokeStyle='#2a1a08'; ctx.lineJoin='round'; ctx.stroke();
  ctx.fillStyle='#ffd35c'; ctx.fill();
  ctx.lineWidth=1; ctx.strokeStyle='#8a5a10'; ctx.stroke();
  // small jewels at the peaks
  ctx.fillStyle='#a23b3b';
  [[-4,-1.5],[0,-1.5],[4,-1.5]].forEach(function(p){ ctx.beginPath(); ctx.arc(p[0],p[1],0.9,0,7); ctx.fill(); });
  ctx.restore();
}
function drawCapitals(ctx){
  const labeled={};   // owner ids already labeled via their capital marker
  if(STATE.capitals){
    const pulse=(Date.now()%1800)/1800;   // 0->1 ring expansion cycle, performance-friendly (no gradient rebuild)
    for(const cid in STATE.capitals){
      const c=STATE.capitals[cid];
      if(c.x==null) continue;
      const p=tileToScreen(c.x+0.5,c.y+0.5), x=p[0], y=p[1];
      if(x<-30||y<-30||x>ctx.canvas.width+30||y>ctx.canvas.height+30) continue;
      // expanding, fading ring (cheap: one stroked circle, not a gradient fill)
      ctx.beginPath(); ctx.arc(x,y,9+pulse*11,0,7);
      ctx.lineWidth=1.6; ctx.strokeStyle='rgba(255,211,92,'+(0.55*(1-pulse))+')'; ctx.stroke();
      drawCrownIcon(ctx,x,y,1.15);
      if(STATE.layers.capitalLabels!==false){
        const civ=STATE.civsById && STATE.civsById[cid];
        if(civ){
          drawTerritoryLabel(ctx,civ.name,x,y+18);
          labeled[cid]=true;
        }
      }
    }
  }
  // Any territory without a capital marker (smaller factions/guilds, or a
  // preset like "Faction control" whose entities aren't the same ones
  // capitals are tracked for) still gets a label, anchored to its
  // territory's own centroid instead of a capital site.
  if(STATE.layers.capitalLabels!==false && STATE.territory && STATE.territoryCentroids){
    (STATE.territory.civs||[]).forEach(function(civ){
      if(labeled[civ.id]) return;
      const cen=STATE.territoryCentroids[civ.id];
      if(!cen) return;
      const p=tileToScreen(cen.x,cen.y), x=p[0], y=p[1];
      if(x<-30||y<-30||x>ctx.canvas.width+30||y>ctx.canvas.height+30) return;
      drawTerritoryLabel(ctx,civ.name,x,y);
    });
  }
}
function drawTerritoryLabel(ctx,name,x,y){
  ctx.font='bold 11px var(--sans),sans-serif';
  ctx.textAlign='center';
  ctx.lineWidth=3; ctx.strokeStyle='rgba(20,15,5,.85)'; ctx.strokeText(name,x,y);
  ctx.fillStyle='#fff4d8'; ctx.fillText(name,x,y);
}
function drawCustomMarkers(ctx){
  for(const m of STATE.markers){
    const p=tileToScreen(m.x+0.5,m.y+0.5), x=p[0], y=p[1];
    ctx.beginPath(); ctx.arc(x,y,5,0,7);
    ctx.fillStyle=m.color; ctx.fill();
    ctx.lineWidth=1.3; ctx.strokeStyle='#fff'; ctx.stroke();
  }
}
function drawRoutes(ctx){
  ctx.save(); ctx.setLineDash([5,4]); ctx.lineWidth=1.6; ctx.strokeStyle='#8a6a2a';
  for(const r of STATE.routes){
    const s1=STATE.sites.find(s=>s.id===r.from_site), s2=STATE.sites.find(s=>s.id===r.to_site);
    if(!s1||!s2) continue;
    const p1=tileToScreen(s1.x+0.5,s1.y+0.5), p2=tileToScreen(s2.x+0.5,s2.y+0.5);
    ctx.beginPath(); ctx.moveTo(p1[0],p1[1]); ctx.lineTo(p2[0],p2[1]); ctx.stroke();
  }
  ctx.restore();
}
function drawCampaigns(ctx){
  ctx.save(); ctx.setLineDash([3,3]); ctx.lineWidth=1.4; ctx.strokeStyle='rgba(150,20,20,.75)';
  for(const c of STATE.campaigns){
    if(STATE.selectedCampaign===null || c.id!==STATE.selectedCampaign) continue;
    for(let i=0;i<c.path.length-1;i++){
      const p1=tileToScreen(c.path[i].x+0.5,c.path[i].y+0.5);
      const p2=tileToScreen(c.path[i+1].x+0.5,c.path[i+1].y+0.5);
      ctx.beginPath(); ctx.moveTo(p1[0],p1[1]); ctx.lineTo(p2[0],p2[1]); ctx.stroke();
    }
    for(const pt of c.path){
      const p=tileToScreen(pt.x+0.5,pt.y+0.5);
      ctx.beginPath(); ctx.arc(p[0],p[1],3,0,7); ctx.fillStyle='#a01414'; ctx.fill();
    }
  }
  ctx.restore();
}
function drawAreaInProgress(ctx){
  ctx.save(); ctx.strokeStyle='#2e5a8a'; ctx.fillStyle='rgba(46,90,138,.18)'; ctx.lineWidth=2;
  ctx.beginPath();
  STATE.areaPoints.forEach((pt,i)=>{ const p=tileToScreen(pt.x,pt.y); if(i===0) ctx.moveTo(p[0],p[1]); else ctx.lineTo(p[0],p[1]); });
  if(STATE.areaPoints.length>2) ctx.closePath();
  ctx.fill(); ctx.stroke();
  for(const pt of STATE.areaPoints){
    const p=tileToScreen(pt.x,pt.y);
    ctx.beginPath(); ctx.arc(p[0],p[1],3.5,0,7); ctx.fillStyle='#2e5a8a'; ctx.fill();
  }
  ctx.restore();
}

function wireMapInteraction(){
  const wrap=$('#mapWrap'), cv=$('#mapCanvas');
  let dragging=false, lastX=0, lastY=0, moved=false;
  cv.addEventListener('mousedown',e=>{ dragging=true; moved=false; lastX=e.clientX; lastY=e.clientY; wrap.classList.add('panning'); });
  window.addEventListener('mousemove',e=>{
    if(dragging){
      const dx=e.clientX-lastX, dy=e.clientY-lastY;
      if(Math.abs(dx)>2||Math.abs(dy)>2) moved=true;
      STATE.offsetX+=dx; STATE.offsetY+=dy; lastX=e.clientX; lastY=e.clientY;
      draw();
    }
    handleHover(e);
  });
  window.addEventListener('mouseup',e=>{
    if(dragging && !moved) handleClick(e);
    dragging=false; wrap.classList.remove('panning');
  });
  cv.addEventListener('wheel',e=>{
    e.preventDefault();
    const rect=cv.getBoundingClientRect(), mx=e.clientX-rect.left, my=e.clientY-rect.top;
    const t=screenToTile(mx,my);
    STATE.zoom=Math.max(0.5,Math.min(40,STATE.zoom*(e.deltaY<0?1.12:0.89)));
    const ns=tileToScreen(t[0],t[1]);
    STATE.offsetX+=mx-ns[0]; STATE.offsetY+=my-ns[1];
    draw();
  },{passive:false});
}
function setTool(t){
  STATE.tool=t; STATE.routeFirstSite=null; STATE.distFirst=null; STATE.areaPoints=[];
  document.querySelectorAll('.tbtn').forEach(b=>b.classList.remove('active'));
  $('#tool-'+t).classList.add('active');
  const mb=$('#measureBox');
  if(t==='distance'){ mb.style.display='block'; mb.textContent='Click a start point, then an end point.'; }
  else if(t==='area'){ mb.style.display='block'; mb.textContent='Click 3+ points, then click the first point again to close.'; }
  else mb.style.display='none';
  draw();
}
function nearestSite(tx,ty,maxDist){
  let best=null,bd=maxDist;
  for(const s of STATE.sites){ const d=Math.hypot(s.x-tx,s.y-ty); if(d<bd){bd=d;best=s;} }
  return best;
}
function handleClick(e){
  const rect=$('#mapCanvas').getBoundingClientRect();
  const t=screenToTile(e.clientX-rect.left, e.clientY-rect.top), tx=t[0], ty=t[1];
  if(STATE.tool==='pan'){ const s=nearestSite(tx,ty,8/STATE.zoom); if(s) openSitePopup(s); return; }
  if(STATE.tool==='distance'){
    if(!STATE.distFirst){ STATE.distFirst={x:tx,y:ty}; $('#measureBox').textContent='Now click the end point...'; }
    else{ measureDistance(STATE.distFirst,{x:tx,y:ty}); STATE.distFirst=null; }
    return;
  }
  if(STATE.tool==='area'){
    if(STATE.areaPoints.length>=3){
      const first=STATE.areaPoints[0];
      if(Math.hypot(first.x-tx,first.y-ty) < 4/STATE.zoom){ measureArea(STATE.areaPoints); STATE.areaPoints=[]; draw(); return; }
    }
    STATE.areaPoints.push({x:tx,y:ty}); draw();
    return;
  }
  if(STATE.tool==='marker'){ openMarkerModal(Math.round(tx),Math.round(ty)); return; }
  if(STATE.tool==='route'){
    const s=nearestSite(tx,ty,5);
    if(!s){ toast('Click closer to a site'); return; }
    if(!STATE.routeFirstSite){
      STATE.routeFirstSite=s; $('#measureBox').style.display='block';
      $('#measureBox').textContent='From '+s.name+' -> click destination site';
    }else{
      addRoute(STATE.routeFirstSite, s);
      STATE.routeFirstSite=null; $('#measureBox').style.display='none';
    }
  }
}
function handleHover(e){
  const rect=$('#mapCanvas').getBoundingClientRect();
  const mx=e.clientX-rect.left, my=e.clientY-rect.top;
  const t=screenToTile(mx,my), tx=t[0], ty=t[1];
  const tip=$('#hoverTip');
  if(!STATE.meta || tx<0||ty<0||tx>=STATE.meta.width||ty>=STATE.meta.height){ tip.style.display='none'; return; }
  const s=nearestSite(tx,ty,3);
  let text;
  if(s) text=s.name+' - '+s.type;
  else text=biomeAt(Math.floor(tx),Math.floor(ty));
  if(!text){ tip.style.display='none'; return; }
  tip.textContent=text; tip.style.display='block';
  tip.style.left=(e.clientX+14)+'px'; tip.style.top=(e.clientY+10)+'px';
}
function biomeAt(x,y){
  const g=STATE.mapGrid; if(!g) return null;
  if(x<0||y<0||x>=g.width||y>=g.height) return null;
  const idx=g.grid[y][x];
  return idx>=0 ? g.types[idx] : null;
}

async function measureDistance(p1,p2){
  const d=await api('/measure/distance?x1='+p1.x+'&y1='+p1.y+'&x2='+p2.x+'&y2='+p2.y);
  $('#measureBox').innerHTML='<b>'+d.miles.toLocaleString()+' miles</b> <span class="hint">('+d.tiles+' tiles x '+d.miles_per_tile+' mi/tile)</span>';
}
async function measureArea(points){
  const d=await apiPost('/measure/area',{points:points});
  $('#measureBox').innerHTML='<b>'+d.sq_miles.toLocaleString()+' sq mi</b><br><span class="hint">roughly the size of '+esc(d.reference)+'</span>';
  $('#measureBox').style.display='block';
}

function switchTab(name){
  document.querySelectorAll('.sb-tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===name));
  ['layers','legend','factions','campaigns','commerce'].forEach(n=>{
    $('#sb'+n[0].toUpperCase()+n.slice(1)).style.display = n===name?'block':'none';
  });
}
const TERRITORY_MODE_LABELS={none:'Off',political:'Political (folklands)',race:'Race density',religion:'Religion',faction:'Faction control'};
function renderLayersPanel(){
  if(!$('#sbLayers')) return;   // view torn down (navigated away mid-load)
  const tmOpts=Object.keys(TERRITORY_MODE_LABELS).map(function(k){
    return '<option value="'+k+'"'+(STATE.territoryMode===k?' selected':'')+'>'+TERRITORY_MODE_LABELS[k]+'</option>';
  }).join('');
  $('#sbLayers').innerHTML=
    '<h3>Map Mode</h3>'+
    '<div class="field"><select id="ly-territorymode" onchange="MapView.setTerritoryMode(this.value)" style="width:100%">'+tmOpts+'</select></div>'+
    '<div class="field" id="ly-bleedwrap" style="display:'+(STATE.territoryMode==='none'?'none':'block')+'">'+
      '<select id="ly-bleedmode" onchange="MapView.setBleedMode(this.value)" style="width:100%">'+
      '<option value="bleed">Boundary Bleed (fading influence)</option>'+
      '<option value="hard">Political Lines (hard borders)</option></select></div>'+
    '<div class="layer-row"><input type="checkbox" id="ly-all-territory" onchange="MapView.toggleTerritoryScope(this.checked)"> Include minor governments</div>'+
    '<h3 style="margin-top:16px">Overlays</h3>'+
    layerRow('coastline','Coastline (smooth vector)',false,true)+
    layerRow('simpleMap','Simple map (flat colors, faster)',false)+
    layerRow('topographic','Topographic (elevation)',false)+
    layerRow('climate','Climate heatmap','fake')+
    layerRow('drainage','Drainage','fake')+
    layerRow('activity','Activity heatmap (event density)','fake-lite')+
    '<h3 style="margin-top:16px">Markers</h3>'+
    layerRow('sites','Site markers',false,true)+
    layerRow('capitalLabels','Capital name labels',false,true)+
    layerRow('routes','Trade routes','edit',true)+
    layerRow('markers','Custom markers',false,true)+'';
  updateActiveLayersHud();
}
function layerRow(key,label,badge,checked){
  const isOn = STATE.layers[key]!==false && (checked || STATE.layers[key]===true);
  const badgeHtml = '';
  return '<div class="layer-row'+(isOn?' active-layer':'')+'" id="row-'+key+'">'+
    '<input type="checkbox" id="ly-'+key+'" '+(isOn?'checked':'')+' onchange="MapView.toggleLayer(\''+key+'\',this.checked)"> '+esc(label)+badgeHtml+'</div>';
}
function toggleLayer(key,val){
  STATE.layers[key]=val;
  document.getElementById('row-'+key).classList.toggle('active-layer',val);
  draw(); updateActiveLayersHud();
}
function setTerritoryMode(mode){
  STATE.territoryMode=mode;
  $('#ly-bleedwrap').style.display = mode==='none' ? 'none':'block';
  loadTerritory().then(function(){ invalidateTerritory(); renderFactionsPanel(); updateActiveLayersHud(); });
}
function setBleedMode(v){ STATE.layers.bleedMode = v==='bleed'; invalidateTerritory(); }
async function toggleTerritoryScope(val){ STATE.legendAll=val; await Promise.all([loadTerritory(),loadCapitals()]); invalidateTerritory(); renderFactionsPanel(); }

function updateActiveLayersHud(){
  const items=[];
  if(STATE.territoryMode!=='none') items.push({label:TERRITORY_MODE_LABELS[STATE.territoryMode],color:'#d43838'});
  if(STATE.layers.topographic) items.push({label:'Topographic',color:'#b09860'});
  if(STATE.layers.climate) items.push({label:'Climate',color:'#f08030'});
  if(STATE.layers.drainage) items.push({label:'Drainage',color:'#3888c8'});
  if(STATE.layers.activity) items.push({label:'Activity',color:'#ff8828'});
  let hud=document.getElementById('activeLayersHud');
  if(!hud){
    hud=el('<div id="activeLayersHud" style="position:absolute;bottom:10px;right:10px;background:rgba(24,18,10,.72);'+
      'color:#f4efe4;border-radius:8px;padding:8px 11px;font-size:11px;z-index:15;max-width:200px"></div>');
    document.getElementById('mapWrap').appendChild(hud);
  }
  const vig=document.getElementById('modeVignette');
  if(!items.length){
    hud.style.display='none';
    if(vig) vig.style.boxShadow='inset 0 0 0 0 transparent';
    return;
  }
  hud.style.display='block';
  hud.innerHTML='<div style="font-weight:700;margin-bottom:4px;letter-spacing:.4px;text-transform:uppercase;font-size:9.5px;color:#d8c9a0">Active Layers</div>'+
    items.map(function(it){ return '<div style="display:flex;align-items:center;gap:6px;padding:1px 0">'+
      '<span style="width:9px;height:9px;border-radius:50%;background:'+it.color+';flex-shrink:0"></span>'+esc(it.label)+'</div>'; }).join('');
  if(vig) vig.style.boxShadow='inset 0 0 0 5px '+items[0].color+'55, inset 0 0 40px 2px '+items[0].color+'33';
}


function renderLegend(){
  if(!$('#sbLegend')) return;   // view torn down (navigated away mid-load)
  const counts={};
  STATE.sites.forEach(s=>{ counts[s.type]=(counts[s.type]||0)+1; });
  const types=Object.keys(counts).sort((a,b)=>counts[b]-counts[a]);
  $('#sbLegend').innerHTML='<h3>Site Types <span class="small-btn" onclick="MapView.legendAll(true)">all</span> <span class="small-btn" onclick="MapView.legendAll(false)">none</span></h3>'+
    '<div class="hint" style="margin-bottom:8px">Zoom in past 2× on the map to see these symbols in place of dots.</div>'+
    types.map(function(t){
      const icon=SITE_ICONS[t];
      const sw=icon
        ? '<img class="leg-icon" src="/icons/carto/'+icon+'.png" alt="">'
        : '<span class="leg-sw" style="background:'+siteColor(t)+'"></span>';
      return '<div class="leg-row '+(STATE.legendOff.has(t)?'off':'')+'" onclick="MapView.toggleLegendType(\''+t+'\')">'+
        sw+esc(t)+' <span class="hint" style="margin-left:auto">'+counts[t]+'</span></div>'; }).join('');
}
function toggleLegendType(t){
  if(STATE.legendOff.has(t)) STATE.legendOff.delete(t); else STATE.legendOff.add(t);
  renderLegend(); draw();
}
function legendAll(show){
  if(show) STATE.legendOff.clear();
  else STATE.sites.forEach(s=>STATE.legendOff.add(s.type));
  renderLegend(); draw();
}

/* ---- Folklands ---------------------------------------------------------
   Named for the Old English *folcland*. Land held by a people under their
/* ---- Factions ------------------------------------------------------------
   Grouped under collapsible race headers because a world this size produces
   dozens of civilizations and a flat alphabetical list buries the big powers
   among the small ones. Within each race they're ordered by controlled tile
   area, so the civilizations that actually shaped the map sit at the top.
   Clicking one selects it (highlighting its territory) and centers the map
   on its capital, the same way Trade's hub list jumps to a site. The
   smaller factions/guilds list (not tied to territory) sits below it. ---- */
const FOLK_OPEN={};   // race -> expanded?
function renderCivsPanel(){
  if(!STATE.territory){ return ''; }
  const civs=STATE.territory.civs.slice();
  const byRace={};
  civs.forEach(function(c){
    const r=c.race||'unknown';
    (byRace[r]=byRace[r]||[]).push(c);
  });
  const races=Object.keys(byRace).sort(function(a,b){
    const ta=byRace[a].reduce(function(s,c){return s+(c.tiles||0);},0);
    const tb=byRace[b].reduce(function(s,c){return s+(c.tiles||0);},0);
    return tb-ta || a.localeCompare(b);
  });
  // a race group holding the selected civilization stays open regardless
  if(STATE.selectedCiv){
    const sel=civs.find(function(c){ return c.id==STATE.selectedCiv; });
    if(sel) FOLK_OPEN[sel.race||'unknown']=true;
  }

  let html='<h3>Civilizations <span class="hint">('+civs.length+')</span></h3>';

  if(!civs.length){
    html+='<div class="empty-hint">None found. Try "include minor governments" in Layers.</div>';
  }else{
    STATE._folkRaces=races;   // index-based lookup, so race names never need quote-escaping into an attribute
    races.forEach(function(race, ri){
      // largest group opens by default
      if(FOLK_OPEN[race]===undefined) FOLK_OPEN[race]=(ri===0);
      const open=!!FOLK_OPEN[race];
      const group=byRace[race].slice().sort(function(a,b){ return (b.tiles||0)-(a.tiles||0) || a.name.localeCompare(b.name); });
      html+='<div class="folk-group'+(open?' open':'')+'">'+
        '<div class="folk-head" onclick="MapView.toggleFolkRace('+ri+')">'+
          '<span class="fh-arrow">▸</span>'+
          '<span class="fh-race">'+esc(race.charAt(0).toUpperCase()+race.slice(1))+'</span>'+
          '<span class="fh-count">'+group.length+'</span>'+
        '</div><div class="folk-body">';
      group.forEach(function(c){
        html+='<div class="civ-item'+(STATE.selectedCiv==c.id?' sel':'')+'" onclick="MapView.selectCiv(\''+c.id+'\')">'+
          '<span class="civ-sw" style="background:'+c.color+'"></span>'+
          '<span class="civ-n">'+esc(c.name)+'</span>'+
          '<span class="civ-area" title="Controlled tiles">'+(c.tiles||0)+'</span></div>';
      });
      html+='</div></div>';
    });
  }
  if(STATE.selectedCiv) html+='<button class="small-btn" style="margin-top:10px" onclick="MapView.selectCiv(null)">Clear selection</button>';
  return html;
}
function toggleFolkRace(ri){
  const race=(STATE._folkRaces||[])[ri];
  if(race==null) return;
  FOLK_OPEN[race]=!FOLK_OPEN[race];
  renderFactionsPanel();
}
function selectCiv(cid){
  STATE.selectedCiv = STATE.selectedCiv===cid ? null : cid;
  renderFactionsPanel(); invalidateTerritory();
  if(STATE.selectedCiv){
    const c=STATE.capitals[STATE.selectedCiv];
    if(c && c.x!=null){
      STATE.offsetX = $('#mapCanvas').width/2 - c.x*STATE.zoom;
      STATE.offsetY = $('#mapCanvas').height/2 - c.y*STATE.zoom;
      draw();
    }
  }
}

function renderFactionsPanel(){
  if(!$('#sbFactions')) return;   // view torn down (navigated away mid-load)
  const civsHtml=renderCivsPanel();
  const guildsHtml='<h3 style="margin-top:18px">Factions & Guilds</h3>'+
    (STATE.factions.length ? STATE.factions.map(function(f){ return '<div class="faction-item"><div class="ft">'+esc(f.type)+' - '+f.n_members+' members</div><div>'+esc(f.name)+'</div></div>'; }).join('') : '<div class="empty-hint">No smaller factions found in this world.</div>');
  $('#sbFactions').innerHTML=civsHtml+guildsHtml;
}

function renderCampaignsPanel(){
  if(!$('#sbCampaigns')) return;   // view torn down (navigated away mid-load)
  const withPaths=STATE.campaigns.filter(function(c){ return c.path.length>=2; });
  $('#sbCampaigns').innerHTML='<h3>Historical Campaigns</h3>'+
    '<div class="hint">Real battles from named wars, connected in year order.</div>'+
    (withPaths.length ? withPaths.map(function(c){ return '<div class="campaign-item" onclick="MapView.selectCampaign('+c.id+')"><div class="ft">Year '+(c.year!=null?c.year:'?')+'-'+(c.end_year!=null?c.end_year:'?')+' - '+c.n_battles+' battles</div><div>'+esc(c.name||'unnamed war')+'</div></div>'; }).join('') : '<div class="empty-hint">No multi-battle wars with known locations found.</div>');
}
function selectCampaign(id){
  STATE.selectedCampaign = STATE.selectedCampaign===id ? null : id;
  STATE.layers.campaigns = !!STATE.selectedCampaign;
  draw();
}

function renderCommercePanel(){
  if(!$('#sbCommerce')) return;   // view torn down (navigated away mid-load)
  const hubs=STATE.tradeHubs||[];
  $('#sbCommerce').innerHTML='<h3>Trade & Commerce</h3>'+
    '<div class="hint">Real merchant-company sites, plus your busiest civilian settlements as likely markets.</div>'+
    (hubs.length ? hubs.map(function(h){ return '<div class="faction-item" onclick="MapView.flyToTile('+h.x+','+h.y+')">'+
      '<div class="ft">'+(h.company?esc(h.company):'Market settlement')+' · '+h.events+' events</div>'+
      '<div>'+esc(h.site_name)+'</div></div>'; }).join('') :
      '<div class="empty-hint">No clear trade hubs found in this world.</div>');
}
function flyToTile(x,y){
  // (standalone DFCart switched views here; inside DwarfWiki the router has
  //  already put us on the map route before this can be clicked)
  STATE.offsetX = $('#mapCanvas').width/2 - x*STATE.zoom;
  STATE.offsetY = $('#mapCanvas').height/2 - y*STATE.zoom;
  draw();
}

function openSitePopup(s){
  let capEntry=null;
  for(const cid in (STATE.capitals||{})){ if(STATE.capitals[cid].site_id===s.id){ capEntry=[cid,STATE.capitals[cid]]; break; } }
  const capName = capEntry ? (STATE.territory.civs.find(function(c){return c.id==capEntry[0];})||{}).name : null;
  $('#mapModal').innerHTML='<h3>'+esc(s.name)+'</h3>'+
    '<div class="hint">'+esc(s.type)+' - '+s.events+' recorded events - '+s.structures+' structures</div>'+
    (capEntry ? '<div class="hint" style="color:var(--accent);font-weight:600">Capital of '+esc(capName||'a realm')+'</div>' : '')+
    '<div class="modal-actions">'+
    // now that the map lives inside the wiki, a site on the map can open
    // its own page directly. No second app, no pasting a name into search
    '<button class="btn primary" onclick="MapView.openSiteInWiki('+s.id+')">Read its history &rarr;</button>'+
    '<button class="btn" onclick="MapView.closeModal()">Close</button>'+
    (capEntry ? '<button class="btn" onclick="MapView.clearCapitalOverride(\''+capEntry[0]+'\')">Reset capital to default</button>' :
                '<button class="btn" onclick="MapView.promptSetCapital('+s.id+')">Make this a realm capital</button>')+
    '</div>';
  $('#mapModalBg').style.display='flex';
}
/* Map -> wiki. The whole point of the merge: click a town, read about it. */
function openSiteInWiki(siteId){
  closeModal();
  location.hash = '#/w/'+STATE.world+'/site/'+siteId;
}

async function promptSetCapital(siteId){
  const names=STATE.territory.civs.map(function(c){return c.name;}).join(', ');
  const civName=prompt('Which realm should this be the capital of?\\n('+names+')');
  if(!civName) return;
  const civ=STATE.territory.civs.find(function(c){return c.name.toLowerCase()===civName.trim().toLowerCase();});
  if(!civ){ toast('No realm with that exact name'); return; }
  await apiPost('/w/'+STATE.world+'/capitals',{civ_id:civ.id, site_id:siteId});
  await loadCapitals(); closeModal(); draw();
  toast(civ.name+"'s capital updated");
}
async function clearCapitalOverride(civId){
  await apiPost('/w/'+STATE.world+'/capitals',{civ_id:civId, site_id:null});
  await loadCapitals(); closeModal(); draw();
}

function openMarkerModal(x,y){
  $('#mapModal').innerHTML='<h3>Add a marker</h3>'+
    '<div class="field"><label>Label</label><input type="text" id="mkLabel" placeholder="e.g. My homebrew ruin"></div>'+
    '<div class="field"><label>Color</label><div class="color-row"><input type="color" id="mkColor" value="#7a2e2e"></div></div>'+
    '<div class="modal-actions"><button class="btn" onclick="MapView.closeModal();setTool(\'pan\')">Cancel</button>'+
    '<button class="btn primary" onclick="MapView.saveMarker('+x+','+y+')">Add</button></div>';
  $('#mapModalBg').style.display='flex';
}
async function saveMarker(x,y){
  const label=$('#mkLabel').value, color=$('#mkColor').value;
  await apiPost('/w/'+STATE.world+'/markers',{action:'add',x:x,y:y,label:label,color:color});
  await loadMarkers(); closeModal(); setTool('pan'); draw();
}

async function addRoute(s1,s2){
  await apiPost('/w/'+STATE.world+'/routes',{action:'add',from_site:s1.id,to_site:s2.id,label:''});
  await loadRoutes(); draw();
  toast('Route added: '+s1.name+' <-> '+s2.name);
}

async function renderGlobe(){
  if(!$('#globeGrid')) return;   // view torn down (navigated away mid-load)
  const g=await api('/globe');
  STATE.globe=g;
  renderContinentsLegend(g);
  const grid=$('#globeGrid');
  grid.style.gridTemplateColumns='repeat('+g.cols+',1fr)';
  grid.innerHTML='';
  const total=g.rows*g.cols;
  for(let slot=1; slot<=total; slot++){
    grid.appendChild(buildGlobeCell(g.grid[slot], [slot], g));
  }
}
function renderContinentsLegend(g){
  if(!$('#continentLegend')) return;   // view torn down (navigated away mid-load)
  const ids=[1,2,3,4,5];
  $('#continentLegend').innerHTML=ids.map(function(cid){
    const c=(g.continents||{})[cid];
    const name=c?c.name:('Continent '+cid+' (unused)');
    const color=c?c.color:'#ccc4ac';
    return '<span class="small-btn" style="border-color:'+color+';display:flex;align-items:center;gap:5px;cursor:pointer" onclick="MapView.renameContinentPrompt('+cid+')">'+
      '<span style="width:10px;height:10px;border-radius:50%;background:'+color+';display:inline-block"></span>'+esc(name)+'</span>';
  }).join('');
}
async function renameContinentPrompt(cid){
  const g=STATE.globe;
  const cur=(g.continents||{})[cid];
  const name=prompt('Continent '+cid+' name:', cur?cur.name:('Continent '+cid));
  if(name===null) return;
  await apiPost('/globe',{action:'rename_continent', continent:cid, name:name});
  renderGlobe();
}
function buildGlobeCell(cell, path, globeState){
  const div=document.createElement('div');
  div.className='globe-cell';
  const continentId = cell && cell.continent;
  if(continentId && globeState.continents && globeState.continents[continentId] && path.length===1){
    div.style.boxShadow='inset 0 0 0 3px '+globeState.continents[continentId].color;
  }
  if(!cell || cell.type==='empty'){
    div.textContent='+';
  }else if(cell.type==='blank_ocean'){
    div.classList.add('ocean'); div.textContent='ocean';
  }else if(cell.type==='world'){
    div.classList.add('filled');
    const w=STATE.worlds.find(function(w){return w.name===cell.world;});
    div.style.backgroundImage='url('+API+'/w/'+cell.world+'/map.png)';
    div.appendChild(el('<div class="gc-label">'+esc(w?w.world_name:cell.world)+'</div>'));
  }else if(cell.type==='subdivided'){
    div.classList.add('subdivided');
    const sub=document.createElement('div');
    sub.className='globe-sub';
    sub.style.gridTemplateColumns='repeat('+cell.cols+',1fr)';
    const letters='abcdefghijklmnopqrstuvwxyz';
    for(let i=0;i<cell.rows*cell.cols;i++){
      const letter=letters[i];
      const childCell=(cell.children||{})[letter];
      const childPath=path.concat([letter]);
      const childDiv=buildGlobeCell(childCell, childPath, globeState);
      childDiv.addEventListener('click',function(ev){ ev.stopPropagation(); openGlobeCellModal(childPath); });
      sub.appendChild(childDiv);
    }
    div.appendChild(sub);
    return div;
  }
  div.addEventListener('click',function(){ openGlobeCellModal(path); });
  return div;
}
function openGlobeCellModal(path){
  const worldOpts=STATE.worlds.map(function(w){ return '<option value="'+w.name+'">'+esc(w.world_name)+'</option>'; }).join('');
  const isTopLevel = path.length===1;
  let continentField='';
  if(isTopLevel){
    const g=STATE.globe||{continents:{}};
    const curCell=g.grid[path[0]];
    const curContinent=curCell?curCell.continent:null;
    let opts='<option value="">None</option>';
    for(let cid=1;cid<=5;cid++){
      const c=(g.continents||{})[cid];
      const label=c?c.name:('Continent '+cid);
      opts+='<option value="'+cid+'"'+(curContinent==cid?' selected':'')+'>'+esc(label)+'</option>';
    }
    continentField='<div class="field"><label>Continent</label><select id="gcContinent">'+opts+'</select></div>';
  }
  $('#mapModal').innerHTML='<h3>Slot '+path.join('')+'</h3>'+
    '<div class="field"><label>Assign</label><select id="gcType" onchange="$(\'#gcWorldRow\').style.display=this.value===\'world\'?\'block\':\'none\'">'+
      '<option value="empty">Empty</option><option value="world">A world</option><option value="blank_ocean">Blank ocean (no history)</option></select></div>'+
    '<div class="field" id="gcWorldRow" style="display:none"><label>World</label><select id="gcWorld">'+worldOpts+'</select></div>'+
    continentField+
    (isTopLevel?'':'<div class="hint">Sub-cells share their parent slot’s continent as one cluster.</div>')+
    '<div class="hint">Have a cluster of small islands that do not fit one slot? Subdivide this cell instead.</div>'+
    '<div class="modal-actions"><button class="btn" onclick="MapView.closeModal()">Cancel</button>'+
    '<button class="btn" onclick=\'subdivideGlobeCell('+JSON.stringify(path)+')\'>Subdivide (2x2)</button>'+
    '<button class="btn primary" onclick=\'saveGlobeCell('+JSON.stringify(path)+')\'>Save</button></div>';
  $('#mapModalBg').style.display='flex';
}
async function saveGlobeCell(path){
  const type=$('#gcType').value;
  const cell = type==='world' ? {type:'world', world:$('#gcWorld').value} : {type:type};
  await apiPost('/globe',{action:'set', path:path, cell:cell});
  const contSel=$('#gcContinent');
  if(contSel){
    const val=contSel.value;
    await apiPost('/globe',{action:'set_continent', path:path, continent: val?parseInt(val):null});
  }
  closeModal(); renderGlobe();
}
async function subdivideGlobeCell(path){
  await apiPost('/globe',{action:'subdivide', path:path, cols:2, rows:2});
  closeModal(); renderGlobe();
}



/* =========================================================================
   MOUNT / UNMOUNT. The lifecycle DwarfWiki's router drives
   ========================================================================= */
let _mounted=false, _resizeHandler=null, _mountedWorld=null, _wired=false;

async function mount(world){
  if(!document.getElementById('mapCanvas')) return;
  _mounted=true;
  resizeCanvas();
  if(!_resizeHandler){
    _resizeHandler=function(){ if(_mounted) resizeCanvas(); };
    window.addEventListener('resize', _resizeHandler);
  }
  // the map markup is re-injected on every visit, so interaction handlers
  // must be re-bound each time. They're attached to the fresh canvas node
  _wired=false;
  wireMapInteraction(); _wired=true;
  renderLayersPanel();
  if(world && world!==_mountedWorld){
    _mountedWorld=world;
    await loadWorld(world);
  }else{
    zoomReset();
    renderLegend(); renderFactionsPanel();
    renderCampaignsPanel(); renderCommercePanel();
    draw();
  }
}

function unmount(){
  _mounted=false;
  // the capital-pulse rAF loop re-schedules itself; this flag stops it so an
  // unmounted map isn't still repainting a canvas that's no longer on screen
  _capAnimRunning=false;
}

function invalidateWorld(world){ if(_mountedWorld===world) _mountedWorld=null; }

window.MapView={
  mount: mount,
  resize: resizeCanvas,
  openSiteInWiki: openSiteInWiki,
  unmount: unmount,
  invalidateWorld: invalidateWorld,
  autoFitPlanet: autoFitPlanet,
  clearCapitalOverride: clearCapitalOverride,
  closeModal: closeModal,
  commitPlanetSize: commitPlanetSize,
  flyToTile: flyToTile,
  legendAll: legendAll,
  onPlanetSlider: onPlanetSlider,
  promptSetCapital: promptSetCapital,
  renameContinentPrompt: renameContinentPrompt,
  saveMarker: saveMarker,
  selectCampaign: selectCampaign,
  selectCiv: selectCiv,
  setBleedMode: setBleedMode,
  setTerritoryMode: setTerritoryMode,
  setTool: setTool,
  switchTab: switchTab,
  toggleFolkRace: toggleFolkRace,
  toggleLayer: toggleLayer,
  toggleLayoutPanel: toggleLayoutPanel,
  toggleLegendType: toggleLegendType,
  toggleTerritoryScope: toggleTerritoryScope,
  zoomBy: zoomBy,
  zoomReset: zoomReset,
};

})();
