/* =========================================================================
   globe.js  --  the 3D globe, as an ES module inside DwarfWiki
   =========================================================================
   Separate from map.js because the vendored Three.js build is ES-module-only
   (no UMD/global build ships anymore), and module scripts don't share scope
   with classic ones. The two halves talk over a small, explicit window
   contract rather than by leaking globals:

     map.js  publishes -> window.MapState, window.MapAPI, window.api,
                          window.apiPost
     this    publishes -> planetRadiusKm, defaultPlanetRadiusKm,
                          METERS_PER_TILE, REFERENCE_TILES,
                          stitchGridToTexture, init3dGlobeIfNeeded,
                          refresh3dGlobeTexture, toggleGlobeSpin,
                          noteGlobeInteraction
   ========================================================================= */

/* ============================================================
   3D GLOBE. Separate <script type="module"> block because the
   vendored Three.js build is ES-module-only (no legacy UMD/global
   build ships anymore). This block does not share scope with the
   classic script above; STATE/API/api() were explicitly exposed
   on window for that reason. See the top of the main script.
   ============================================================ */
import * as THREE from '/vendor/three.module.min.js';

let scene, camera, renderer, sphere, canvasTexture, stitchCanvas, stitchCtx;
let inited=false, isDragging=false, lastPX=0, lastPY=0, rotY=0, rotX=0, camDist=3;
let _globeCanvasEl=null, _animRunning=false;
const imgCache={};

function loadImageCached(src){
  if(!imgCache[src]){
    imgCache[src]=new Promise((resolve)=>{
      const img=new Image();
      img.onload=()=>resolve(img);
      img.onerror=()=>resolve(null);   // a missing/broken map shouldn't kill the whole stitch
      img.src=src;
    });
  }
  return imgCache[src];
}

/* Prepare a region's map.png for the globe: key its OCEAN out to transparency
   so the sphere's own bathymetry shows through seamlessly, and feather the
   outer rectangular edge. Together these kill the three globe artifacts:
     - washed-out squares (the map's ocean was drawing as opaque flat blue
       over the sphere's ocean. Now it's genuinely transparent)
     - hard rectangular cutoffs (the straight map border was a blue cliff.
       Now the border is ocean, which is transparent, so there is no cliff)
     - only real land ends up painted onto the planet.
   The flat Map view is untouched and stays pixel-exact; this transform only
   runs for the 3D globe. */
const _featherCache={};
function isOceanPixel(r,g,b){
  // DF ocean/lake tiles render in a fairly tight blue band: blue clearly
  // dominant, red low. This keys those out without touching green land,
  // brown mountains, or white ice.
  return b>90 && b>r+28 && b>g+10 && r<110;
}
function featherToCanvas(img, w, h, featherFrac){
  w=Math.max(2,Math.round(w)); h=Math.max(2,Math.round(h));
  const key=img.src+'|'+w+'x'+h+'|'+featherFrac;
  if(_featherCache[key]) return _featherCache[key];
  const c=document.createElement('canvas'); c.width=w; c.height=h;
  const cx=c.getContext('2d');
  cx.drawImage(img,0,0,w,h);
  const fx=Math.max(1,Math.floor(w*featherFrac)), fy=Math.max(1,Math.floor(h*featherFrac));
  const id=cx.getImageData(0,0,w,h), d=id.data;
  for(let y=0;y<h;y++){
    const dy=Math.min(y,h-1-y);
    const ay=dy<fy ? dy/fy : 1;
    for(let x=0;x<w;x++){
      const i=(y*w+x)*4;
      // ocean -> fully transparent, so the sphere's sea shows through and there
      // is no flat-blue rectangle to look washed out or to end in a hard edge
      if(isOceanPixel(d[i],d[i+1],d[i+2])){ d[i+3]=0; continue; }
      const dx=Math.min(x,w-1-x);
      const ax=dx<fx ? dx/fx : 1;
      let a=Math.min(ax,ay);
      if(a<1){
        a=a*a*(3-2*a);                     // smoothstep edge feather (for land that runs to the map border)
        d[i+3]=Math.round(d[i+3]*a);
      }
    }
  }
  cx.putImageData(id,0,0);
  _featherCache[key]=c;
  return c;
}

async function drawCellInto(ctx, cell, px, py, w, h){
  if(!cell || cell.type==='empty') return;               // bare ocean shows through
  if(cell.type==='blank_ocean'){
    return;   // procedural bathymetry (painted first) already shows through here
  }
  if(cell.type==='world'){
    const img=await loadImageCached(window.MapAPI+'/w/'+cell.world+'/map.png');
    if(!img) return;
    // size by the world's REAL tile count relative to a Large region, and
    // centre it in its slot. A pocket region occupies a sliver of its slot
    // instead of being stretched to fill it
    const t=worldTileSize(cell.world);
    const sw=w*(t.w/REFERENCE_TILES), sh=h*(t.h/REFERENCE_TILES);
    // don't let a pocket region vanish entirely at small planet scales
    const dw=Math.max(6,sw), dh=Math.max(6,sh);
    const dx=px+(w-dw)/2, dy=py+(h-dh)/2;
    ctx.drawImage(featherToCanvas(img, dw, dh, 0.13), dx, dy, dw, dh);
    return;
  }
  if(cell.type==='subdivided'){
    const cols=cell.cols||2, rows=cell.rows||2;
    const subW=w/cols, subH=h/rows;
    const letters='abcdefghijklmnopqrstuvwxyz';
    const jobs=[];
    for(let i=0;i<rows*cols;i++){
      const letter=letters[i];
      const child=(cell.children||{})[letter];
      const cx=px+(i%cols)*subW, cy=py+Math.floor(i/cols)*subH;
      jobs.push(drawCellInto(ctx, child, cx, cy, subW, subH));
    }
    await Promise.all(jobs);
  }
}

/* ---- procedural deep-sea bathymetry (cheap value-noise, generated small
   then smooth-upscaled. Ocean floor doesn't need pixel-perfect detail,
   the blur is exactly the right look anyway) ---- */
function _hash2(x,y){ const s=Math.sin(x*127.1+y*311.7)*43758.5453; return s-Math.floor(s); }
function _valueNoise(x,y){
  const xi=Math.floor(x), yi=Math.floor(y), xf=x-xi, yf=y-yi;
  const a=_hash2(xi,yi), b=_hash2(xi+1,yi), c=_hash2(xi,yi+1), d=_hash2(xi+1,yi+1);
  const u=xf*xf*(3-2*xf), v=yf*yf*(3-2*yf);
  return a*(1-u)*(1-v)+b*u*(1-v)+c*(1-u)*v+d*u*v;
}
function drawBathymetry(ctx,W,H){
  const sw=256, sh=128;
  const small=document.createElement('canvas'); small.width=sw; small.height=sh;
  const sctx=small.getContext('2d');
  const img=sctx.createImageData(sw,sh);
  for(let y=0;y<sh;y++){
    for(let x=0;x<sw;x++){
      const n=_valueNoise(x*0.08,y*0.08)*0.6+_valueNoise(x*0.22,y*0.22)*0.4;
      const depth=14+n*50;   // mid-ocean ridges (lighter) vs trenches (darker)
      const idx=(y*sw+x)*4;
      img.data[idx]=6+depth*0.25; img.data[idx+1]=24+depth*0.65; img.data[idx+2]=46+depth*1.05; img.data[idx+3]=255;
    }
  }
  sctx.putImageData(img,0,0);
  ctx.imageSmoothingEnabled=true; ctx.imageSmoothingQuality='high';
  ctx.drawImage(small,0,0,W,H);
}

/* ---- polar ice caps. Alpha-blended over whatever's beneath (ocean or
   land), which is exactly what makes them "blend into the coastline" ---- */
function drawPolarCaps(ctx,W,H){
  const capH=H*0.15;
  let grad=ctx.createLinearGradient(0,0,0,capH);
  grad.addColorStop(0,'rgba(238,245,250,0.95)'); grad.addColorStop(0.65,'rgba(238,245,250,0.5)'); grad.addColorStop(1,'rgba(238,245,250,0)');
  ctx.fillStyle=grad; ctx.fillRect(0,0,W,capH);
  grad=ctx.createLinearGradient(0,H-capH,0,H);
  grad.addColorStop(0,'rgba(238,245,250,0)'); grad.addColorStop(0.35,'rgba(238,245,250,0.5)'); grad.addColorStop(1,'rgba(238,245,250,0.95)');
  ctx.fillStyle=grad; ctx.fillRect(0,H-capH,W,capH);
}

/* ---- lat/lon <-> texture pixel / sphere-space math. Verified with a
   round-trip test before use (forward->inverse reproduces input to well
   under 0.01 degrees across pole-adjacent and antimeridian cases), this
   is the one piece of math in the whole feature that's hard to eyeball-
   verify without a real WebGL context, so it got extra scrutiny. Both the
   texture-pixel mapping and the sphere-space mapping are derived from the
   SAME phi/theta definitions Three.js's own SphereGeometry uses
   internally, so markers stay aligned with their texture content even if
   there's some absolute rotation offset. ---- */
const TEX_W=2048, TEX_H=1024;
function latLonToPx(lat,lon){ return [(lon+180)/360*TEX_W, (90-lat)/180*TEX_H]; }
function latLonToXYZ(lat,lon,radius){
  const phi=(lon+180)*Math.PI/180, theta=(90-lat)*Math.PI/180;
  return { x:-radius*Math.cos(phi)*Math.sin(theta), y:radius*Math.cos(theta), z:radius*Math.sin(phi)*Math.sin(theta) };
}
function xyzToLatLon(p){
  const r=Math.sqrt(p.x*p.x+p.y*p.y+p.z*p.z);
  const theta=Math.acos(Math.max(-1,Math.min(1,p.y/r)));
  let phi=Math.atan2(p.z,-p.x); if(phi<0) phi+=2*Math.PI;
  return { lat:90-theta*180/Math.PI, lon:phi*180/Math.PI-180 };
}

/* ============================================================
   REAL-WORLD SCALE
   A DF overworld tile is ~1873m across, so a region's true size
   is just (tiles x 1873m): Large 257 -> 481km, Medium 129 ->
   242km, Small 65 -> 122km, Pocket 17 -> 32km. Regions are now
   drawn at their TRUE size relative to each other instead of
   every world being stretched to fill an identical grid cell,
   which is what made pocket/small coastal regions look absurd.

   PLANET_RADIUS_KM sets the absolute scale. The default puts a
   Large region at roughly 10 degrees of arc, which keeps a
   typical medium+large layout readable; the layout panel has a
   slider if you want a bigger or smaller planet.
   ============================================================ */
const METERS_PER_TILE = 1873;
const REFERENCE_TILES = 257;        // a Large region. The layout grid's unit cell
/* Default planet size: whatever makes the layout grid wrap the sphere exactly,
   i.e. one grid column == one Large region of longitude. For the standard 8x4
   grid that's a ~613km-radius world where a Large region spans 45 degrees and
   lands at 256px on the 2048px texture. Essentially 1:1 with the 257px source
   map, so nothing is thrown away. This is the "30-odd large regions ARE the
   whole world" scale, not "a fraction of an Earth". */
function defaultPlanetRadiusKm(g){
  const cols=(g && g.cols) || 8;
  const circumferenceKm = cols * REFERENCE_TILES * METERS_PER_TILE / 1000;
  return circumferenceKm / (2*Math.PI);
}
function planetRadiusKm(){
  const g = window.MapState.globe || {};
  return g.planet_radius_km || defaultPlanetRadiusKm(g);
}
/* the layout panel's planet slider lives in the main (non-module) script
   block, which can't reach into module scope. Export what it needs */
window.defaultPlanetRadiusKm = defaultPlanetRadiusKm;
window.planetRadiusKm = planetRadiusKm;
window.METERS_PER_TILE = METERS_PER_TILE;
window.REFERENCE_TILES = REFERENCE_TILES;
function regionSpanFrac(tiles){
  // fraction of the full 360-degree texture width this many tiles covers
  const km = (tiles * METERS_PER_TILE) / 1000;
  return km / (2 * Math.PI * planetRadiusKm());
}
function worldTileSize(worldName){
  const w = (window.MapState.worlds || []).find(function(x){ return x.name === worldName; });
  if (w && w.width) return { w: w.width, h: w.height || w.width };
  return { w: REFERENCE_TILES, h: REFERENCE_TILES };   // unknown world: assume Large
}

/**
 * stitchGridToTexture(). Paints procedural bathymetry first (the "vast
 * ocean" backdrop), then draws each continent's cluster of grid cells
 * around that continent's lat/lon anchor. Two things changed here:
 *
 *  1. Every world is sized by its REAL tile count rather than stretched to
 *     fill its grid slot, so a pocket island reads as a speck next to a
 *     large region instead of matching it.
 *  2. Cells with no continent tag now join the continent of an adjacent
 *     grid neighbour instead of being left behind at their raw grid
 *     longitude. That was the actual reason a subdivided coastal cluster
 *     "didn't render". It wasn't missing, it was stranded on the far side
 *     of the globe while the cells it was drawn next to on the layout grid
 *     had all moved to the continent anchor.
 */
async function stitchGridToTexture(){
  const g = window.MapState.globe || await window.api('/globe');
  window.MapState.globe = g;
  if(stitchCanvas.width!==TEX_W || stitchCanvas.height!==TEX_H){ stitchCanvas.width=TEX_W; stitchCanvas.height=TEX_H; }
  const ctx=stitchCtx;
  drawBathymetry(ctx, TEX_W, TEX_H);

  const total=g.rows*g.cols;
  const contOf={};                       // slot -> continent id (explicit or inherited)
  const occupied=[];
  for(let slot=1; slot<=total; slot++){
    const cell=g.grid[slot];
    if(!cell || cell.type==='empty') continue;
    occupied.push(slot);
    if(cell.continent) contOf[slot]=String(cell.continent);
  }
  // flood untagged cells outward from tagged ones across grid adjacency, so a
  // cluster you drew touching your continent travels with it
  for(let pass=0; pass<total; pass++){
    let changed=false;
    for(const slot of occupied){
      if(contOf[slot]) continue;
      const row=Math.floor((slot-1)/g.cols), col=(slot-1)%g.cols;
      const nbrs=[[row-1,col],[row+1,col],[row,col-1],[row,col+1]];
      for(const nb of nbrs){
        if(nb[0]<0||nb[1]<0||nb[0]>=g.rows||nb[1]>=g.cols) continue;
        const nslot=nb[0]*g.cols+nb[1]+1;
        if(contOf[nslot]){ contOf[slot]=contOf[nslot]; changed=true; break; }
      }
    }
    if(!changed) break;
  }

  const byContinent={}, loose=[];
  for(const slot of occupied){
    if(contOf[slot]) (byContinent[contOf[slot]]=byContinent[contOf[slot]]||[]).push(slot);
    else loose.push(slot);
  }

  // one grid slot == one REFERENCE_TILES-wide region on the planet
  const unitW = regionSpanFrac(REFERENCE_TILES) * TEX_W;
  const unitH = unitW;                    // square slots. Tiles are square
  const jobs=[];

  for(const cid in byContinent){
    const slots=byContinent[cid];
    const placement=(g.continents||{})[cid] || {lat:0,lon:0};
    let minCol=1e9,maxCol=-1,minRow=1e9,maxRow=-1;
    slots.forEach(function(slot){
      const row=Math.floor((slot-1)/g.cols), col=(slot-1)%g.cols;
      minCol=Math.min(minCol,col); maxCol=Math.max(maxCol,col);
      minRow=Math.min(minRow,row); maxRow=Math.max(maxRow,row);
    });
    const spanCols=maxCol-minCol+1, spanRows=maxRow-minRow+1;
    const center=latLonToPx(placement.lat||0, placement.lon||0);
    const blockX=center[0]-spanCols*unitW/2, blockY=center[1]-spanRows*unitH/2;
    slots.forEach(function(slot){
      const row=Math.floor((slot-1)/g.cols), col=(slot-1)%g.cols;
      const px=blockX+(col-minCol)*unitW, py=blockY+(row-minRow)*unitH;
      jobs.push(drawCellInto(ctx, g.grid[slot], px, py, unitW, unitH));
    });
  }
  // genuinely isolated cells (no continent anywhere in their group) keep their
  // raw grid position, just now at true scale
  for(const slot of loose){
    const row=Math.floor((slot-1)/g.cols), col=(slot-1)%g.cols;
    const cx=(col+0.5)*(TEX_W/g.cols)-unitW/2, cy=(row+0.5)*(TEX_H/g.rows)-unitH/2;
    jobs.push(drawCellInto(ctx, g.grid[slot], cx, cy, unitW, unitH));
  }

  await Promise.all(jobs);
  drawPolarCaps(ctx, TEX_W, TEX_H);
  if(canvasTexture) canvasTexture.needsUpdate=true;
  rebuildContinentMarkers();
}
window.stitchGridToTexture=stitchGridToTexture;

/* ---- continent markers: small colored dots at each continent's anchor,
   draggable to reposition (raycast-picked). Highest priority interaction,
   checked before falling back to globe rotation on mousedown. ---- */
let continentMarkers=[], raycaster=null, draggingContinent=null, dragThrottle=0;
function rebuildContinentMarkers(){
  if(!scene || !sphere) return;
  continentMarkers.forEach(function(m){ sphere.remove(m.mesh); });
  continentMarkers=[];
  const g=window.MapState.globe;
  if(!g || !g.continents) return;
  for(const cid in g.continents){
    const c=g.continents[cid];
    const pos=latLonToXYZ(c.lat||0, c.lon||0, 1.46);
    const geo=new THREE.SphereGeometry(0.045, 14, 14);
    const mat=new THREE.MeshBasicMaterial({color: c.color||'#ffffff'});
    const mesh=new THREE.Mesh(geo, mat);
    mesh.position.set(pos.x,pos.y,pos.z);
    sphere.add(mesh);   // parented to the sphere -> inherits its rotation for free, no per-frame repositioning needed
    continentMarkers.push({cid:cid, mesh:mesh});
  }
}
function pickContinentMarker(clientX, clientY, canvas){
  if(!raycaster) raycaster=new THREE.Raycaster();
  const rect=canvas.getBoundingClientRect();
  const ndc=new THREE.Vector2(((clientX-rect.left)/rect.width)*2-1, -((clientY-rect.top)/rect.height)*2+1);
  raycaster.setFromCamera(ndc, camera);
  const hits=raycaster.intersectObjects(continentMarkers.map(function(m){return m.mesh;}));
  if(hits.length) return continentMarkers.find(function(m){return m.mesh===hits[0].object;});
  return null;
}
function sphereHitLatLon(clientX, clientY, canvas){
  if(!raycaster) raycaster=new THREE.Raycaster();
  const rect=canvas.getBoundingClientRect();
  const ndc=new THREE.Vector2(((clientX-rect.left)/rect.width)*2-1, -((clientY-rect.top)/rect.height)*2+1);
  raycaster.setFromCamera(ndc, camera);
  const hits=raycaster.intersectObject(sphere);
  if(!hits.length) return null;
  const local=sphere.worldToLocal(hits[0].point.clone());
  return xyzToLatLon(local);
}

async function init3dGlobeIfNeeded(){
  const canvas=document.getElementById('globe3dCanvas');
  if(!canvas) return;
  // As a standalone page the globe was built once and lived forever. Inside
  // DwarfWiki the router destroys and rebuilds the view on every navigation,
  // so the canvas we initialised against can be a detached node by the time
  // you come back. The renderer keeps drawing correctly into an element
  // that is no longer in the document, which looks exactly like a black,
  // empty globe. Rebuild whenever the canvas is a different element.
  if(inited && _globeCanvasEl===canvas) return;
  if(renderer){ try{ renderer.dispose(); }catch(e){} renderer=null; }
  _globeCanvasEl=canvas;
  inited=true;

  renderer=new THREE.WebGLRenderer({canvas, antialias:true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1, 2));

  scene=new THREE.Scene();
  camera=new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.z=camDist;

  stitchCanvas=document.createElement('canvas');
  stitchCanvas.width=TEX_W; stitchCanvas.height=TEX_H;
  stitchCtx=stitchCanvas.getContext('2d');
  drawBathymetry(stitchCtx, TEX_W, TEX_H);

  canvasTexture=new THREE.CanvasTexture(stitchCanvas);
  if(THREE.SRGBColorSpace) canvasTexture.colorSpace=THREE.SRGBColorSpace;

  const geo=new THREE.SphereGeometry(1.4, 64, 48);
  const mat=new THREE.MeshBasicMaterial({map:canvasTexture});
  sphere=new THREE.Mesh(geo, mat);
  scene.add(sphere);

  wireDragControls(canvas);
  window.addEventListener('resize', resize3d);
  resize3d();
  // one loop only. Re-initialising must not stack a second rAF chain
  if(!_animRunning){ _animRunning=true; animate3d(); }
}

function resize3d(){
  const wrap=document.getElementById('view3d');
  if(!wrap || !renderer) return;
  const w=wrap.clientWidth||1, h=wrap.clientHeight||1;
  renderer.setSize(w, h, false);
  camera.aspect=w/h;
  camera.updateProjectionMatrix();
}

function wireDragControls(canvas){
  canvas.addEventListener('mousedown', function(e){
    const hit=pickContinentMarker(e.clientX, e.clientY, canvas);
    if(hit){ draggingContinent=hit; canvas.style.cursor='grabbing'; return; }
    isDragging=true; lastPX=e.clientX; lastPY=e.clientY; noteGlobeInteraction();
  });
  window.addEventListener('mouseup', function(){
    if(draggingContinent){
      const c=window.MapState.globe.continents[draggingContinent.cid];
      window.apiPost3d('/globe',{action:'place_continent', continent:parseInt(draggingContinent.cid), lat:c.lat, lon:c.lon, scale:c.scale});
      draggingContinent=null; canvas.style.cursor='';
    }
    isDragging=false; noteGlobeInteraction();
  });
  window.addEventListener('mousemove', function(e){
    if(draggingContinent){
      const ll=sphereHitLatLon(e.clientX, e.clientY, canvas);
      if(ll){
        const c=window.MapState.globe.continents[draggingContinent.cid];
        c.lat=Math.max(-80,Math.min(80,ll.lat)); c.lon=ll.lon;
        const pos=latLonToXYZ(c.lat,c.lon,1.46);
        draggingContinent.mesh.position.set(pos.x,pos.y,pos.z);
        const now=Date.now();
        if(now-dragThrottle>120){ dragThrottle=now; stitchGridToTexture(); }
      }
      return;
    }
    if(!isDragging) return;
    const dx=e.clientX-lastPX, dy=e.clientY-lastPY;
    rotY += dx*0.006;
    rotX = Math.max(-1.3, Math.min(1.3, rotX + dy*0.006));
    lastPX=e.clientX; lastPY=e.clientY; noteGlobeInteraction();
  });
  canvas.addEventListener('wheel', e=>{
    e.preventDefault();
    camDist=Math.max(1.8, Math.min(6, camDist + e.deltaY*0.0025)); noteGlobeInteraction();
  }, {passive:false});
  canvas.addEventListener('touchstart', e=>{ isDragging=true; lastPX=e.touches[0].clientX; lastPY=e.touches[0].clientY; noteGlobeInteraction(); }, {passive:true});
  window.addEventListener('touchend', ()=>{ isDragging=false; noteGlobeInteraction(); });
  window.addEventListener('touchmove', e=>{
    if(!isDragging || !e.touches.length) return;
    const dx=e.touches[0].clientX-lastPX, dy=e.touches[0].clientY-lastPY;
    rotY += dx*0.006;
    rotX = Math.max(-1.3, Math.min(1.3, rotX + dy*0.006));
    lastPX=e.touches[0].clientX; lastPY=e.touches[0].clientY; noteGlobeInteraction();
  }, {passive:true});
}

/* ---- idle auto-spin: waits SPIN_DELAY_MS after you stop interacting, then
   eases back up to speed over ~1.2s instead of snapping to full rate the
   instant the mouse is released, which felt like the globe was yanked. ---- */
const SPIN_DELAY_MS=6000, SPIN_RATE=0.0016, SPIN_RAMP_MS=1200;
let lastInteractAt=0, spinEnabled=true, spinVel=0;
function noteGlobeInteraction(){ lastInteractAt=Date.now(); spinVel=0; }
window.noteGlobeInteraction=noteGlobeInteraction;
function toggleGlobeSpin(){
  spinEnabled=!spinEnabled;
  if(spinEnabled) lastInteractAt=Date.now();   // resume respects the same delay
  else spinVel=0;
  const b=document.getElementById('spinToggle');
  if(b){ b.textContent = spinEnabled ? '⏸' : '▶'; b.title = spinEnabled ? 'Pause the idle spin' : 'Resume the idle spin'; }
}
window.toggleGlobeSpin=toggleGlobeSpin;

function animate3d(){
  requestAnimationFrame(animate3d);
  const wrap=document.getElementById('view3d');
  if(!wrap || wrap.style.display==='none') return;  // don't burn cycles while hidden
  if(!renderer || !sphere || !scene || !camera) return;   // view torn down mid-flight
  const idleFor=Date.now()-lastInteractAt;
  if(spinEnabled && !isDragging && !draggingContinent && idleFor>SPIN_DELAY_MS){
    const ramp=Math.min(1,(idleFor-SPIN_DELAY_MS)/SPIN_RAMP_MS);
    spinVel=SPIN_RATE*(ramp*ramp*(3-2*ramp));   // smoothstep ease-in
  }else{
    spinVel=0;
  }
  rotY += spinVel;
  sphere.rotation.y=rotY;
  sphere.rotation.x=rotX;
  camera.position.z=camDist;
  renderer.render(scene, camera);
}

/* A brand-new install has an empty layout grid, so the globe correctly
   renders an empty ocean, which reads as "broken" rather than "you haven't
   placed anything yet". Seed the grid with the world you're currently
   viewing so the globe is useful the first time you open it. Only ever fires
   when the grid is completely empty, so it can't disturb a layout you've
   actually arranged. */
async function ensureGlobeSeeded(world){
  if(!world) return false;
  let g = window.MapState && window.MapState.globe;
  if(!g){
    try{ g = await window.api('/globe'); }catch(e){ return false; }
    if(window.MapState) window.MapState.globe = g;
  }
  const occupied = Object.keys(g.grid||{}).filter(function(k){
    const c=g.grid[k]; return c && c.type && c.type!=='empty';
  });
  if(occupied.length) return false;
  const slot = Math.floor((g.rows||4)/2)*(g.cols||8) + Math.floor((g.cols||8)/2) + 1;
  try{
    await window.apiPost('/globe',{action:'set', path:[slot], cell:{type:'world', world:world}});
    await window.apiPost('/globe',{action:'set_continent', path:[slot], continent:1});
    await window.apiPost('/globe',{action:'place_continent', continent:1, lat:0, lon:0});
    window.MapState.globe = await window.api('/globe');
    return true;
  }catch(e){ return false; }
}

async function refresh3dGlobeTexture(world){
  await init3dGlobeIfNeeded();
  if(world) await ensureGlobeSeeded(world);
  await stitchGridToTexture();
  resize3d();
}

window.ensureGlobeSeeded=ensureGlobeSeeded;
window.init3dGlobeIfNeeded=init3dGlobeIfNeeded;
window.refresh3dGlobeTexture=refresh3dGlobeTexture;
window.apiPost3d=function(path,body){
  return fetch(window.MapAPI+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(function(r){return r.json();});
};
