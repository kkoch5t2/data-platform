// Observe the real raster request without extra tile probes.
export const HAZARD_LAYERS={
 flood:{label:'洪水',path:'01_flood_l2_shinsuishin_data'},
 tsunami:{label:'津波',path:'04_tsunami_newlegend_data'},
 sediment:{label:'土石流',path:'05_dosekiryukeikaikuiki'}
};
const options={tileSize:256,minzoom:2,maxzoom:17,roundZoom:true};
export function createHazardMonitor({map,maplibregl,onUpdate,fetcher=fetch,
 decode=blob=>createImageBitmap(blob),blank=()=>{const canvas=new OffscreenCanvas(256,256);canvas.getContext('2d');return createImageBitmap(canvas)}}){
 const cache=new Map(),epochs=new Map();
 const sourceId=id=>'hazard-'+id;
 const tiles=id=>['datlume-hazard://'+id+'/{z}/{x}/{y}?v='+(epochs.get(id)||0)];
 const key=(id,tile)=>id+'/'+tile;
 function refresh(){
  const visible=map.coveringTiles(options).map(t=>[t.canonical.z,t.canonical.x,t.canonical.y].join('/'));
  for(const id of Object.keys(HAZARD_LAYERS)){
   const active=map.getLayer(sourceId(id))&&map.getLayoutProperty(sourceId(id),'visibility')!=='none';
   const counts={loaded:0,missing:0,failed:0,pending:0};
   if(active)for(const tile of new Set(visible)){const entry=cache.get(key(id,tile));counts[entry?.status||'pending']++}
   const status=!active?'off':counts.failed?'failed':counts.pending?'loading':counts.loaded?'loaded':counts.missing?'missing':'unknown';
   onUpdate({id,status,counts});
  }
  if(cache.size>2048){
   const keep=new Set(Object.keys(HAZARD_LAYERS).flatMap(id=>visible.map(t=>key(id,t))));
   for(const k of cache.keys()){if(cache.size<=2048)break;if(!keep.has(k))cache.delete(k)}
  }
 }
 maplibregl.addProtocol('datlume-hazard',async(params,abortController)=>{
  const match=/^datlume-hazard:\/\/(flood|tsunami|sediment)\/(\d+)\/(\d+)\/(\d+)\?v=(\d+)$/.exec(params.url);
  if(!match)throw new Error('Invalid hazard tile URL');
  const [,id,z,x,y,version]=match,entry={status:'pending'},k=key(id,[z,x,y].join('/'));
  if(Number(z)<2||Number(z)>17||Number(x)>=2**Number(z)||Number(y)>=2**Number(z))throw new Error('Invalid hazard tile coordinates');
  const current=()=>Number(version)===(epochs.get(id)||0)&&cache.get(k)===entry;
  if(Number(version)===(epochs.get(id)||0))cache.set(k,entry);
  refresh();
  try{
   const response=await fetcher('https://disaportaldata.gsi.go.jp/raster/'+HAZARD_LAYERS[id].path+'/'+z+'/'+x+'/'+y+'.png',
    {signal:AbortSignal.any([abortController.signal,AbortSignal.timeout(15000)]),cache:Number(version)?'reload':'default'});
   if(response.status===404){
    const data=await blank();if(current()){entry.status='missing';refresh()}return {data};
   }
   if(!response.ok)throw new Error('Hazard tile HTTP '+response.status);
   const data=await decode(await response.blob());
   if(current()){entry.status='loaded';refresh()}return {data};
  }catch(error){
   if(current()){
    if(abortController.signal.aborted)cache.delete(k);
    else entry.status='failed';
    refresh();
   }
   throw error;
  }
 });
 for(const event of ['move','moveend','resize','idle'])map.on(event,refresh);
 return {
  addLayer(id,visible){
   map.addSource(sourceId(id),{type:'raster',tiles:tiles(id),tileSize:256,minzoom:2,maxzoom:17,
    attribution:'<a href="https://disaportal.gsi.go.jp/hazardmap/copyright/opendata.html" target="_blank" rel="noreferrer">ハザードマップポータルサイト</a>'});
   map.addLayer({id:sourceId(id),source:sourceId(id),type:'raster',
    layout:{visibility:visible?'visible':'none'},paint:{'raster-opacity':.43}});
   refresh();
  },
  refresh,
  retry(){
   for(const id of Object.keys(HAZARD_LAYERS)){
    if(!map.getLayer(sourceId(id))||map.getLayoutProperty(sourceId(id),'visibility')==='none')continue;
    epochs.set(id,(epochs.get(id)||0)+1);
    for(const k of cache.keys())if(k.startsWith(id+'/'))cache.delete(k);
    map.getSource(sourceId(id)).setTiles(tiles(id));
   }
   refresh();
  }
 };
}
