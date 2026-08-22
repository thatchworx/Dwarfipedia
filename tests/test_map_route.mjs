import { JSDOM } from 'jsdom';
import fs from 'fs';

const html = fs.readFileSync('/home/claude/DwarfWiki/static/index.html','utf8');
const dom = new JSDOM(html, { runScripts:'outside-only', url:'http://127.0.0.1:5000/', pretendToBeVisual:true });
const { window } = dom;

// canvas 2d stub — jsdom has no canvas backend
// a canvas stub with REAL ImageData, so pixel loops actually execute
function makeCtx(cv){
  const noop=()=>{};
  return {
    canvas:cv,
    fillStyle:'',strokeStyle:'',font:'',globalAlpha:1,lineWidth:1,textAlign:'',textBaseline:'',
    globalCompositeOperation:'',imageSmoothingEnabled:false,shadowColor:'',shadowBlur:0,shadowOffsetY:0,
    lineJoin:'',lineCap:'',
    fillRect:noop,strokeRect:noop,clearRect:noop,beginPath:noop,closePath:noop,moveTo:noop,lineTo:noop,
    arc:noop,fill:noop,stroke:noop,save:noop,restore:noop,translate:noop,rotate:noop,scale:noop,
    drawImage:noop,fillText:noop,strokeText:noop,setLineDash:noop,putImageData:noop,clip:noop,rect:noop,
    measureText:(t)=>({width:(t||'').length*7}),
    createRadialGradient:()=>({addColorStop:noop}),
    createLinearGradient:()=>({addColorStop:noop}),
    createImageData:(w,h)=>({width:w,height:h,data:new Uint8ClampedArray(w*h*4)}),
    getImageData:(x,y,w,h)=>({width:w,height:h,data:new Uint8ClampedArray(w*h*4)}),
  };
}
window.HTMLCanvasElement.prototype.getContext = function(){ if(!this.__ctx) this.__ctx=makeCtx(this); return this.__ctx; };

const errors=[];
window.addEventListener('error', e=>errors.push('window error: '+e.message));
window.onerror=(m)=>errors.push('onerror: '+m);
process.on('unhandledRejection', r=>errors.push('unhandledRejection: '+(r&&r.message||r)));

// real fetch against the running server
// resolve relative API paths against the real server
window.fetch = (u,o)=> fetch(typeof u==='string' && u.startsWith('/') ? 'http://127.0.0.1:5000'+u : u, o);
window.Image = class { constructor(){ this.complete=false; this.naturalWidth=0; }
  set src(v){ this._src=v; setTimeout(()=>{ this.complete=true; this.naturalWidth=257; this.onload&&this.onload(); },5); }
  get src(){ return this._src; } };

// load the three scripts in page order
for(const f of ['vectorborders.js','map.js']){
  const code=fs.readFileSync('/home/claude/DwarfWiki/static/'+f,'utf8');
  try{ window.eval(code); }catch(e){ errors.push(`LOAD ${f}: ${e.message}`); }
}
// the inline script
const inline = html.match(/<script>([\s\S]*?)<\/script>/)[1];
try{ window.eval(inline); }catch(e){ errors.push('LOAD inline: '+e.message); }

console.log('MapView present:', typeof window.MapView);
console.log('viewMap present:', typeof window.viewMap);

// drive the real route
window.location.hash = '#/w/region1/map';
await new Promise(r=>setTimeout(r,300));
// drive it the way the app does: boot(), then navigate
try{ await window.eval('boot()'); }catch(e){ errors.push('boot threw: '+e.message); }
await new Promise(r=>setTimeout(r,1500));
try{ window.eval("location.hash='#/w/region1/map'"); }catch(e){ errors.push('nav threw: '+e.message); }
await new Promise(r=>setTimeout(r,500));
try{ await window.eval('route()'); }catch(e){ errors.push('route threw: '+e.message+'\n'+(e.stack||'')); }
await new Promise(r=>setTimeout(r,2500));

const d=window.document;
console.log('\n--- DOM after mount ---');
console.log('#mapView exists:', !!d.getElementById('mapView'));
console.log('#mapCanvas exists:', !!d.getElementById('mapCanvas'));
const cv=d.getElementById('mapCanvas');
console.log('canvas w/h:', cv&&cv.width, cv&&cv.height);
const sl=d.getElementById('sbLayers');
console.log('#sbLayers innerHTML length:', sl? sl.innerHTML.length : 'MISSING');
console.log('MapState.meta:', window.MapState && window.MapState.meta ? 'LOADED ('+window.MapState.meta.width+'x'+window.MapState.meta.height+')' : '*** NULL ***');
console.log('MapState.world:', window.MapState && window.MapState.world);
console.log('MapState.sites:', window.MapState && window.MapState.sites ? window.MapState.sites.length : 'none');
console.log('\n--- ERRORS ---');
console.log(errors.length? errors.join('\n\n') : 'none');
