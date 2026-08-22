import { JSDOM } from 'jsdom';
import fs from 'fs';
const html=fs.readFileSync('/home/claude/DwarfWiki/static/index.html','utf8');
const dom=new JSDOM(html,{runScripts:'outside-only',url:'http://127.0.0.1:5000/',pretendToBeVisual:true});
const {window}=dom;
window.HTMLCanvasElement.prototype.getContext=function(){const n=()=>{};return{canvas:this,fillStyle:'',strokeStyle:'',font:'',globalAlpha:1,lineWidth:1,textAlign:'',textBaseline:'',imageSmoothingEnabled:false,lineJoin:'',lineCap:'',fillRect:n,strokeRect:n,clearRect:n,beginPath:n,closePath:n,moveTo:n,lineTo:n,arc:n,fill:n,stroke:n,save:n,restore:n,translate:n,drawImage:n,fillText:n,putImageData:n,measureText:t=>({width:(t||'').length*7}),createImageData:(w,h)=>({width:w,height:h,data:new Uint8ClampedArray(w*h*4)}),getImageData:(x,y,w,h)=>({width:w,height:h,data:new Uint8ClampedArray(Math.max(1,w*h)*4).fill(120)})};};
window.fetch=(u,o)=>fetch(typeof u==='string'&&u.startsWith('/')?'http://127.0.0.1:5000'+u:u,o);
window.Image=class{constructor(){this.complete=true;this.naturalWidth=257;} set src(v){this._src=v;this.onload&&setTimeout(()=>this.onload(),1);} get src(){return this._src;}};
window.confirm=()=>true; window.prompt=(m,d)=>'Ironhold';
const errors=[]; window.onerror=m=>errors.push(m);
process.on('unhandledRejection',r=>errors.push('rejection: '+(r&&r.message||r)));
for(const f of ['vectorborders.js','map.js','wall.js']) window.eval(fs.readFileSync('/home/claude/DwarfWiki/static/'+f,'utf8'));
window.eval(html.match(/<script>([\s\S]*?)<\/script>/)[1]);
await window.eval('boot()'); await new Promise(r=>setTimeout(r,1200));
const d=window.document;
console.log('=== NAVBAR ===');
console.log('  top-level items:', d.querySelectorAll('nav.tabs > a, nav.tabs > .tabdrop').length);
console.log('  dropdowns:', d.querySelectorAll('.tabdrop').length);
console.log('  blank header buttons:', d.querySelectorAll('.top-actions button')
  .length ? [...d.querySelectorAll('.top-actions button')].filter(b=>!b.textContent.trim()&&!b.querySelector('svg')).length : 0);
console.log('  any icon left in nav labels:', /[\u{1F300}-\u{1FAFF}\u2600-\u27BF]/u.test(d.querySelector('nav.tabs').textContent));
// active state through a dropdown
window.eval("location.hash='#/w/region1/browse/site'"); await new Promise(r=>setTimeout(r,150));
await window.eval('route()'); await new Promise(r=>setTimeout(r,1500));
const bd=d.querySelector('.tabdrop[data-drop="browse"]');
console.log('  browse trigger marked active on a browse route:', bd && bd.classList.contains('here'));
console.log('\n=== WALL ===');
window.eval("location.hash='#/w/region1/wall'"); await new Promise(r=>setTimeout(r,150));
await window.eval('route()'); await new Promise(r=>setTimeout(r,2200));
const WV=window.WallView;
console.log('  base swatches:', d.querySelectorAll('.wpal .wsw').length);
try{ WV.toggleShades(); }catch(e){ errors.push('shades: '+e.message); }
console.log('  shade ramps:', d.querySelectorAll('.wramp').length, '| total shade swatches:', d.querySelectorAll('.wrampr .wsw').length);
WV.toggleShades();
try{ const c=WV.pickColorAt(10,10); console.log('  eyedropper sampled:', c); }catch(e){ errors.push('pick: '+e.message); }
try{ WV.setColor('#aabbcc'); WV.applyBrush(5,5,false);
  console.log('  paint stores colour:', JSON.stringify(WV.paintGet(5,5))); }catch(e){ errors.push('paint: '+e.message); }
try{ WV.addLabelAt(100,100); console.log('  label added:', JSON.stringify(WV._W.labels[0])); }catch(e){ errors.push('label: '+e.message); }
try{ console.log('  hitLabel finds it:', WV.hitLabel(100,100)>=0); }catch(e){ errors.push('hit: '+e.message); }
try{ WV.addRegion('region1'); await WV.saveContinent();
  const id=WV._W.continent.id; WV.newContinent(); await WV.loadContinent(id);
  await new Promise(r=>setTimeout(r,500));
  console.log('  labels survive save/load:', WV._W.labels.length, '| paint:', WV.paintCount());
}catch(e){ errors.push('roundtrip: '+e.message); }
console.log('\nERRORS:', errors.length?errors.join('\n  '):'none');
