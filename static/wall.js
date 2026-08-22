/* =========================================================================
   wall.js  --  the Map Wall
   =========================================================================
   A Minecraft-map-wall for Dwarf Fortress: place as many generated regions
   as you like on one shared surface, paint over the seams where their
   coastlines and mountain ranges refuse to line up, fill the gaps with
   procedural sea, and save the whole arrangement as a named continent.

   COORDINATES
   Everything is in DF overworld tiles (1 tile ~= 1873m), in one continuous
   space, NOT in grid cells. That's deliberate: a Pocket region is 17 tiles
   and a Large is 257, so a cell-based grid would either force a 17-tile
   island to occupy a 257-tile slot, or force everything to the same size.
   In tile space a pocket island can sit in a bay off a mainland at its true
   relative scale. The grid you snap to is only an editing aid.

   STORAGE
   - placements: [{world, x, y}]           -- top-left corner, in tiles
   - oceans:     [{x,y,w,h,seed,style}]    -- a seed, not pixels: a 257x257
                                              sea costs ~50 bytes instead of
                                              66,000 tile entries
   - paint:      {"x,y": biomeIndex}       -- sparse, because a wall is
                                              mostly untouched real data
                                              with edits only at the seams

   Nothing here modifies your legends data. Painting is an overlay; the
   underlying regions are always recoverable via the "Raw maps" toggle.
   ========================================================================= */
(function(){
'use strict';

const API = '/api';
const $ = s => document.querySelector(s);

/* Chunked paint storage. A wall can grow to tens of thousands of tiles
   across; iterating every painted tile each frame would eventually cost
   real time, so paint is bucketed and only visible buckets are drawn. */
const CHUNK = 64;
function chunkKey(x,y){ return ((x>>6)|0)+','+((y>>6)|0); }

const W = {
  // starts as a blank document rather than null: the host page sizes the
  // canvas (which triggers a draw) BEFORE mount() runs, so a null here threw
  // "Cannot read properties of null (reading 'oceans')" on first open
  continent: blankContinent(),
  paintChunks: new Map(),   // "cx,cy" -> Map("x,y" -> biomeIndex)
  view: {x:-40, y:-40, zoom:1.2},
  tool: 'pan',
  brush: 1,
  color: '#789452',         // the colour the brush lays down
  palette: [],              // 10 base biomes from the server
  shades: [],               // base colours expanded into a light->dark ramp
  showShades: false,
  magicFamily: null,        // biome name the magic brush blends shades from
  magicSeed: Math.random()*10000,   // keeps one session's blotches stable
  labels: [],               // {x,y,text,major}
  worlds: [],
  images: new Map(),        // world -> {lo:Image, hi:Image|null, hiTried:bool}
  oceanCache: new Map(),    // ocean id -> canvas
  undo: [],
  showRaw: false,
  dirty: true,
  selected: null,           // index into placements, when moving
  selectedOcean: null,      // index into oceans, when moving a sea instead
  mounted: false,
};
const UNDO_MAX = 10;

/* ---------------------------------------------------------------------
   Seeded PRNG + value noise. Ocean is generated from a seed rather than
   stored as pixels, so it round-trips through save/load byte-for-byte and
   costs almost nothing on disk.
   --------------------------------------------------------------------- */
function mulberry32(a){
  return function(){
    a |= 0; a = a + 0x6D2B79F5 | 0;
    let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
function makeNoise(seed){
  const rnd = mulberry32(seed);
  const perm = new Uint8Array(512);
  const p = new Uint8Array(256);
  for(let i=0;i<256;i++) p[i]=i;
  for(let i=255;i>0;i--){ const j=(rnd()*(i+1))|0; const t=p[i]; p[i]=p[j]; p[j]=t; }
  for(let i=0;i<512;i++) perm[i]=p[i&255];
  function grad(h,x,y){ const u=h&1?x:-x, v=h&2?y:-y; return u+v; }
  function fade(t){ return t*t*t*(t*(t*6-15)+10); }
  return function(x,y){
    const X=Math.floor(x)&255, Y=Math.floor(y)&255;
    const xf=x-Math.floor(x), yf=y-Math.floor(y);
    const u=fade(xf), v=fade(yf);
    const aa=perm[perm[X]+Y], ab=perm[perm[X]+Y+1];
    const ba=perm[perm[X+1]+Y], bb=perm[perm[X+1]+Y+1];
    const x1=grad(aa,xf,yf)*(1-u)+grad(ba,xf-1,yf)*u;
    const x2=grad(ab,xf,yf-1)*(1-u)+grad(bb,xf-1,yf-1)*u;
    return (x1*(1-v)+x2*v);
  };
}

/* Ocean styles. You asked not to be stuck with one look. Each style is a
   different set of noise parameters, and every ocean also carries its own
   seed, so "Re-roll" gives a fresh variant within the same character. */
const OCEAN_STYLES = {
  // lo/hi are the depth BAND the style occupies (0 = shoreline shallows,
  // 1 = abyss). Stated outright rather than emerging from a curve, because
  // the first version had a "coastal shelf" that came out deeper than open
  // ocean. Easy to get backwards when depth is an indirect side effect.
  shelf:    {label:'Coastal shelf', oct:5, base:0.022, ridge:0.15, lo:0.04, hi:0.38, contrast:1.05},
  open:     {label:'Open ocean',    oct:5, base:0.013, ridge:0.00, lo:0.30, hi:0.66, contrast:1.75},
  archi:    {label:'Broken water',  oct:6, base:0.030, ridge:0.35, lo:0.12, hi:0.72, contrast:1.15},
  ridges:   {label:'Ridged sea',    oct:6, base:0.016, ridge:0.75, lo:0.24, hi:0.86, contrast:1.20},
  trenches: {label:'Deep trenches', oct:5, base:0.008, ridge:0.55, lo:0.30, hi:1.00, contrast:1.45},
};
const OCEAN_STYLE_ORDER = ['shelf','open','archi','ridges','trenches'];   // shallow -> deep

/* Depth ramp. Anchored on the real Ocean colour the map renderer uses
   (46,74,102) so procedural sea sits beside a region's own sea without a
   visible join, then extended darker for trenches and lighter for shelves. */
function depthColor(d){
  // d: 0 = shallowest, 1 = deepest
  const stops = [
    [0.00, [ 96,143,170]],
    [0.28, [ 63,101,133]],
    [0.55, [ 46, 74,102]],
    [0.78, [ 31, 51, 76]],
    [1.00, [ 18, 31, 52]],
  ];
  for(let i=0;i<stops.length-1;i++){
    const [p0,c0]=stops[i], [p1,c1]=stops[i+1];
    if(d<=p1){
      const t=(d-p0)/(p1-p0||1);
      return [
        Math.round(c0[0]+(c1[0]-c0[0])*t),
        Math.round(c0[1]+(c1[1]-c0[1])*t),
        Math.round(c0[2]+(c1[2]-c0[2])*t),
      ];
    }
  }
  return stops[stops.length-1][1];
}

function buildOceanCanvas(o){
  const style = OCEAN_STYLES[o.style] || OCEAN_STYLES.open;
  const n = makeNoise(o.seed||1);
  const c = document.createElement('canvas');
  c.width = Math.max(1,o.w); c.height = Math.max(1,o.h);
  const ctx = c.getContext('2d');
  const img = ctx.createImageData(c.width, c.height);
  const d = img.data;
  for(let y=0;y<c.height;y++){
    for(let x=0;x<c.width;x++){
      let amp=1, freq=style.base, sum=0, norm=0;
      for(let oi=0; oi<style.oct; oi++){
        let v = n((x+o.x)*freq, (y+o.y)*freq);
        if(style.ridge>0){
          // ridged noise: fold the signal to make sharp crests, which is
          // what reads as an undersea ridge rather than soft blobs
          v = 1 - Math.abs(v);
          v = v*v;
          v = v*style.ridge + (1-style.ridge)*((v+1)/2);
        }else{
          v = (v+1)/2;
        }
        sum += v*amp; norm += amp;
        amp *= 0.5; freq *= 2.05;
      }
      let depth = sum/norm;
      depth = (depth-0.5)*style.contrast + 0.5;
      depth = Math.max(0, Math.min(1, depth));
      depth = style.lo + depth*(style.hi-style.lo);   // map into this style's band
      const rgb = depthColor(depth);
      const i=(y*c.width+x)*4;
      d[i]=rgb[0]; d[i+1]=rgb[1]; d[i+2]=rgb[2]; d[i+3]=255;
    }
  }
  ctx.putImageData(img,0,0);
  return c;
}
function oceanCanvas(o){
  const key = [o.x,o.y,o.w,o.h,o.seed,o.style].join('|');
  if(!W.oceanCache.has(key)) W.oceanCache.set(key, buildOceanCanvas(o));
  return W.oceanCache.get(key);
}

/* ---------------------------------------------------------------------
   Region imagery. Every placed region loads its small map.png (a few KB).
   The 1536px detailed render is 1.5MB apiece, so it loads lazily and only
   for regions actually on screen at high zoom. A hundred-region wall
   would otherwise pull ~150MB for detail you can't see.
   --------------------------------------------------------------------- */
function worldSize(name){
  const w = W.worlds.find(x=>x.name===name);
  return w && w.width ? {w:w.width, h:w.height||w.width} : {w:257,h:257};
}
function getImages(name){
  if(!W.images.has(name)){
    const rec = {lo:null, hi:null, hiTried:false};
    const lo = new Image();
    lo.onload = ()=>{ W.dirty=true; draw(); };
    lo.src = API+'/w/'+name+'/map.png';
    rec.lo = lo;
    W.images.set(name, rec);
  }
  return W.images.get(name);
}
function requestDetail(name){
  const rec = getImages(name);
  if(rec.hiTried) return rec.hi;
  rec.hiTried = true;
  const hi = new Image();
  hi.onload = ()=>{ rec.hi=hi; W.dirty=true; draw(); };
  hi.onerror = ()=>{ rec.hi=null; };
  hi.src = API+'/w/'+name+'/detailed_map.png';
  return null;
}

/* ---- coordinate transforms ---- */
function t2sx(tx){ return (tx - W.view.x) * W.view.zoom; }
function t2sy(ty){ return (ty - W.view.y) * W.view.zoom; }
function s2tx(sx){ return sx / W.view.zoom + W.view.x; }
function s2ty(sy){ return sy / W.view.zoom + W.view.y; }

function viewportTiles(cv){
  return {
    x0: Math.floor(s2tx(0)) - 1,
    y0: Math.floor(s2ty(0)) - 1,
    x1: Math.ceil(s2tx(cv.width)) + 1,
    y1: Math.ceil(s2ty(cv.height)) + 1,
  };
}

/* ---- paint helpers ---- */
function paintGet(x,y){
  const ch = W.paintChunks.get(chunkKey(x,y));
  return ch ? ch.get(x+','+y) : undefined;
}
function paintSet(x,y,b){
  const k = chunkKey(x,y);
  let ch = W.paintChunks.get(k);
  if(!ch){ ch = new Map(); W.paintChunks.set(k,ch); }
  if(b==null) ch.delete(x+','+y); else ch.set(x+','+y,b);
}
function paintFromFlat(flat){
  W.paintChunks.clear();
  for(const k in flat){
    const [x,y]=k.split(',').map(Number);
    paintSet(x,y,flat[k]);
  }
}
function paintToFlat(){
  const out={};
  for(const ch of W.paintChunks.values())
    for(const [k,v] of ch) out[k]=v;
  return out;
}
function paintCount(){
  let n=0; for(const ch of W.paintChunks.values()) n+=ch.size; return n;
}

/* ---- undo (10 deep, as asked) ---- */
function pushUndo(label){
  if(!W.continent) return;
  W.undo.push({label, paint: paintToFlat(),
               placements: JSON.parse(JSON.stringify(W.continent.placements)),
               oceans: JSON.parse(JSON.stringify(W.continent.oceans)),
               labels: JSON.parse(JSON.stringify(W.labels||[]))});
  if(W.undo.length>UNDO_MAX) W.undo.shift();
  refreshChrome();
}
function doUndo(){
  const st = W.undo.pop();
  if(!st){ toast('Nothing left to undo.'); return; }
  paintFromFlat(st.paint);
  W.continent.placements = st.placements;
  W.continent.oceans = st.oceans;
  W.labels = st.labels||[];
  W.dirty=true; draw(); refreshChrome();
  toast('Undid: '+st.label);
}

function toast(msg){
  if(window.toast) window.toast(msg);
}

/* ---------------------------------------------------------------------
   DRAW
   --------------------------------------------------------------------- */
function draw(){
  const cv = document.getElementById('wallCanvas');
  if(!cv || !cv.width || !W.continent) return;
  const ctx = cv.getContext('2d');
  ctx.imageSmoothingEnabled = W.view.zoom < 2;   // crisp tiles when zoomed in
  ctx.fillStyle = '#0d1826';
  ctx.fillRect(0,0,cv.width,cv.height);

  const vp = viewportTiles(cv);
  const z = W.view.zoom;

  // 1. procedural sea
  for(const o of (W.continent.oceans||[])){
    if(o.x>vp.x1 || o.y>vp.y1 || o.x+o.w<vp.x0 || o.y+o.h<vp.y0) continue;
    const c = oceanCanvas(o);
    ctx.drawImage(c, t2sx(o.x), t2sy(o.y), o.w*z, o.h*z);
  }
  if(W.selectedOcean!=null && W.continent.oceans[W.selectedOcean]){
    const o=W.continent.oceans[W.selectedOcean];
    ctx.strokeStyle='#ffd97a'; ctx.lineWidth=2;
    ctx.strokeRect(t2sx(o.x), t2sy(o.y), o.w*z, o.h*z);
  }

  // 2. the regions themselves
  (W.continent.placements||[]).forEach((p,idx)=>{
    const sz = worldSize(p.world);
    if(p.x>vp.x1 || p.y>vp.y1 || p.x+sz.w<vp.x0 || p.y+sz.h<vp.y0) return;
    const rec = getImages(p.world);
    // switch to the detailed render once a tile is worth ~3 screen pixels
    let img = rec.lo;
    if(z >= 3){
      if(rec.hi) img = rec.hi;
      else requestDetail(p.world);
    }
    if(img && img.complete && img.naturalWidth){
      ctx.drawImage(img, t2sx(p.x), t2sy(p.y), sz.w*z, sz.h*z);
    }else{
      ctx.fillStyle='#1b2b3d';
      ctx.fillRect(t2sx(p.x), t2sy(p.y), sz.w*z, sz.h*z);
    }
    if(W.selected===idx){
      ctx.strokeStyle='#ffd97a'; ctx.lineWidth=2;
      ctx.strokeRect(t2sx(p.x), t2sy(p.y), sz.w*z, sz.h*z);
    }
  });

  // 3. hand-painted tiles (skipped entirely in Raw mode)
  if(!W.showRaw && W.paintChunks.size){
    const cx0=(vp.x0>>6), cx1=(vp.x1>>6), cy0=(vp.y0>>6), cy1=(vp.y1>>6);
    for(let cy=cy0; cy<=cy1; cy++){
      for(let cx=cx0; cx<=cx1; cx++){
        const ch=W.paintChunks.get(cx+','+cy);
        if(!ch) continue;
        for(const [k,b] of ch){
          const i=k.indexOf(','), x=+k.slice(0,i), y=+k.slice(i+1);
          const col=paintColor(b, z);
          if(!col) continue;
          ctx.fillStyle=col;
          ctx.fillRect(Math.floor(t2sx(x)), Math.floor(t2sy(y)),
                       Math.ceil(z), Math.ceil(z));
        }
      }
    }
  }

  drawLabels(ctx);
  drawCompass(ctx, cv);
  W.dirty=false;
}

/* A static compass rose, bottom-right. A watermark, not a minimap, so it
   costs nothing to keep on screen. */
function drawCompass(ctx, cv){
  const r=34, cx=cv.width-r-22, cy=cv.height-r-22;
  ctx.save();
  ctx.globalAlpha=0.5;
  ctx.strokeStyle='#f0e4c4'; ctx.fillStyle='#f0e4c4'; ctx.lineWidth=1.4;
  ctx.beginPath(); ctx.arc(cx,cy,r,0,Math.PI*2); ctx.stroke();
  ctx.beginPath(); ctx.arc(cx,cy,r*0.72,0,Math.PI*2); ctx.globalAlpha=0.25; ctx.stroke();
  ctx.globalAlpha=0.6;
  // four points
  for(let i=0;i<4;i++){
    const a=-Math.PI/2 + i*Math.PI/2;
    ctx.beginPath();
    ctx.moveTo(cx+Math.cos(a)*r*0.92, cy+Math.sin(a)*r*0.92);
    ctx.lineTo(cx+Math.cos(a+0.34)*r*0.22, cy+Math.sin(a+0.34)*r*0.22);
    ctx.lineTo(cx+Math.cos(a-0.34)*r*0.22, cy+Math.sin(a-0.34)*r*0.22);
    ctx.closePath();
    ctx.globalAlpha = i===0 ? 0.85 : 0.45;
    ctx.fill();
  }
  ctx.globalAlpha=0.8;
  ctx.font='bold 12px system-ui,sans-serif';
  ctx.textAlign='center'; ctx.textBaseline='middle';
  ctx.fillText('N', cx, cy-r-9);
  ctx.restore();
}

/* =========================================================================
   INTERACTION
   ========================================================================= */
let _wired=false, _drag=null, _painting=false, _resizeH=null;

function canvas(){ return document.getElementById('wallCanvas'); }

function resize(){
  const cv=canvas(); if(!cv) return;
  const wrap=cv.parentElement; if(!wrap) return;
  const r=wrap.getBoundingClientRect();
  if(!r.width || !r.height) return;
  cv.width=Math.floor(r.width); cv.height=Math.floor(r.height);
  draw();
}

function zoomBy(f, ax, ay){
  const cv=canvas(); if(!cv) return;
  ax = ax==null ? cv.width/2 : ax;
  ay = ay==null ? cv.height/2 : ay;
  const tx=s2tx(ax), ty=s2ty(ay);
  W.view.zoom = Math.max(0.06, Math.min(24, W.view.zoom*f));
  // keep the tile under the cursor pinned while zooming
  W.view.x = tx - ax/W.view.zoom;
  W.view.y = ty - ay/W.view.zoom;
  draw(); refreshChrome();
}

function fitAll(){
  const cv=canvas(); if(!cv) return;
  const b=wallBounds();
  if(!b){ W.view={x:-40,y:-40,zoom:1.2}; draw(); return; }
  const pad=30;
  const zx=cv.width/(b.w+pad*2), zy=cv.height/(b.h+pad*2);
  W.view.zoom=Math.max(0.06, Math.min(24, Math.min(zx,zy)));
  W.view.x=b.x-pad; W.view.y=b.y-pad;
  draw(); refreshChrome();
}

function wallBounds(){
  let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity, any=false;
  for(const p of (W.continent.placements||[])){
    const sz=worldSize(p.world);
    x0=Math.min(x0,p.x); y0=Math.min(y0,p.y);
    x1=Math.max(x1,p.x+sz.w); y1=Math.max(y1,p.y+sz.h); any=true;
  }
  for(const o of (W.continent.oceans||[])){
    x0=Math.min(x0,o.x); y0=Math.min(y0,o.y);
    x1=Math.max(x1,o.x+o.w); y1=Math.max(y1,o.y+o.h); any=true;
  }
  if(!any) return null;
  return {x:x0,y:y0,w:x1-x0,h:y1-y0};
}

/* which placement is under this tile, topmost first */
function hitPlacement(tx,ty){
  const ps=W.continent.placements||[];
  for(let i=ps.length-1;i>=0;i--){
    const sz=worldSize(ps[i].world);
    if(tx>=ps[i].x && ty>=ps[i].y && tx<ps[i].x+sz.w && ty<ps[i].y+sz.h) return i;
  }
  return -1;
}

/* which ocean rectangle is under this tile, topmost first. Same idea as
   hitPlacement, so a sea can be grabbed and dragged just like a region */
function hitOcean(tx,ty){
  const os=W.continent.oceans||[];
  for(let i=os.length-1;i>=0;i--){
    if(tx>=os[i].x && ty>=os[i].y && tx<os[i].x+os[i].w && ty<os[i].y+os[i].h) return i;
  }
  return -1;
}

function applyBrush(tx,ty,erase){
  const r=(W.brush-1)/2;
  for(let dy=-r; dy<=r; dy++){
    for(let dx=-r; dx<=r; dx++){
      const x=Math.round(tx+dx), y=Math.round(ty+dy);
      if(erase){ paintSet(x,y,null); continue; }
      paintSet(x,y, W.tool==='magic' ? magicPaintValue(x,y) : W.color);
    }
  }
  W.dirty=true;
}

/* ---------------------------------------------------------------------
   MAGIC BRUSH
   Pick a biome family, then paint like normal. Each tile gets one of
   that family's five shades instead of one flat colour, so a stroke
   reads like blended terrain instead of a single-tone patch. The mix
   is a deterministic hash of the tile's own coordinates (a coarse hash
   for a few-tile blotch and a finer one layered on top for grain)
   rather than Math.random(), so painting back over the same tile
   twice (or panning away and returning)doesn't flicker between
   unrelated shades; the same spot always resolves to the same blend
   for this session. "Re-roll blend" reseeds it for a different mix.
   --------------------------------------------------------------------- */
function hash01(x,y,seed){
  let h = Math.sin(x*12.9898 + y*78.233 + seed) * 43758.5453;
  return h - Math.floor(h);
}
function magicColorAt(x,y){
  const fam = W.shades.find(s=>s.name===W.magicFamily) || W.shades[0];
  if(!fam) return W.color;
  const steps = fam.steps;
  const coarse = hash01(Math.floor(x/3), Math.floor(y/3), W.magicSeed);
  const fine   = hash01(x, y, W.magicSeed+1);
  const t = coarse*0.65 + fine*0.35;
  const idx = Math.min(steps.length-1, Math.floor(t*steps.length));
  return steps[idx];
}
/* What actually gets stored for a magic-brush tile. Plain painted tiles
   are already one flat colour at every zoom level. Nothing to do there.
   Magic-brush tiles are deliberately MULTI-shade so they read as blended
   terrain up close, but that same variation reads as noise once you're
   zoomed out far enough that regions themselves fall back to their own
   flat, simplified art (see the rec.lo/rec.hi swap in draw()). So a
   magic-brush tile remembers both: its detailed blended shade, and which
   family it belongs to (so a flat mid-tone can stand in for it at low
   zoom). Encoded as one string, with a control-character prefix that
   can't collide with any real hex/rgba/named colour, so paintColor() can
   tell a magic tile from a plain one without a second data structure.
   \u0001 = a marker byte, never legal in a colour string. */
const MAGIC_PREFIX = '\u0001m|';
function magicPaintValue(x,y){
  const fam = W.magicFamily || (W.shades[0] && W.shades[0].name) || '';
  return MAGIC_PREFIX + fam + '|' + magicColorAt(x,y);
}
function setMagicFamily(name){ W.magicFamily=name; refreshChrome(); }
function rerollMagic(){ W.magicSeed = Math.random()*10000; toast('Blend reshuffled. Paint over an area again to see it.'); }

/* Paint values used to be indices into the 10-biome palette. They're colour
   strings now, which is what makes both the shade ramp and the eyedropper
   possible. You can lay down any colour, including one sampled straight off
   a region's own art. Old saves stored integers, so those still resolve. */
/* z is the current tile-to-screen zoom (same threshold (3)that swaps a
   region between its own flat/detailed art in draw()). Defaults to the
   "always detailed" branch so callers that don't care about LOD (PNG
   export, which always uses each region's own highest-detail art too)
   don't have to think about it. */
function paintColor(v, z=3){
  if(typeof v === 'string'){
    if(v.startsWith(MAGIC_PREFIX)){
      const rest = v.slice(MAGIC_PREFIX.length);
      const bar = rest.indexOf('|');
      const famName = rest.slice(0,bar), detail = rest.slice(bar+1);
      if(z < 3){
        const fam = W.shades.find(s=>s.name===famName);
        if(fam) return fam.steps[2];   // flat mid-tone, matching a region's own low-zoom art
      }
      return detail;
    }
    return v;
  }
  const p = W.palette[v];
  return p ? p.hex : null;
}

function wire(){
  const cv=canvas(); if(!cv || _wired) return;
  _wired=true;

  cv.addEventListener('contextmenu', e=>e.preventDefault());

  cv.addEventListener('mousedown', e=>{
    const r=cv.getBoundingClientRect();
    const mx=e.clientX-r.left, my=e.clientY-r.top;
    const tx=s2tx(mx), ty=s2ty(my);
    // right-drag always pans, whatever tool is active. Otherwise painting
    // a big area means constantly switching back to the pan tool
    if(e.button===2 || W.tool==='pan'){
      // a flag is readable without switching tools
      if(e.button!==2 && W.tool==='pan'){
        const li=hitLabel(tx,ty);
        if(li>=0){ editLabel(li); return; }
      }
      _drag={mode:'pan', px:e.clientX, py:e.clientY, vx:W.view.x, vy:W.view.y};
      cv.style.cursor='grabbing';
      return;
    }
    if(W.tool==='pick'){
      const r2=cv.getBoundingClientRect();
      const c=pickColorAt(e.clientX-r2.left, e.clientY-r2.top);
      if(c){ W.color=c; setTool('paint'); toast('Picked '+c+'. Brush ready.'); }
      else toast('Nothing to sample there.');
      return;
    }
    if(W.tool==='label'){
      const i=hitLabel(tx,ty);
      if(i>=0) editLabel(i); else addLabelAt(tx,ty);
      return;
    }
    if(W.tool==='paint' || W.tool==='erase' || W.tool==='magic'){
      pushUndo(W.tool==='erase'?'erase':(W.tool==='magic'?'magic paint':'paint'));
      _painting=true;
      applyBrush(tx,ty, W.tool==='erase');
      draw();
      return;
    }
    if(W.tool==='move'){
      // regions sit on top of the sea, so a region under the cursor wins;
      // only fall back to the ocean beneath it if there's no region there
      const i=hitPlacement(tx,ty);
      if(i>=0){
        W.selected=i; W.selectedOcean=null;
        pushUndo('move region');
        _drag={mode:'region', idx:i, px:e.clientX, py:e.clientY,
               ox:W.continent.placements[i].x, oy:W.continent.placements[i].y};
        draw(); refreshChrome();
        return;
      }
      const oi=hitOcean(tx,ty);
      W.selected=null; W.selectedOcean = oi>=0 ? oi : null;
      if(oi>=0){
        pushUndo('move ocean');
        _drag={mode:'ocean', idx:oi, px:e.clientX, py:e.clientY,
               ox:W.continent.oceans[oi].x, oy:W.continent.oceans[oi].y};
      }
      draw(); refreshChrome();
      return;
    }
  });

  window.addEventListener('mousemove', e=>{
    if(!W.mounted) return;
    const cvv=canvas(); if(!cvv) return;
    if(_drag && _drag.mode==='pan'){
      W.view.x = _drag.vx - (e.clientX-_drag.px)/W.view.zoom;
      W.view.y = _drag.vy - (e.clientY-_drag.py)/W.view.zoom;
      draw(); return;
    }
    if(_drag && _drag.mode==='region'){
      const p=W.continent.placements[_drag.idx];
      let nx=_drag.ox + (e.clientX-_drag.px)/W.view.zoom;
      let ny=_drag.oy + (e.clientY-_drag.py)/W.view.zoom;
      if(!e.altKey){ const g=W.snap||1; nx=Math.round(nx/g)*g; ny=Math.round(ny/g)*g; }
      p.x=Math.round(nx); p.y=Math.round(ny);
      draw(); refreshChrome(); return;
    }
    if(_drag && _drag.mode==='ocean'){
      const o=W.continent.oceans[_drag.idx];
      let nx=_drag.ox + (e.clientX-_drag.px)/W.view.zoom;
      let ny=_drag.oy + (e.clientY-_drag.py)/W.view.zoom;
      if(!e.altKey){ const g=W.snap||1; nx=Math.round(nx/g)*g; ny=Math.round(ny/g)*g; }
      o.x=Math.round(nx); o.y=Math.round(ny);
      draw(); refreshChrome(); return;
    }
    if(_painting){
      const r=cvv.getBoundingClientRect();
      applyBrush(s2tx(e.clientX-r.left), s2ty(e.clientY-r.top), W.tool==='erase');
      draw();
    }
  });

  window.addEventListener('mouseup', ()=>{
    _drag=null; _painting=false;
    const cvv=canvas(); if(cvv) cvv.style.cursor = W.tool==='pan'?'grab':'crosshair';
  });

  cv.addEventListener('wheel', e=>{
    e.preventDefault();
    const r=cv.getBoundingClientRect();
    zoomBy(e.deltaY<0 ? 1.18 : 1/1.18, e.clientX-r.left, e.clientY-r.top);
  }, {passive:false});
}

/* =========================================================================
   ACTIONS
   ========================================================================= */
function setTool(t){
  W.tool=t;
  const cv=canvas(); if(cv) cv.style.cursor = t==='pan'?'grab':'crosshair';
  refreshChrome();
}
function setBrush(n){ W.brush=n; refreshChrome(); }
function setColor(c){ W.color=c; refreshChrome(); }
function toggleShades(){ W.showShades=!W.showShades; refreshChrome(); }

/* Build a light->dark ramp from each biome. Five steps per colour turned out
   to be the gap: a flat swatch reads fine zoomed out, but up close DF's own
   terrain is speckled with neighbouring shades, so one flat tone next to it
   looks obviously painted. */
function buildShades(){
  const SHADE_MULT = [1.30, 1.14, 1.00, 0.86, 0.72];
  W.shades = W.palette.map(p=>{
    const [r,g,b] = p.rgb;
    return {
      name: p.name,
      steps: SHADE_MULT.map(m=>'#'+[r,g,b].map(ch=>{
        const v=Math.max(0,Math.min(255,Math.round(ch*m)));
        return v.toString(16).padStart(2,'0');
      }).join(''))
    };
  });
}

/* ---------------------------------------------------------------------
   EYEDROPPER
   Samples whatever is actually on screen under the cursor. Including a
   region's own generated art, and makes it the brush colour. This is the
   real answer to "the palette can't blend": rather than guessing which of
   fifty swatches matches a mountain's edge, take the mountain's own colour.
   Everything is served same-origin, so reading the canvas back is allowed.
   --------------------------------------------------------------------- */
function pickColorAt(sx, sy){
  const cv = canvas(); if(!cv) return null;
  try{
    const d = cv.getContext('2d').getImageData(Math.round(sx), Math.round(sy), 1, 1).data;
    if(d[3] === 0) return null;
    return '#'+[d[0],d[1],d[2]].map(v=>v.toString(16).padStart(2,'0')).join('');
  }catch(e){
    // a tainted canvas would land here; ours never is, but fail soft rather
    // than break the whole tool
    return null;
  }
}

/* ---------------------------------------------------------------------
   LABELS
   --------------------------------------------------------------------- */
function addLabelAt(tx,ty){
  const text = prompt('Label text:');
  if(text==null || !text.trim()) return;
  const major = confirm('Mark as a major landmark?\n\nOK  = major (stays visible when zoomed out)\nCancel = minor (hidden at low zoom)');
  pushUndo('add label');
  W.labels.push({x:Math.round(tx), y:Math.round(ty), text:text.trim(), major:major});
  draw(); refreshChrome();
}
function hitLabel(tx,ty){
  // generous hit radius in tiles, scaled so it stays clickable at any zoom
  const r = Math.max(3, 12/W.view.zoom);
  for(let i=W.labels.length-1;i>=0;i--){
    const L=W.labels[i];
    if(Math.abs(L.x-tx)<=r && Math.abs(L.y-ty)<=r) return i;
  }
  return -1;
}
function editLabel(i){
  const L=W.labels[i]; if(!L) return;
  const text=prompt('Label text (blank to delete):', L.text);
  if(text==null) return;
  pushUndo('edit label');
  if(!text.trim()){ W.labels.splice(i,1); }
  else{
    L.text=text.trim();
    L.major=confirm('Major landmark?\n\nOK = major (visible when zoomed out)\nCancel = minor');
  }
  draw(); refreshChrome();
}
function drawLabels(ctx){
  if(!W.labels.length) return;
  const z=W.view.zoom;
  // below this zoom only majors show, so a wall covered in hamlets still
  // reads as a continent when you pull back
  const MINOR_MIN_ZOOM = 0.55;
  ctx.save();
  ctx.textAlign='left'; ctx.textBaseline='middle';
  for(const L of W.labels){
    if(!L.major && z < MINOR_MIN_ZOOM) continue;
    const x=t2sx(L.x), y=t2sy(L.y);
    if(x<-160||y<-40||x>ctx.canvas.width+160||y>ctx.canvas.height+40) continue;
    const h = L.major ? 15 : 11;
    // flagpole
    ctx.strokeStyle='rgba(20,14,8,.85)'; ctx.lineWidth=1.6;
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x, y-h*1.7); ctx.stroke();
    // pennant
    ctx.fillStyle = L.major ? '#d9a441' : '#e8e0cc';
    ctx.strokeStyle='rgba(20,14,8,.85)'; ctx.lineWidth=1;
    ctx.beginPath();
    ctx.moveTo(x, y-h*1.7); ctx.lineTo(x+h*1.15, y-h*1.7+h*0.42);
    ctx.lineTo(x, y-h*1.7+h*0.84); ctx.closePath();
    ctx.fill(); ctx.stroke();
    // text once we're close enough for it to be legible
    if(z>=0.9 || L.major){
      const fs = L.major ? 13 : 11.5;
      ctx.font = (L.major?'700 ':'')+fs+'px "Iowan Old Style",Palatino,Georgia,serif';
      const tw=ctx.measureText(L.text).width;
      ctx.fillStyle='rgba(20,15,8,.62)';
      ctx.fillRect(x+h*1.5, y-h*1.7-2, tw+10, fs+7);
      ctx.fillStyle='#f6efdc';
      ctx.fillText(L.text, x+h*1.5+5, y-h*1.7+fs/2+1.5);
    }
  }
  ctx.restore();
}
function toggleRaw(){ W.showRaw=!W.showRaw; draw(); refreshChrome(); }

function addRegion(worldName){
  if(!worldName) return;
  pushUndo('add region');
  // drop it at the centre of the current view, snapped
  const cv=canvas();
  const sz=worldSize(worldName);
  let x=Math.round(s2tx(cv.width/2)-sz.w/2), y=Math.round(s2ty(cv.height/2)-sz.h/2);
  const g=W.snap||1; x=Math.round(x/g)*g; y=Math.round(y/g)*g;
  W.continent.placements.push({world:worldName, x:x, y:y});
  W.selected=W.continent.placements.length-1; W.selectedOcean=null;
  setTool('move');
  draw(); refreshChrome();
  toast('Placed '+worldName+'. Drag to position it.');
}
function removeSelected(){
  if(W.selected!=null){
    pushUndo('remove region');
    W.continent.placements.splice(W.selected,1);
    W.selected=null; draw(); refreshChrome();
    return;
  }
  if(W.selectedOcean!=null){
    pushUndo('remove ocean');
    W.continent.oceans.splice(W.selectedOcean,1);
    W.oceanCache.clear();
    W.selectedOcean=null; draw(); refreshChrome();
  }
}

function addOcean(){
  pushUndo('add ocean');
  const cv=canvas();
  const size=257;
  let x=Math.round(s2tx(cv.width/2)-size/2), y=Math.round(s2ty(cv.height/2)-size/2);
  const g=W.snap||1; x=Math.round(x/g)*g; y=Math.round(y/g)*g;
  W.continent.oceans.push({x:x,y:y,w:size,h:size,
                           seed:(Math.random()*1e9)|0, style:W.oceanStyle||'open'});
  draw(); refreshChrome();
  toast('Ocean added. Re-roll it for a different variant.');
}
function rerollOceans(){
  if(!W.continent.oceans.length){ toast('No ocean to re-roll yet.'); return; }
  pushUndo('re-roll ocean');
  for(const o of W.continent.oceans){
    o.seed=(Math.random()*1e9)|0;
    o.style=W.oceanStyle||o.style;
  }
  W.oceanCache.clear();
  draw();
  toast('Re-rolled '+W.continent.oceans.length+' ocean'+(W.continent.oceans.length===1?'':'s')+'.');
}
function clearOceans(){
  if(!W.continent.oceans.length) return;
  pushUndo('clear oceans');
  W.continent.oceans=[]; W.oceanCache.clear(); draw(); refreshChrome();
}

/* =========================================================================
   PERSISTENCE
   ========================================================================= */
function blankContinent(){
  return {id:null, name:'Untitled continent', placements:[], oceans:[], paint:{}, labels:[]};
}
function newContinent(){
  if(W.continent && (W.continent.placements.length||paintCount())){
    if(!confirm('Start a new continent? Unsaved changes to this one will be lost.')) return;
  }
  W.continent=blankContinent();
  W.labels=[];
  W.paintChunks.clear(); W.oceanCache.clear(); W.undo=[]; W.selected=null; W.selectedOcean=null;
  W.view={x:-40,y:-40,zoom:1.2};
  draw(); refreshChrome();
}
async function saveContinent(){
  const name=prompt('Name this continent:', W.continent.name||'Untitled continent');
  if(name==null) return;
  W.continent.name=name.trim()||'Untitled continent';
  const body={
    id:W.continent.id, name:W.continent.name,
    placements:W.continent.placements, oceans:W.continent.oceans,
    paint:paintToFlat(), labels:W.labels,
  };
  try{
    const r=await fetch(API+'/continents',{method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    if(!r.ok) throw new Error(await r.text());
    const doc=await r.json();
    W.continent.id=doc.id;
    toast('Saved "'+doc.name+'".');
    refreshChrome();
  }catch(e){ toast('Save failed: '+e.message); }
}
async function loadContinent(id){
  if(!id) return;
  try{
    const r=await fetch(API+'/continents/'+id);
    if(!r.ok) throw new Error('not found');
    const doc=await r.json();
    W.continent={id:doc.id, name:doc.name, placements:doc.placements||[],
                 oceans:doc.oceans||[], paint:{}, labels:doc.labels||[]};
    W.labels=doc.labels||[];
    paintFromFlat(doc.paint||{});
    W.oceanCache.clear(); W.undo=[]; W.selected=null; W.selectedOcean=null;
    draw(); fitAll(); refreshChrome();
    toast('Loaded "'+doc.name+'".');
  }catch(e){ toast('Load failed: '+e.message); }
}
async function deleteContinent(){
  if(!W.continent.id){ toast('This continent has never been saved.'); return; }
  if(!confirm('Delete "'+W.continent.name+'" permanently? The regions themselves are untouched.')) return;
  await fetch(API+'/continents/'+W.continent.id,{method:'DELETE'});
  newContinent();
  await refreshContinentList();
  toast('Deleted.');
}
async function refreshContinentList(){
  try{
    const r=await fetch(API+'/continents');
    const d=await r.json();
    W.savedList=d.continents||[];
  }catch(e){ W.savedList=[]; }
  refreshChrome();
}

/* =========================================================================
   EXPORT. One giant PNG at full native tile resolution
   ========================================================================= */
async function exportPNG(){
  const b=wallBounds();
  if(!b){ toast('Nothing on the wall to export yet.'); return; }
  // export at the detailed render's own scale where available (~6px/tile),
  // capped so a huge wall can still fit in a canvas the browser will allocate
  const MAXPX=14000;
  let scale=6;
  while((b.w*scale>MAXPX || b.h*scale>MAXPX) && scale>1) scale-=1;
  const cw=Math.round(b.w*scale), chh=Math.round(b.h*scale);
  toast('Rendering '+cw+'x'+chh+' image…');
  await new Promise(r=>setTimeout(r,30));
  const c=document.createElement('canvas'); c.width=cw; c.height=chh;
  const ctx=c.getContext('2d');
  ctx.imageSmoothingEnabled=false;
  ctx.fillStyle='#0d1826'; ctx.fillRect(0,0,cw,chh);
  for(const o of W.continent.oceans){
    ctx.drawImage(oceanCanvas(o), (o.x-b.x)*scale, (o.y-b.y)*scale, o.w*scale, o.h*scale);
  }
  // make sure every placed region has its detailed art before we rasterise
  const waits=[];
  for(const p of W.continent.placements){
    const rec=getImages(p.world);
    if(!rec.hi && !rec.hiTried){
      requestDetail(p.world);
      waits.push(new Promise(res=>{
        const t0=Date.now();
        (function poll(){
          if(rec.hi || Date.now()-t0>15000) return res();
          setTimeout(poll,150);
        })();
      }));
    }
  }
  if(waits.length){ toast('Fetching detailed maps for '+waits.length+' region(s)…'); await Promise.all(waits); }
  for(const p of W.continent.placements){
    const rec=getImages(p.world), sz=worldSize(p.world);
    const img=rec.hi||rec.lo;
    if(img && img.complete && img.naturalWidth)
      ctx.drawImage(img, (p.x-b.x)*scale, (p.y-b.y)*scale, sz.w*scale, sz.h*scale);
  }
  if(!W.showRaw){
    for(const ch of W.paintChunks.values()){
      for(const [k,bi] of ch){
        const i=k.indexOf(','), x=+k.slice(0,i), y=+k.slice(i+1);
        const col=paintColor(bi); if(!col) continue;
        ctx.fillStyle=col;
        ctx.fillRect((x-b.x)*scale, (y-b.y)*scale, scale, scale);
      }
    }
  }
  c.toBlob(blob=>{
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download=(W.continent.name||'continent').replace(/[^a-z0-9]+/gi,'_')+'.png';
    a.click();
    setTimeout(()=>URL.revokeObjectURL(a.href), 4000);
    toast('Exported '+cw+'x'+chh+' PNG.');
  },'image/png');
}

function setOceanStyle(s){ W.oceanStyle=s; refreshChrome(); }
function setSnap(n){ W.snap=n; refreshChrome(); }

/* =========================================================================
   MOUNT
   ========================================================================= */
async function mount(){
  if(!canvas()) return;
  W.mounted=true;
  if(!W.continent) W.continent=blankContinent();
  // palette + world list are needed before anything can render meaningfully
  if(!W.palette.length){
    try{ W.palette=(await (await fetch(API+'/palette')).json()).palette; }catch(e){ W.palette=[]; }
  }
  if(!W.worlds.length){
    try{ W.worlds=(await (await fetch(API+'/worlds')).json()).worlds; }catch(e){ W.worlds=[]; }
  }
  if(W.palette.length && !W.shades.length) buildShades();
  if(W.palette.length && !W.magicFamily) W.magicFamily = W.palette[0].name;
  W.snap = W.snap || 257;
  W.oceanStyle = W.oceanStyle || 'open';
  wire();
  resize();
  if(!_resizeH){ _resizeH=()=>{ if(W.mounted) resize(); }; window.addEventListener('resize',_resizeH); }
  await refreshContinentList();
  refreshChrome();
  draw();
}
function unmount(){ W.mounted=false; }

/* Rebuild the toolbar. Kept as one render so state can never drift between
   the palette swatches, the tool buttons and the counters. */
function refreshChrome(){
  const el=document.getElementById('wallChrome');
  if(!el || !W.continent) return;
  const sw=(c,label)=>`<button class="wsw${W.color===c?' on':''}" style="background:${c}"
       title="${label}" onclick="WallView.setColor('${c}')"></button>`;
  const pal = W.showShades
    ? W.shades.map(sh=>`<div class="wramp"><span class="wrampn">${sh.name}</span>
        <div class="wrampr">${sh.steps.map(c=>sw(c,sh.name)).join('')}</div></div>`).join('')
    : `<div class="wpal">${W.palette.map(p=>sw(p.hex,p.name)).join('')}</div>`;
  const styles=OCEAN_STYLE_ORDER.map(k=>
    `<option value="${k}"${W.oceanStyle===k?' selected':''}>${OCEAN_STYLES[k].label}</option>`).join('');
  const worlds=(W.worlds||[]).map(w=>
    `<option value="${w.name}">${w.world_name||w.name} (${w.width||257}t)</option>`).join('');
  const saved=(W.savedList||[]).map(c=>
    `<option value="${c.id}"${W.continent.id===c.id?' selected':''}>${c.name}, ${c.regions} regions</option>`).join('');
  const b=wallBounds();
  el.innerHTML=`
   <div class="wsec">
     <div class="wlab">Continent</div>
     <select onchange="WallView.loadContinent(this.value)">
       <option value="">Saved continents</option>${saved}</select>
     <div class="wrow">
       <button onclick="WallView.saveContinent()">Save</button>
       <button onclick="WallView.newContinent()">New</button>
       <button onclick="WallView.deleteContinent()">Delete</button>
     </div>
     <div class="whint">${W.continent.name}${W.continent.id?'':' (unsaved)'}</div>
   </div>
   <div class="wsec">
     <div class="wlab">Add a region</div>
     <select id="wallAddSel">${worlds||'<option>no worlds imported</option>'}</select>
     <div class="wrow">
       <button onclick="WallView.addRegion(document.getElementById('wallAddSel').value)">Place</button>
       <button onclick="WallView.removeSelected()" ${(W.selected==null&&W.selectedOcean==null)?'disabled':''}>Remove</button>
     </div>
     <div class="wrow"><label class="wsnap">Snap
       <select onchange="WallView.setSnap(+this.value)">
         <option value="1"${W.snap===1?' selected':''}>off</option>
         <option value="17"${W.snap===17?' selected':''}>pocket (17)</option>
         <option value="65"${W.snap===65?' selected':''}>small (65)</option>
         <option value="129"${W.snap===129?' selected':''}>medium (129)</option>
         <option value="257"${W.snap===257?' selected':''}>large (257)</option>
       </select></label></div>
     <div class="whint">Hold Alt while dragging to ignore snap.</div>
   </div>
   <div class="wsec">
     <div class="wlab">Tools</div>
     <div class="wrow wtools">
       <button class="${W.tool==='pan'?'on':''}" onclick="WallView.setTool('pan')" title="Pan / read a label"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18M3 12h18M12 3l-2.6 2.6M12 3l2.6 2.6M12 21l-2.6-2.6M12 21l2.6-2.6M3 12l2.6-2.6M3 12l2.6 2.6M21 12l-2.6-2.6M21 12l-2.6 2.6"/></svg></button>
       <button class="${W.tool==='move'?'on':''}" onclick="WallView.setTool('move')" title="Move regions / seas">⬚</button>
       <button class="${W.tool==='paint'?'on':''}" onclick="WallView.setTool('paint')" title="Paint">🖌</button>
       <button class="${W.tool==='magic'?'on':''}" onclick="WallView.setTool('magic')" title="Magic brush. Auto-blends shades from one biome family as you paint">✨</button>
       <button class="${W.tool==='erase'?'on':''}" onclick="WallView.setTool('erase')" title="Erase paint">⌫</button>
       <button class="${W.tool==='pick'?'on':''}" onclick="WallView.setTool('pick')" title="Eyedropper. Sample any colour on the map, including a region's own">💧</button>
       <button class="${W.tool==='label'?'on':''}" onclick="WallView.setTool('label')" title="Place a label">⚑</button>
     </div>
     <div class="wrow">Brush
       ${[1,3,5].map(n=>`<button class="${W.brush===n?'on':''}" onclick="WallView.setBrush(${n})">${n}</button>`).join('')}
       <span class="wcur" style="background:${W.color}" title="Current colour: ${W.color}"></span>
     </div>
     ${W.tool==='magic' ? `
     <div class="wlab" style="margin-top:8px">Magic brush. Biome family</div>
     <div class="wrow wpal">${(W.palette||[]).map(p=>{
        const fam=W.shades.find(s=>s.name===p.name);
        const preview=fam?fam.steps[2]:p.hex;
        return `<button class="wsw${W.magicFamily===p.name?' on':''}" style="background:${preview}"
          title="${esc(p.name)}" onclick="WallView.setMagicFamily('${p.name}')"></button>`;
     }).join('')}</div>
     <div class="wrow"><button onclick="WallView.rerollMagic()">Re-roll blend</button></div>
     <div class="whint">Pick a family above, then paint. "Re-roll blend" reshuffles the mix.</div>` : `
     ${pal}
     <div class="wrow"><button onclick="WallView.toggleShades()">${W.showShades?'Fewer colours':'More shades…'}</button></div>`}
   </div>
   <div class="wsec">
     <div class="wlab">Ocean</div>
     <select onchange="WallView.setOceanStyle(this.value)">${styles}</select>
     <div class="wrow">
       <button onclick="WallView.addOcean()">Add sea</button>
       <button onclick="WallView.rerollOceans()">Re-roll</button>
       <button onclick="WallView.clearOceans()">Clear</button>
     </div>
   </div>
   <div class="wsec">
     <div class="wrow">
       <button onclick="WallView.fitAll()">Fit all</button>
       <button onclick="WallView.doUndo()" ${W.undo.length?'':'disabled'}>Undo (${W.undo.length})</button>
     </div>
     <div class="wrow">
       <label class="wsnap"><input type="checkbox" ${W.showRaw?'checked':''} onchange="WallView.toggleRaw()"> Raw maps</label>
     </div>
     <div class="wrow"><button onclick="WallView.exportPNG()">Export PNG</button></div>
     <div class="whint">${W.continent.placements.length} regions · ${W.continent.oceans.length} seas · ${paintCount()} painted · ${(W.labels||[]).length} labels${b?` · ${b.w}×${b.h} tiles`:''}</div>
   </div>`;
}

window.WallView = {
  _W: W,
  resize: resize, zoomBy: zoomBy, fitAll: fitAll, wallBounds: wallBounds,
  setTool: setTool, setBrush: setBrush, setColor: setColor, toggleRaw: toggleRaw,
  toggleShades: toggleShades, buildShades: buildShades, pickColorAt: pickColorAt,
  setMagicFamily: setMagicFamily, rerollMagic: rerollMagic, magicColorAt: magicColorAt,
  addLabelAt: addLabelAt, editLabel: editLabel, hitLabel: hitLabel, drawLabels: drawLabels,
  paintColor: paintColor,
  addRegion: addRegion, removeSelected: removeSelected,
  addOcean: addOcean, rerollOceans: rerollOceans, clearOceans: clearOceans,
  wire: wire, hitPlacement: hitPlacement, applyBrush: applyBrush,
  mount: mount, unmount: unmount, refreshChrome: refreshChrome,
  saveContinent: saveContinent, loadContinent: loadContinent,
  newContinent: newContinent, deleteContinent: deleteContinent,
  exportPNG: exportPNG, setOceanStyle: setOceanStyle, setSnap: setSnap,
  draw: draw,
  paintGet: paintGet, paintSet: paintSet,
  paintToFlat: paintToFlat, paintFromFlat: paintFromFlat, paintCount: paintCount,
  pushUndo: pushUndo, doUndo: doUndo,
  oceanCanvas: oceanCanvas, buildOceanCanvas: buildOceanCanvas,
  OCEAN_STYLES: OCEAN_STYLES, OCEAN_STYLE_ORDER: OCEAN_STYLE_ORDER,
  worldSize: worldSize, getImages: getImages,
  t2sx:t2sx, t2sy:t2sy, s2tx:s2tx, s2ty:s2ty,
  makeNoise: makeNoise, depthColor: depthColor,
};

})();
