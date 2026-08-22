/* =========================================================================
   vectorborders.js  --  turn a blocky tile grid into smooth curved outlines
   =========================================================================
   DF gives us territory as a raster: every 257x257 tile belongs to some civ
   or to nobody. Drawing that boundary directly produces the pixel staircase
   you see on a zoomed-in political map. What makes hand-drawn (and Azgaar's)
   maps read as organic is that their borders are *vectors*. Smooth curves
   that stay smooth at any zoom instead of getting blockier as you zoom in.

   Two standard, well-understood steps get us there:

     1. BOUNDARY EXTRACTION (marching-squares style edge walking)
        For every tile inside a region whose neighbour is outside it, emit the
        unit edge between them, as a *directed* segment. Because the winding
        is consistent, each segment's end point is exactly the next segment's
        start point, so the segments chain into closed loops with no fitting
        or guessing. Holes (a civ enclosing another) fall out naturally as
        their own loops.

     2. CHAIKIN CORNER CUTTING
        Repeatedly replace every corner with two points at 1/4 and 3/4 along
        its edges. Each pass halves the sharpness; 2-3 passes turn a staircase
        into something that reads as a drawn coastline. Chaikin converges to a
        quadratic B-spline, so it stays faithful to the original shape rather
        than wandering off it. Important here, because these borders are real
        data, not decoration.

   Everything works in TILE coordinates and is cached per layer. The renderer
   scales the finished paths to screen space, which is the whole point: the
   curve is resolution-independent, so it's crisp at any zoom instead of being
   baked into pixels.
   ========================================================================= */
(function(){
'use strict';

/**
 * Walk the boundary of a region and return closed loops of tile-space points.
 *
 * @param {function(number,number):boolean} inside - is tile (x,y) in the region
 * @param {number} W @param {number} H - grid dimensions
 * @param {Array<[number,number]>} cells - the tiles in this region (so we
 *        don't rescan the whole grid for every civ)
 * @returns {Array<Array<[number,number]>>} closed loops
 */
function traceRegion(inside, W, H, cells){
  // Directed unit edges, wound consistently so ends meet starts.
  // Keyed "x,y" -> list of end points, because a single lattice point can be
  // the corner of two diagonally-touching blobs.
  const edges = new Map();
  function addEdge(x1,y1,x2,y2){
    const k = x1+','+y1;
    let a = edges.get(k);
    if(!a){ a=[]; edges.set(k,a); }
    a.push([x2,y2]);
  }

  for(let i=0;i<cells.length;i++){
    const x=cells[i][0], y=cells[i][1];
    // clockwise winding in screen space (y down)
    if(!inside(x,   y-1)) addEdge(x,   y,   x+1, y  );  // top
    if(!inside(x+1, y  )) addEdge(x+1, y,   x+1, y+1);  // right
    if(!inside(x,   y+1)) addEdge(x+1, y+1, x,   y+1);  // bottom
    if(!inside(x-1, y  )) addEdge(x,   y+1, x,   y  );  // left
  }

  const loops=[];
  // walk chains until every edge is consumed
  for(const startKey of Array.from(edges.keys())){
    let bucket = edges.get(startKey);
    while(bucket && bucket.length){
      const loop=[];
      let cx = Number(startKey.split(',')[0]);
      let cy = Number(startKey.split(',')[1]);
      let guard = 0, maxSteps = W*H*4 + 16;
      while(guard++ < maxSteps){
        const k = cx+','+cy;
        const b = edges.get(k);
        if(!b || !b.length) break;         // chain ended
        const nxt = b.pop();
        if(!b.length) edges.delete(k);
        loop.push([cx,cy]);
        cx = nxt[0]; cy = nxt[1];
        if(cx===Number(startKey.split(',')[0]) && cy===Number(startKey.split(',')[1])) break;  // closed
      }
      if(loop.length>=4) loops.push(loop);
      bucket = edges.get(startKey);
    }
  }
  return loops;
}

/**
 * Chaikin corner cutting on a CLOSED loop. Each pass replaces every point
 * with two points at 1/4 and 3/4 along its outgoing edge.
 */
function chaikin(points, iterations){
  let pts = points;
  for(let it=0; it<iterations; it++){
    const n = pts.length;
    if(n < 3) return pts;
    const out = new Array(n*2);
    for(let i=0;i<n;i++){
      const p = pts[i], q = pts[(i+1)%n];
      out[i*2]   = [p[0]*0.75 + q[0]*0.25, p[1]*0.75 + q[1]*0.25];
      out[i*2+1] = [p[0]*0.25 + q[0]*0.75, p[1]*0.25 + q[1]*0.75];
    }
    pts = out;
  }
  return pts;
}

/**
 * Ramer-Douglas-Peucker on a closed loop.
 *
 * This is the step that actually kills the staircase, and it has to run
 * BEFORE Chaikin. A 45-degree grid boundary is a run of alternating unit
 * steps. Noise at 1-tile wavelength. Chaikin only cuts corners locally, so
 * on a staircase it just produces a *rounded* staircase (verified: point
 * count and area plateau while the steps stay visible). RDP instead asks
 * "which points actually define this shape?" and throws away everything
 * within `eps` of the line between them, collapsing a staircase into the
 * single straight diagonal it was always meant to be. Chaikin then rounds
 * what genuinely are corners.
 *
 * eps is in tiles: below ~1.0 the staircase survives, and much above ~2.5
 * real territorial detail starts getting eaten.
 */
function rdp(points, eps){
  const n=points.length;
  if(n<4) return points;
  // a closed loop has no natural endpoints; anchor on the two most distant
  // points so the split is stable rather than dependent on where the walk
  // happened to start
  let ai=0, bi=0, bestD=-1;
  for(let i=1;i<n;i++){
    const dx=points[i][0]-points[0][0], dy=points[i][1]-points[0][1];
    const d=dx*dx+dy*dy;
    if(d>bestD){ bestD=d; bi=i; }
  }
  const seg1=points.slice(ai,bi+1);
  const seg2=points.slice(bi).concat([points[0]]);
  const out=_rdpOpen(seg1,eps).concat(_rdpOpen(seg2,eps).slice(1,-1));
  return out.length>=4 ? out : points;
}

function _rdpOpen(pts, eps){
  if(pts.length<3) return pts;
  const a=pts[0], b=pts[pts.length-1];
  let idx=-1, maxD=-1;
  const dx=b[0]-a[0], dy=b[1]-a[1];
  const len=Math.hypot(dx,dy);
  for(let i=1;i<pts.length-1;i++){
    const p=pts[i];
    // perpendicular distance to the a-b line (or to a, if a==b)
    const d = len<1e-9
      ? Math.hypot(p[0]-a[0], p[1]-a[1])
      : Math.abs(dy*p[0] - dx*p[1] + b[0]*a[1] - b[1]*a[0]) / len;
    if(d>maxD){ maxD=d; idx=i; }
  }
  if(maxD>eps){
    const left=_rdpOpen(pts.slice(0,idx+1), eps);
    const right=_rdpOpen(pts.slice(idx), eps);
    return left.slice(0,-1).concat(right);
  }
  return [a,b];
}

/** Drop points closer together than `tol`. Chaikin quadruples the point
 *  count each pass, and at these scales most of that is redundant detail. */
function simplify(points, tol){
  if(points.length<8) return points;
  const t2 = tol*tol;
  const out=[points[0]];
  for(let i=1;i<points.length;i++){
    const p=out[out.length-1], q=points[i];
    const dx=q[0]-p[0], dy=q[1]-p[1];
    if(dx*dx+dy*dy >= t2) out.push(q);
  }
  return out.length>=4 ? out : points;
}

/**
 * Full pipeline for one region: raw grid cells -> smooth closed loops.
 * `minLoop` drops specks. A 3-tile island's outline is noise at map scale.
 */
function smoothRegion(inside, W, H, cells, opts){
  opts = opts||{};
  const iterations = opts.iterations!=null ? opts.iterations : 3;
  const minLoop    = opts.minLoop!=null ? opts.minLoop : 8;
  const tol        = opts.tol!=null ? opts.tol : 0.28;
  const eps        = opts.eps!=null ? opts.eps : 1.8;   // tiles; see rdp()
  const loops = traceRegion(inside, W, H, cells);
  const out=[];
  for(const loop of loops){
    if(loop.length < minLoop) continue;
    // ORDER MATTERS: collapse the staircase first, then round real corners
    const simplified = rdp(loop, eps);
    out.push(simplify(chaikin(simplified, iterations), tol));
  }
  return out;
}

window.VectorBorders = {
  traceRegion: traceRegion,
  rdp: rdp,
  chaikin: chaikin,
  simplify: simplify,
  smoothRegion: smoothRegion,
};

})();
