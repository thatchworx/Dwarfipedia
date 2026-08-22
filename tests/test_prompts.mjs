import { JSDOM } from 'jsdom';
import fs from 'fs';
const html=fs.readFileSync('/home/claude/DwarfWiki/static/index.html','utf8');
const dom=new JSDOM(html,{runScripts:'outside-only',url:'http://127.0.0.1:5000/',pretendToBeVisual:true});
const {window}=dom;
window.HTMLCanvasElement.prototype.getContext=function(){const n=()=>{};return{canvas:this,fillRect:n,drawImage:n,beginPath:n,arc:n,fill:n,stroke:n,save:n,restore:n,measureText:()=>({width:10}),createImageData:(w,h)=>({data:new Uint8ClampedArray(4)}),getImageData:()=>({data:new Uint8ClampedArray(4)}),putImageData:n,clearRect:n,moveTo:n,lineTo:n,closePath:n,translate:n,fillText:n};};
window.fetch=(u,o)=>fetch(typeof u==='string'&&u.startsWith('/')?'http://127.0.0.1:5000'+u:u,o);
window.Image=class{constructor(){this.complete=true;this.naturalWidth=1;} set src(v){this.onload&&setTimeout(()=>this.onload(),1);} get src(){return '';}};
window.confirm=()=>true;
const errors=[]; window.onerror=m=>errors.push(m);
process.on('unhandledRejection',r=>errors.push('rejection: '+(r&&r.message||r)));
for(const f of ['vectorborders.js','map.js','wall.js','adv_data.js','adventurer.js'])
  window.eval(fs.readFileSync('/home/claude/DwarfWiki/static/'+f,'utf8'));
window.eval(html.match(/<script>([\s\S]*?)<\/script>/)[1]);
await window.eval('boot()'); await new Promise(r=>setTimeout(r,1000));
window.eval("location.hash='#/prompts'"); await new Promise(r=>setTimeout(r,150));
await window.eval('route()'); await new Promise(r=>setTimeout(r,1200));
const d=window.document;
console.log('prompt editor rendered:', d.querySelectorAll('.pr-sec').length, 'sections');
console.log('seed inputs:', d.querySelectorAll('.pr-seeds .pr-item').length, '| banned inputs:', d.querySelectorAll('.pr-banned .pr-item').length);
console.log('prompt textareas:', d.querySelectorAll('.pr-sec textarea').length);
console.log('combination count shown:', /possible combinations/.test(d.getElementById('view').innerHTML));
// edit + save round trip
// NOTE: jsdom with runScripts:'outside-only' does NOT execute inline
// oninput=/onclick= attributes, so dispatching an event here would go
// nowhere. Call the handlers directly, which is what the attribute would do.
window.eval("promptSeedAdd()"); await new Promise(r=>setTimeout(r,150));
const idx=d.querySelectorAll('.pr-seeds .pr-item input').length-1;
window.eval(`promptSeed(${idx},'TEST SEED')`);
window.eval('promptSave()'); await new Promise(r=>setTimeout(r,800));
const after=await (await fetch('http://127.0.0.1:5000/api/prompts')).json();
console.log('saved seed persisted:', after.style_seeds.includes('TEST SEED'));
window.eval('promptResetAll()'); await new Promise(r=>setTimeout(r,500));
const reset=await (await fetch('http://127.0.0.1:5000/api/prompts')).json();
console.log('reset restored defaults:', reset.style_seeds.length, 'seeds, TEST SEED gone:', !reset.style_seeds.includes('TEST SEED'));
console.log('\nERRORS:', errors.length?errors.join('\n  '):'none');
