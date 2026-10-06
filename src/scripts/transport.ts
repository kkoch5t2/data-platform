import * as echarts from 'echarts';
const $ = (id: string) => document.getElementById(id) as any;
const nf = new Intl.NumberFormat('ja-JP'), decimal = new Intl.NumberFormat('ja-JP', {maximumFractionDigits:1});
const q = new URLSearchParams(location.search), charts = new Map<string, any>();
let stations: any, commute: any, usage: any, selected: any, filtered: any[] = [], page = 0, railPeriod = 'monthly', revision = 0;
const PAGE = 10;
const stateLabels: any = {ok:'',missing:'データなし',private:'非公開',absent:'駅なし', 'other-line':'他路線に記載',unclassified:'原典の欠損'};
const setText = (id: string, text: any) => { $(id).textContent = text; };
const normalize = (s: string) => s.normalize('NFKC').replace(/[ァ-ヶ]/g, c=>String.fromCharCode(c.charCodeAt(0)-96)).toLocaleLowerCase().replace(/\s/g,'');
function options(id: string, list: any[], want = '') { const el=$(id); el.replaceChildren(...list.map(([v,t])=>new Option(t,v))); if(list.some(([v])=>v===want)) el.value=want; }
function chart(id: string, option: any) { if(!charts.has(id)) charts.set(id,echarts.init($(id))); charts.get(id).setOption({...option,animation:false},true); }
async function load(name: string) { const r=await fetch('/data/transport/'+name+'.json'); if(!r.ok) throw Error('交通データを読み込めません。再読み込みしてください。'); return r.json(); }
function err(e: any) { $('load-error').hidden=false; setText('load-error', e.message || String(e)); }
function persist() {
 const params=new URLSearchParams({tab:document.querySelector('[role=tab][aria-selected=true]')!.id.replace('tab-',''),year:$('station-year').value});
 for(const [key,id] of [['q','station-search'],['operator','operator'],['line','line'],['compare','station-compare'],['mode','station-chart-mode'],['prefA','pref-a'],['areaA','area-a'],['prefB','pref-b'],['areaB','area-b'],['bus','bus-pref'],['sort','station-sort']]) if($(id).value) params.set(key,$(id).value);
 if(selected)params.set('station',selected.id); if($('show-missing').checked)params.set('missing','1');params.set('rail',railPeriod);
 history.replaceState(null,'','?'+params);
}
function delta(a: any,b: any) { return a==null||b==null||b===0?null:(a/b-1)*100; }
function signed(v: number | null) { return v==null?'比較不可':(v>0?'+':'')+decimal.format(v)+'%'; }
const yearIndex=()=>Number($('station-year').value)-2011;
function lines(want='') { const rows=stations.records.filter((r:any)=>!$('operator').value||r.operator===$('operator').value); options('line',[['','すべての路線'],...[...new Set(rows.map((r:any)=>r.line))].sort((a:any,b:any)=>a.localeCompare(b,'ja')).map(v=>[v,v])],want); }
function filter() {
 const search=normalize($('station-search').value),i=yearIndex();
 filtered=stations.records.filter((r:any)=>(!search||normalize(r.name+' '+r.line+' '+r.operator).includes(search))&&(!$('operator').value||r.operator===$('operator').value)&&(!$('line').value||r.line===$('line').value)&&($('show-missing').checked||r.values[i]!=null)&&r.states[i]!=='other-line');
 const sort=$('station-sort').value;
 if(sort==='growth')filtered=filtered.filter(r=>i>0&&delta(r.values[i],r.values[i-1])!=null);
 filtered.sort((a,b)=>sort==='name'?a.name.localeCompare(b.name,'ja'):sort==='growth'?(delta(b.values[i],b.values[i-1])!-delta(a.values[i],a.values[i-1])!):((b.values[i]??-1)-(a.values[i]??-1)||a.name.localeCompare(b.name,'ja')));
 page=0;results();
 options('station-compare',[['','比較なし'],...filtered.filter(r=>r.id!==selected?.id).map(r=>[r.id,r.name+' · '+r.operator+' / '+r.line])],$('station-compare').value);
 setText('station-count', nf.format(filtered.length)+'件 · '+$('station-year').value+'年度'+(sort==='growth'?' · 前年度と比較できる駅のみ':''));
}
function results() {
 const target=$('station-results');target.replaceChildren();const i=yearIndex();
 if(!filtered.length) { const p=document.createElement('p');p.className='empty';p.textContent='該当する駅がありません。検索語や会社・路線の条件を変更してください。';target.append(p); }
 for(const r of filtered.slice(page*PAGE,(page+1)*PAGE)) {
  const btn=document.createElement('button');btn.className='result';btn.setAttribute('aria-pressed',String(r.id===selected?.id));
  const top=document.createElement('div');top.className='result-top';const title=document.createElement('span');title.textContent=r.name;const v=document.createElement('strong');v.textContent=$('station-sort').value==='growth'?signed(delta(r.values[i],r.values[i-1])):r.values[i]==null?stateLabels[r.states[i]]:nf.format(r.values[i])+'人／日';top.append(title,v);
  const sub=document.createElement('small');sub.textContent=r.operator+' · '+r.line;btn.append(top,sub);btn.addEventListener('click',()=>{document.querySelector('.station-layout')!.classList.remove('searching');selected=r;const previous=$('station-compare').value;filter();$('station-compare').value=previous===r.id?'':previous;drawStation();if(matchMedia('(max-width:660px)').matches)$('station-name').scrollIntoView({behavior:'smooth',block:'start'});});target.append(btn);
 }
 $('result-prev').disabled=page===0;$('result-next').disabled=(page+1)*PAGE>=filtered.length;setText('result-page',filtered.length?(page*PAGE+1)+'〜'+Math.min((page+1)*PAGE,filtered.length)+' / '+nf.format(filtered.length):'0件');
}
function drawStation() {
 if(!selected)return;const a=selected,b=stations.records.find((r:any)=>r.id===$('station-compare').value),i=yearIndex(),v=a.values[i],prev=a.values[i-1];
 setText('station-name',a.name);setText('station-description',a.operator+' · '+a.line);setText('station-value-label',$('station-year').value+'年度 · 1日あたりの乗降客数');setText('station-value',v==null?stateLabels[a.states[i]]:nf.format(v)+'人');setText('station-value-meta',v==null?'欠損を0人として扱いません':'会社・路線の原典値');setText('station-change',signed(i>0?delta(v,prev):null));setText('station-change-meta',i>0&&v!=null&&prev!=null?'前年度 '+nf.format(prev)+'人／日':'両年度の数値がある場合のみ比較');
 const indexed=$('station-chart-mode').value==='index';const rows=[a,b].filter(Boolean);
 const series=rows.map((r,n)=>({name:r.name+' · '+r.operator,type:'line',connectNulls:false,symbolSize:5,lineStyle:{width:2.5,type:n?'dashed':'solid'},itemStyle:{color:n?'#db7048':'#1769e0'},data:r.values.map((v:any)=>indexed?(r.values[8]>0&&v!=null?+(v/r.values[8]*100).toFixed(1):null):v)}));
 chart('station-chart',{tooltip:{trigger:'axis',valueFormatter:(v:any)=>v==null?'データなし':decimal.format(v)+(indexed?'（2019年度＝100）':'人／日')},legend:{type:'scroll',top:10,textStyle:{fontSize:11}},grid:{left:64,right:12,top:65,bottom:35},xAxis:{type:'category',data:stations.years,axisLabel:{hideOverlap:true}},yAxis:{type:'value',name:indexed?'指数':'人／日',axisLabel:{formatter:(v:number)=>v>=1e4?decimal.format(v/1e4)+'万':nf.format(v)}},series});
 setText('station-chart-note',indexed&&rows.some(r=>!(r.values[8]>0))?'2019年度の値がない・0人の駅は指数を表示できません。':'2011〜2024年度。非公開・駅なし・他路線への記載は線をつなぎません。');
 $('station-map').href='https://maps.gsi.go.jp/#16/'+a.lat+'/'+a.lon+'/&base=std&ls=std&disp=1&vs=c0j0h0k0l0u0t0z0r0s0m0f1';
 const body=$('station-history');body.replaceChildren();
 for(let j=stations.years.length-1;j>=0;j--) { const tr=document.createElement('tr');for(const [n,text] of [stations.years[j]+'年度',a.values[j]==null?stateLabels[a.states[j]]:nf.format(a.values[j]),a.notes[stations.years[j]]||'—'].entries()){const td=document.createElement('td');td.textContent=text;if(n===1)td.className='num';tr.append(td);}body.append(tr); }
 persist();
}
function areas(prefix: string,want='') { const pref=$('pref-'+prefix).value,rows=commute.records.filter((r:any)=>r.prefecture===pref);options('area-'+prefix,rows.map((r:any)=>[r.code,r.code.endsWith('000')?r.name+'（全体）':r.name]),want); }
const area=(prefix:string)=>commute.records.find((r:any)=>r.code===$('area-'+prefix).value);
const compactCodes=['21','22','31','24','27','1'];
function drawRegions() {
 const a=area('a'),b=area('b');if(!a||!b)return;
 setText('area-a-label',a.name);setText('area-b-label',b.name);setText('commute-sub',a.name+'：'+nf.format(a.total)+'人 / '+b.name+'：'+nf.format(b.total)+'人（2020年）');
 const groups=compactCodes.map(c=>({label:commute.modes.find((m:any)=>m.code===c).label,indices:[commute.modes.findIndex((m:any)=>m.code===c)]}));
 groups.push({label:'その他の単独・併用',indices:commute.modes.map((m:any,i:number)=>!compactCodes.includes(m.code)&&m.code!=='5'?i:-1).filter((i:number)=>i>=0)},{label:'不詳',indices:[commute.modes.findIndex((m:any)=>m.code==='5')]});
 const ratio=(r:any,g:any)=>r.total?g.indices.reduce((n:number,i:number)=>n+r.values[i],0)/r.total*100:null;
 chart('commute-chart',{tooltip:{trigger:'axis',valueFormatter:(v:number)=>decimal.format(v)+'%'},legend:{top:0,textStyle:{fontSize:11}},grid:{left:15,right:30,top:45,bottom:25,containLabel:true},xAxis:{type:'value',name:'%',max:100},yAxis:{type:'category',inverse:true,data:groups.map(g=>g.label),axisLabel:{fontSize:11}},series:[a,b].map((r,n)=>({name:r.name,type:'bar',itemStyle:{color:n?'#db7048':'#1769e0'},data:groups.map(g=>ratio(r,g))}))});
 const body=$('commute-table');body.replaceChildren();for(let i=0;i<commute.modes.length;i++){const tr=document.createElement('tr');for(const [j,v] of [commute.modes[i].label,nf.format(a.values[i])+'人',nf.format(b.values[i])+'人'].entries()){const td=document.createElement('td');td.textContent=v;if(j)td.className='num';tr.append(td);}body.append(tr);}persist();
}
function drawBus() {
 const data=usage.bus,all=data.records[0],r=data.records.find((r:any)=>r.code===$('bus-pref').value);setText('bus-title',data.year+'年度 · 乗合バスの年間利用');setText('bus-value',decimal.format(r.thousands/1e5)+'億人');setText('bus-value-meta',r.name+' · '+nf.format(r.thousands)+'千人');setText('bus-share',decimal.format(r.thousands/all.thousands*100)+'%');
 const ranking=data.records.slice(1).sort((a:any,b:any)=>b.thousands-a.thousands),top=ranking.slice(0,12);if(!top.some((x:any)=>x.code===r.code)&&r.code!=='00')top.push(r);
 chart('bus-chart',{tooltip:{trigger:'axis',valueFormatter:(v:number)=>nf.format(v)+'千人'},grid:{left:65,right:45,top:15,bottom:35},xAxis:{type:'value',name:'億人',axisLabel:{formatter:(v:number)=>decimal.format(v/1e5)}},yAxis:{type:'category',inverse:true,data:top.map((x:any)=>x.name),axisLabel:{fontSize:11}},series:[{type:'bar',data:top.map((x:any)=>({value:x.thousands,itemStyle:{color:x.code===r.code?'#1769e0':'#a8bedb'}}))}]});
 const body=$('bus-table');body.replaceChildren();for(const x of ranking){const tr=document.createElement('tr');const td=document.createElement('td'),btn=document.createElement('button');btn.className='btn';btn.textContent=x.name;btn.addEventListener('click',()=>{$('bus-pref').value=x.code;drawBus();});td.append(btn);const v=document.createElement('td');v.className='num';v.textContent=nf.format(x.thousands);tr.append(td,v);body.append(tr);}persist();
}
function drawRail() {
 const rows=usage.rail[railPeriod],last=rows.at(-1),prev=railPeriod==='annual'?rows.at(-2):rows.find((r:any)=>r.period===String(Number(last.period.slice(0,4))-1)+last.period.slice(4));
 setText('rail-sub',railPeriod==='monthly'?'月報 · '+rows[0].period+'〜'+last.period:'年度実績 · '+rows[0].period+'〜'+last.period+'年度');setText('rail-period',last.period+(railPeriod==='annual'?'年度':'')+' · 全国');setText('rail-value',decimal.format(last.thousands[0]/1e5)+'億人');setText('rail-change-label',railPeriod==='monthly'?'前年同月比':'前年度比');setText('rail-change',signed(delta(last.thousands[0],prev?.thousands[0])));
 $('rail-monthly').setAttribute('aria-pressed',String(railPeriod==='monthly'));$('rail-annual').setAttribute('aria-pressed',String(railPeriod==='annual'));
 chart('rail-chart',{tooltip:{trigger:'axis',valueFormatter:(v:number)=>decimal.format(v)+'億人'},legend:{top:0},grid:{left:52,right:20,top:45,bottom:40},xAxis:{type:'category',data:rows.map((r:any)=>r.period),axisLabel:{hideOverlap:true}},yAxis:{type:'value',name:'億人'},series:[{name:'JR旅客会社',type:'line',itemStyle:{color:'#1769e0'},lineStyle:{width:3},data:rows.map((r:any)=>r.thousands[1]/1e5)},{name:'JR以外の民鉄',type:'line',itemStyle:{color:'#db7048'},lineStyle:{width:3,type:'dashed'},data:rows.map((r:any)=>r.thousands[2]/1e5)}]});
 const body=$('rail-table');body.replaceChildren();for(const r of [...rows].reverse()){const tr=document.createElement('tr');[r.period,...r.thousands.map((v:number)=>nf.format(v))].forEach((v:any,n:number)=>{const td=document.createElement('td');td.textContent=v;if(n)td.className='num';tr.append(td);});body.append(tr);}persist();
}
async function tab(name:string) {
 const token=++revision;
 for(const n of ['stations','regions','national']){$('tab-'+n).setAttribute('aria-selected',String(n===name));$('panel-'+n).hidden=n!==name;}
 try {
  if(name==='regions'){if(!commute)commute=await load('commute');if(!usage)usage=await load('usage');if(token!==revision)return;
   if(!$('pref-a').options.length){const prefs=[...new Set(commute.records.map((r:any)=>r.prefecture))];for(const p of ['a','b']){options('pref-'+p,prefs.map(v=>[v,v]),q.get('pref'+p.toUpperCase())||(p==='a'?'東京都':'大阪府'));areas(p,q.get('area'+p.toUpperCase())||(p==='a'?'13104':'27100'));}options('bus-pref',usage.bus.records.map((r:any)=>[r.code,r.name]),q.get('bus')||'13');}
   drawRegions();drawBus();
  } else if(name==='national'){if(!usage)usage=await load('usage');if(token!==revision)return;drawRail();}
  persist();requestAnimationFrame(()=>charts.forEach(c=>c.resize()));
 }catch(e){err(e);}
}
for(const n of ['stations','regions','national'])$('tab-'+n).addEventListener('click',()=>tab(n));
$('operator').addEventListener('change',()=>{document.querySelector('.station-layout')!.classList.add('searching');lines();filter();drawStation();});
for(const id of ['station-search','line','station-year','station-sort','show-missing'])$(id).addEventListener(id==='station-search'?'input':'change',()=>{if(stations){document.querySelector('.station-layout')!.classList.add('searching');filter();drawStation();}});
for(const id of ['station-compare','station-chart-mode'])$(id).addEventListener('change',drawStation);
$('result-prev').addEventListener('click',()=>{page--;results();});$('result-next').addEventListener('click',()=>{page++;results();});
for(const p of ['a','b']){$('pref-'+p).addEventListener('change',()=>{areas(p);drawRegions();});$('area-'+p).addEventListener('change',drawRegions);}
$('bus-pref').addEventListener('change',drawBus);
for(const p of ['monthly','annual'])$('rail-'+p).addEventListener('click',()=>{railPeriod=p;drawRail();});
$('share').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(location.href);setText('share-status','現在の表示条件を含むリンクをコピーしました。');}catch{setText('share-status','アドレスバーのURLをコピーしてください。');}});
$('station-csv').addEventListener('click',()=>{if(!selected)return;const escape=(v:any)=>'"'+String(v??'').replace(/"/g,'""')+'"';const rows=[['レコードID','原典駅コード','駅名','会社','路線','年度','乗降客数（人/日）','状態','原典備考'],...stations.years.map((y:number,i:number)=>[selected.id,selected.code,selected.name,selected.operator,selected.line,y,selected.values[i],stateLabels[selected.states[i]]||'データあり',selected.notes[y]||''])];const url=URL.createObjectURL(new Blob(['\ufeff'+rows.map((r:any[])=>r.map(escape).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='station-'+selected.id+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
(async()=>{try{
 stations=await load('stations');options('operator',[['','すべての会社'],...[...new Set(stations.records.map((r:any)=>r.operator))].sort().map(v=>[v,v])],q.get('operator')||'');lines(q.get('line')||'');
 for(const [key,id] of [['year','station-year'],['sort','station-sort'],['mode','station-chart-mode']]){const val=q.get(key);if(val&&[...$(id).options].some((o:any)=>o.value===val))$(id).value=val;}
 $('station-search').value=q.get('q')||'';$('show-missing').checked=q.get('missing')==='1';railPeriod=q.get('rail')==='annual'?'annual':'monthly';
 selected=stations.records.find((r:any)=>r.id===q.get('station'))||stations.records.find((r:any)=>r.name==='新宿'&&r.operator==='東日本旅客鉄道'&&r.values.at(-1)!=null)||stations.records[0];filter();
 if(q.get('compare')&&[...$('station-compare').options].some((o:any)=>o.value===q.get('compare')))$('station-compare').value=q.get('compare');drawStation();
 await tab(['regions','national'].includes(q.get('tab')||'')?q.get('tab')!:'stations');
}catch(e){setText('station-count','読み込み失敗');err(e);}})();
document.querySelector('[role=tablist]')!.addEventListener('keydown',(e:any)=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const tabs=[...document.querySelectorAll('[role=tab]')] as HTMLButtonElement[],i=tabs.indexOf(document.activeElement as HTMLButtonElement);tabs[e.key==='Home'?0:e.key==='End'?2:(i+(e.key==='ArrowRight'?1:2))%3].focus();});
new ResizeObserver(()=>charts.forEach(c=>c.resize())).observe(document.querySelector('main')!);
