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
for(const [hash,label] of [['#/w/region1/browse/creature','BESTIARY LIST'],['#/w/region1/creature/1','CREATURE PAGE']]){
  window.eval(`location.hash='${hash}'`); await new Promise(r=>setTimeout(r,150));
  try{ await window.eval('route()'); }catch(e){ errors.push(label+': '+e.message+'\n'+(e.stack||'').split('\n').slice(0,4).join('\n')); }
  await new Promise(r=>setTimeout(r,2500));
  const v=d.getElementById('view').innerHTML;
  const stuck=/class="loading"/.test(v);
  console.log(`${label}: ${v.length}b ${stuck?'*** STUCK ON LOADING ***':'rendered'}`);
}
console.log('\nERRORS:', errors.length?errors.join('\n  '):'none');
