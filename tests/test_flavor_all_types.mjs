import { JSDOM } from 'jsdom';
import fs from 'fs';
const html=fs.readFileSync('/home/claude/DwarfWiki/static/index.html','utf8');
const dom=new JSDOM(html,{runScripts:'outside-only',url:'http://127.0.0.1:5000/',pretendToBeVisual:true});
const {window}=dom;
window.HTMLCanvasElement.prototype.getContext=function(){const n=()=>{};return{canvas:this,fillRect:n,drawImage:n,beginPath:n,arc:n,fill:n,stroke:n,save:n,restore:n,measureText:()=>({width:10}),createImageData:()=>({data:new Uint8ClampedArray(4)}),getImageData:()=>({data:new Uint8ClampedArray(4)}),putImageData:n,clearRect:n,moveTo:n,lineTo:n,closePath:n,translate:n,fillText:n};};
window.fetch=(u,o)=>fetch(typeof u==='string'&&u.startsWith('/')?'http://127.0.0.1:5000'+u:u,o);
window.Image=class{constructor(){this.complete=true;this.naturalWidth=1;} set src(v){this.onload&&setTimeout(()=>this.onload(),1);} get src(){return '';}};
const errors=[]; window.onerror=m=>errors.push(m);
process.on('unhandledRejection',r=>errors.push('rejection: '+(r&&r.message||r)));
for(const f of ['vectorborders.js','map.js','wall.js','adv_data.js','adventurer.js'])
  window.eval(fs.readFileSync('/home/claude/DwarfWiki/static/'+f,'utf8'));
window.eval(html.match(/<script>([\s\S]*?)<\/script>/)[1]);
await window.eval('boot()'); await new Promise(r=>setTimeout(r,1200));
const d=window.document;
for(const [t,id] of [['hf',1],['site',1],['ent',990],['artifact',1],['wc',1],['region',1],['creature',1]]){
  window.eval(`location.hash='#/w/region1/${t}/${id}'`); await new Promise(r=>setTimeout(r,120));
  try{ await window.eval('route()'); }catch(e){ errors.push(t+': '+e.message); }
  await new Promise(r=>setTimeout(r,1600));
  const v=d.getElementById('view');
  const secs=v.querySelectorAll('.lore-section').length;
  const gen=v.querySelectorAll('.lore-block .extra-flavor, .chronicle-more').length; const dup=[...v.querySelectorAll('.chronicle-more .lore-h .lore-title')].map(x=>x.textContent.trim());
  const cap=v.querySelectorAll('.dropcap').length;
  const rail=v.querySelectorAll('.rail .toc-list li').length;
  console.log(`${t.padEnd(9)} sections=${String(secs).padStart(2)}  dropcap=${cap}  rail=${String(rail).padStart(2)}  chronicleBlocks=${gen} extras=${dup.length}`);
}
console.log('\nERRORS:', errors.length?errors.join('\n  '):'none');
