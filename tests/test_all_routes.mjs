import { JSDOM } from 'jsdom';
import fs from 'fs';
const html=fs.readFileSync('/home/claude/DwarfWiki/static/index.html','utf8');
const dom=new JSDOM(html,{runScripts:'outside-only',url:'http://127.0.0.1:5000/',pretendToBeVisual:true});
const {window}=dom;
window.HTMLCanvasElement.prototype.getContext=function(){
  const noop=()=>{};
  return {canvas:this,
    fillStyle:'',strokeStyle:'',font:'',globalAlpha:1,lineWidth:1,textAlign:'',textBaseline:'',
    globalCompositeOperation:'',imageSmoothingEnabled:false,shadowColor:'',shadowBlur:0,shadowOffsetY:0,
    shadowOffsetX:0,lineJoin:'',lineCap:'',miterLimit:10,
    fillRect:noop,strokeRect:noop,clearRect:noop,beginPath:noop,closePath:noop,moveTo:noop,lineTo:noop,
    arc:noop,arcTo:noop,ellipse:noop,rect:noop,fill:noop,stroke:noop,clip:noop,
    save:noop,restore:noop,translate:noop,rotate:noop,scale:noop,transform:noop,setTransform:noop,
    drawImage:noop,fillText:noop,strokeText:noop,setLineDash:noop,getLineDash:()=>[],putImageData:noop,
    quadraticCurveTo:noop,bezierCurveTo:noop,
    measureText:(t)=>({width:(t||'').length*7}),
    createRadialGradient:()=>({addColorStop:noop}),
    createLinearGradient:()=>({addColorStop:noop}),
    createPattern:()=>null,
    createImageData:(w,h)=>({width:w,height:h,data:new Uint8ClampedArray((w||1)*(h||1)*4)}),
    getImageData:(x,y,w,h)=>({width:w,height:h,data:new Uint8ClampedArray((w||1)*(h||1)*4)}),
  };
};
window.fetch=(u,o)=>fetch(typeof u==='string'&&u.startsWith('/')?'http://127.0.0.1:5000'+u:u,o);
window.Image=class{constructor(){this.complete=true;this.naturalWidth=257;} set src(v){this._src=v;this.onload&&setTimeout(()=>this.onload(),1);} get src(){return this._src;}};
const errors=[]; window.onerror=m=>errors.push(m);
process.on('unhandledRejection',r=>errors.push('rejection: '+(r&&r.message||r)+'\n    '+((r&&r.stack)||'').split('\n').slice(1,5).join('\n    ')));
for(const f of ['vectorborders.js','map.js']) window.eval(fs.readFileSync('/home/claude/DwarfWiki/static/'+f,'utf8'));
window.eval(html.match(/<script>([\s\S]*?)<\/script>/)[1]);
await window.eval('boot()'); await new Promise(r=>setTimeout(r,1200));
const d=window.document;
async function go(hash,label,ms=1800){
  window.eval(`location.hash='${hash}'`); await new Promise(r=>setTimeout(r,200));
  try{ await window.eval('route()'); }catch(e){ errors.push(label+': '+e.message); }
  await new Promise(r=>setTimeout(r,ms));
  const n=d.getElementById('view').innerHTML.length;
  console.log(`[${label.padEnd(10)}] ${String(n).padStart(7)}b  ${n>500?'ok':'*** EMPTY ***'}`);
}
console.log('--- every route ---');
await go('#/','ATLAS');
await go('#/w/region1/home','HOME');
await go('#/w/region1/browse/hf','BROWSE');
await go('#/w/region1/hf/1','FIGURE');
await go('#/w/region1/site/1','SITE');
await go('#/w/region1/browse/ent','CIVS');
await go('#/w/region1/timeline','TIMELINE');
await go('#/w/region1/stats','STATS',2500);
await go('#/w/region1/map','MAP',2500);
await go('#/w/region1/tags','TAGS');
await go('#/w/region1/bookmarks','BOOKMARKS');
console.log('\n--- header ---');
console.log('  settings menu:', !!d.getElementById('settingsMenu'));
console.log('  random button:', !!d.getElementById('randomBtn'));
console.log('  legacy darkModeBtn kept (code toggles it):', !!d.getElementById('darkModeBtn'));
console.log('  printNoImages present:', !!d.getElementById('printNoImages'));
console.log('\n--- interactions ---');
try{ window.eval('toggleSettingsMenu(null)'); console.log('  toggleSettingsMenu ok'); }catch(e){ errors.push('settings: '+e.message); }
try{ window.eval('closeSettingsMenu()'); console.log('  closeSettingsMenu ok'); }catch(e){ errors.push('closeSettings: '+e.message); }
try{ window.eval('toggleDarkMode()'); console.log('  toggleDarkMode ok'); }catch(e){ errors.push('darkmode: '+e.message); }
try{ window.eval('toggleSfxMuted()'); console.log('  toggleSfxMuted ok'); }catch(e){ errors.push('sfx: '+e.message); }
await go('#/w/region1/hf/1','FIGURE2');
try{ window.eval('toggleToc()'); console.log('  toggleToc ok'); }catch(e){ errors.push('toc: '+e.message); }
try{ window.eval("jumpToSection('sec-overview')"); console.log('  jumpToSection ok'); }catch(e){ errors.push('jump: '+e.message); }
console.log('\nERRORS:', errors.length? errors.join('\n  ') : 'none');
