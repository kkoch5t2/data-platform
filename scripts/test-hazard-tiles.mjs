import assert from 'node:assert/strict';
import {createHazardMonitor} from '../public/js/hazard-tiles.mjs';
let checks=0;
function setup(fetcher,decode=async()=>({image:true})){
 let handler,visible=[{canonical:{z:5,x:28,y:12}}],status,visibility='visible',url;
 const map={coveringTiles:()=>visible,getLayer:id=>id==='hazard-flood'?{}:null,getLayoutProperty:()=>visibility,on(){},
  getSource:()=>({setTiles:tiles=>url=tiles[0]})};
 const monitor=createHazardMonitor({map,maplibregl:{addProtocol:(_,h)=>handler=h},fetcher,decode,blank:async()=>({blank:true}),
  onUpdate:s=>{if(s.id==='flood')status=s}});
 return {monitor,request:(v=0,controller=new AbortController())=>handler({url:'datlume-hazard://flood/5/28/12?v='+v},controller),
  status:()=>status,setVisible:v=>visibility=v,setViewport:v=>visible=v,url:()=>url};
}
for(const [http,expected] of [[200,'loaded'],[404,'missing'],[503,'failed'],[403,'failed']]){
 const f=setup(async()=>({status:http,ok:http===200,blob:async()=>new Blob()}));
 if(http===200||http===404)await f.request();else await assert.rejects(f.request());
 assert.equal(f.status().status,expected);checks++;
 f.setVisible('none');f.monitor.refresh();assert.equal(f.status().status,'off');checks++;
 f.setVisible('visible');f.setViewport([{canonical:{z:6,x:55,y:25}}]);f.monitor.refresh();
 assert.equal(f.status().status,'loading');assert.equal(f.status().counts.failed,0);checks++;
}
for(const [fetcher,decode] of [
 [async()=>{throw new TypeError('network')},async()=>({})],
 [async()=>({status:200,ok:true,blob:async()=>new Blob(['not png'])}),async()=>{throw new Error('invalid image')}]
]){
 const f=setup(fetcher,decode);await assert.rejects(f.request());assert.equal(f.status().status,'failed');checks++;
}
{
 let resolve;
 const f=setup(()=>new Promise(r=>resolve=r));const old=f.request();f.monitor.retry();
 assert(f.url().endsWith('?v=1'));resolve({status:404,ok:false});await old;
 assert.equal(f.status().status,'loading');checks++;
}
{
 const controller=new AbortController(),f=setup(async()=>{controller.abort();throw new DOMException('aborted','AbortError')});
 await assert.rejects(f.request(0,controller));assert.equal(f.status().counts.failed,0);checks++;
}
{
 let mode=503;const f=setup(async()=>({status:mode,ok:mode===200,blob:async()=>new Blob()}));
 await assert.rejects(f.request());f.monitor.retry();mode=200;await f.request(1);
 assert.equal(f.status().status,'loaded');checks++;
}
console.log('hazard tile tests: '+checks+' assertions, 0 failures');
