import { JSDOM } from 'jsdom';
import fs from 'fs';
const html=fs.readFileSync('/home/claude/DwarfWiki/static/index.html','utf8');
const dom=new JSDOM(html,{runScripts:'outside-only',url:'http://127.0.0.1:5000/',pretendToBeVisual:true});
const {window}=dom;
window.HTMLCanvasElement.prototype.getContext=function(){
  const noop=()=>{};
  return {canvas:this,fillStyle:'',strokeStyle:'',font:'',globalAlpha:1,lineWidth:1,textAlign:'',
    textBaseline:'',imageSmoothingEnabled:false,globalCompositeOperation:'',shadowColor:'',shadowBlur:0,
    shadowOffsetY:0,lineJoin:'',lineCap:'',
    fillRect:noop,strokeRect:noop,clearRect:noop,beginPath:noop,closePath:noop,moveTo:noop,lineTo:noop,
    arc:noop,fill:noop,stroke:noop,save:noop,restore:noop,translate:noop,rotate:noop,scale:noop,
    drawImage:noop,fillText:noop,strokeText:noop,setLineDash:noop,putImageData:noop,clip:noop,rect:noop,
    measureText:t=>({width:(t||'').length*7}),
    createRadialGradient:()=>({addColorStop:noop}),createLinearGradient:()=>({addColorStop:noop}),
    createImageData:(w,h)=>({width:w,height:h,data:new Uint8ClampedArray((w||1)*(h||1)*4)}),
    getImageData:(x,y,w,h)=>({width:w,height:h,data:new Uint8ClampedArray((w||1)*(h||1)*4)})};
};
window.fetch=(u,o)=>fetch(typeof u==='string'&&u.startsWith('/')?'http://127.0.0.1:5000'+u:u,o);
window.Image=class{constructor(){this.complete=true;this.naturalWidth=257;} set src(v){this._src=v;this.onload&&setTimeout(()=>this.onload(),1);} get src(){return this._src;}};
window.confirm=()=>true; window.prompt=(m,d)=>'Test Continent';
const errors=[]; window.onerror=m=>errors.push(m);
process.on('unhandledRejection',r=>errors.push('rejection: '+(r&&r.message||r)));
for(const f of ['vectorborders.js','map.js','wall.js']) window.eval(fs.readFileSync('/home/claude/DwarfWiki/static/'+f,'utf8'));
window.eval(html.match(/<script>([\s\S]*?)<\/script>/)[1]);
await window.eval('boot()'); await new Promise(r=>setTimeout(r,1200));
const d=window.document;
console.log('WallView loaded:', typeof window.WallView);
window.eval("location.hash='#/w/region1/wall'"); await new Promise(r=>setTimeout(r,200));
try{ await window.eval('route()'); }catch(e){ errors.push('route: '+e.message+'\n'+(e.stack||'')); }
await new Promise(r=>setTimeout(r,2500));
console.log('#wallView:', !!d.getElementById('wallView'));
console.log('#wallCanvas:', !!d.getElementById('wallCanvas'));
console.log('chrome bytes:', (d.getElementById('wallChrome')||{innerHTML:''}).innerHTML.length);
console.log('palette swatches:', d.querySelectorAll('.wsw').length);
console.log('ocean style options:', d.querySelectorAll('#wallChrome select')[3]?.options.length ?? 'n/a');
console.log('cartography dropdown:', !!d.getElementById('cartoDrop'));
const WV=window.WallView;
console.log('\n--- actions ---');
try{ WV.addRegion('region1'); console.log('  addRegion ok, placements:', WV._W.continent.placements.length); }catch(e){ errors.push('addRegion: '+e.message); }
try{ WV.addOcean(); console.log('  addOcean ok, oceans:', WV._W.continent.oceans.length); }catch(e){ errors.push('addOcean: '+e.message); }
try{ WV.setOceanStyle('trenches'); WV.rerollOceans(); console.log('  reroll ok, style:', WV._W.continent.oceans[0].style); }catch(e){ errors.push('reroll: '+e.message); }
try{ WV.setTool('paint'); WV.setColor('#375a34'); WV.setBrush(3); WV.applyBrush(10,10,false);
     console.log('  paint ok, painted tiles:', WV.paintCount()); }catch(e){ errors.push('paint: '+e.message); }
try{ WV.applyBrush(10,10,true); console.log('  erase ok, painted tiles:', WV.paintCount()); }catch(e){ errors.push('erase: '+e.message); }
try{ WV.doUndo(); console.log('  undo ok, undo depth:', WV._W.undo.length); }catch(e){ errors.push('undo: '+e.message); }
try{ WV.fitAll(); const b=WV.wallBounds(); console.log('  fitAll ok, bounds:', b && (b.w+'x'+b.h+' tiles')); }catch(e){ errors.push('fitAll: '+e.message); }
try{ await WV.saveContinent(); console.log('  save ok, id:', WV._W.continent.id); }catch(e){ errors.push('save: '+e.message); }
try{ WV.toggleRaw(); WV.toggleRaw(); console.log('  raw toggle ok'); }catch(e){ errors.push('raw: '+e.message); }
console.log('\nERRORS:', errors.length? errors.join('\n  ') : 'none');
