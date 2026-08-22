import { JSDOM } from 'jsdom';
import fs from 'fs';
const html=fs.readFileSync('/home/claude/DwarfWiki/static/index.html','utf8');
const dom=new JSDOM(html,{runScripts:'outside-only',url:'http://127.0.0.1:5000/',pretendToBeVisual:true});
const {window}=dom;
window.HTMLCanvasElement.prototype.getContext=function(){const n=()=>{};return{canvas:this,fillStyle:'',strokeStyle:'',font:'',globalAlpha:1,lineWidth:1,textAlign:'',textBaseline:'',imageSmoothingEnabled:false,lineJoin:'',lineCap:'',fillRect:n,strokeRect:n,clearRect:n,beginPath:n,closePath:n,moveTo:n,lineTo:n,arc:n,fill:n,stroke:n,save:n,restore:n,translate:n,drawImage:n,fillText:n,putImageData:n,measureText:t=>({width:10}),createImageData:(w,h)=>({width:w,height:h,data:new Uint8ClampedArray(w*h*4)}),getImageData:(x,y,w,h)=>({width:w,height:h,data:new Uint8ClampedArray(w*h*4)})};};
window.fetch=(u,o)=>fetch(typeof u==='string'&&u.startsWith('/')?'http://127.0.0.1:5000'+u:u,o);
window.Image=class{constructor(){this.complete=true;this.naturalWidth=257;} set src(v){this._src=v;this.onload&&setTimeout(()=>this.onload(),1);} get src(){return this._src;}};
window.confirm=()=>true; window.prompt=()=>'Roundtrip Test';
const errors=[]; window.onerror=m=>errors.push(m);
process.on('unhandledRejection',r=>errors.push('rejection: '+(r&&r.message||r)));
for(const f of ['vectorborders.js','map.js','wall.js']) window.eval(fs.readFileSync('/home/claude/DwarfWiki/static/'+f,'utf8'));
window.eval(html.match(/<script>([\s\S]*?)<\/script>/)[1]);
await window.eval('boot()'); await new Promise(r=>setTimeout(r,1000));
window.eval("location.hash='#/w/region1/wall'"); await new Promise(r=>setTimeout(r,150));
await window.eval('route()'); await new Promise(r=>setTimeout(r,2000));
const WV=window.WallView;
// build a real continent
WV.addRegion('region1');
WV._W.continent.placements[0].x=0; WV._W.continent.placements[0].y=0;
WV.setOceanStyle('ridges'); WV.addOcean();
WV.setColor('#a69462'); WV.setBrush(5);
for(let i=0;i<40;i++) WV.applyBrush(300+i, 120, false);
const before={p:WV._W.continent.placements.length,o:WV._W.continent.oceans.length,
  paint:WV.paintCount(), seed:WV._W.continent.oceans[0].seed, style:WV._W.continent.oceans[0].style,
  sample:WV.paintGet(300,120)};
console.log('BEFORE save:', JSON.stringify(before));
await WV.saveContinent();
const id=WV._W.continent.id;
console.log('saved id:', id);
// wipe and reload
WV.newContinent();
console.log('after new: placements=',WV._W.continent.placements.length,'paint=',WV.paintCount());
await WV.loadContinent(id);
await new Promise(r=>setTimeout(r,600));
const after={p:WV._W.continent.placements.length,o:WV._W.continent.oceans.length,
  paint:WV.paintCount(), seed:WV._W.continent.oceans[0]?.seed, style:WV._W.continent.oceans[0]?.style,
  sample:WV.paintGet(300,120)};
console.log('AFTER load: ', JSON.stringify(after));
const same=JSON.stringify(before)===JSON.stringify(after);
console.log('\nROUND-TRIP IDENTICAL:', same ? 'YES' : '*** NO — data lost ***');
console.log('ERRORS:', errors.length?errors.join('\n  '):'none');
