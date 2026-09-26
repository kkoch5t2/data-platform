(() => {
  const dataEl = document.getElementById('financial-data');
  if (!dataEl || !window.echarts) return;
  const payload = JSON.parse(dataEl.textContent || '{}');
  const rows = payload.rows || [];
  const yen = value => {
    const n = Number(value || 0), a = Math.abs(n), sign = n < 0 ? '-' : '';
    if (a >= 1e12) return sign + (a / 1e12).toFixed(1) + '兆';
    if (a >= 1e8) return sign + (a / 1e8).toFixed(0) + '億';
    return sign + a.toLocaleString('ja-JP');
  };
  const pct = value => value == null ? '—' : (value >= 0 ? '+' : '') + Number(value).toFixed(1) + '%';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));

  let timeline = null;
  const timelineEl = document.getElementById('financial-timeline');
  if (timelineEl && rows.length) {
    timeline = echarts.init(timelineEl);
    timeline.setOption({
      tooltip:{trigger:'axis',valueFormatter:v=>yen(v)+'円'},
      legend:{top:0,data:[payload.revenueLabel,payload.profitLabel]},
      grid:{left:62,right:22,top:44,bottom:38},
      xAxis:{type:'category',data:rows.map(r=>(r.periodEnd||'').slice(0,4))},
      yAxis:{type:'value',axisLabel:{formatter:v=>yen(v)}},
      series:[
        {name:payload.revenueLabel,type:'bar',barMaxWidth:30,data:rows.map(r=>r.revenue)},
        {name:payload.profitLabel,type:'line',symbolSize:7,lineStyle:{width:3},data:rows.map(r=>r.profit)}
      ]
    });
  }

  let segmentChart = null;
  const segmentEl = document.getElementById('segment-treemap');
  if (segmentEl && (payload.segments || []).length >= 2) {
    const color = margin => margin == null ? '#d1d5db' : margin < 0 ? '#c92a2a' :
      `hsl(220 10% ${Math.max(16,88-Math.min(Number(margin),40)*1.65)}%)`;
    segmentChart = echarts.init(segmentEl);
    segmentChart.setOption({
      tooltip:{formatter:p=>{
        const d=p.data.raw;
        return `<b>${esc(d.name)}</b><br>売上高 ${yen(d.revenue)}円<br>`+
          `営業利益 ${d.operatingProfit==null?'—':yen(d.operatingProfit)+'円'}<br>`+
          `営業利益率 ${d.operatingMargin==null?'—':Number(d.operatingMargin).toFixed(1)+'%'}<br>`+
          `売上前年比 ${pct(d.revenueYoY)}<br>利益前年比 ${pct(d.profitYoY)}`;
      }},
      series:[{type:'treemap',roam:false,nodeClick:false,breadcrumb:{show:false},
        label:{show:true,formatter:'{b}'},upperLabel:{show:false},
        data:payload.segments.map(d=>({name:d.name,value:d.revenue,raw:d,
          itemStyle:{color:color(d.operatingMargin)},
          label:{color:d.operatingMargin!=null&&d.operatingMargin<6?'#111827':'#fff'}}))}]
    });
  }

  let ownershipChart = null;
  const ownershipEl = document.getElementById('ownership-network');
  if (ownershipEl && (payload.shareholders || []).length) {
    const holders=payload.shareholders;
    const nodes=[{
      id:'company',name:payload.companyName,symbolSize:68,
      itemStyle:{color:'#1769e0'},label:{show:true,color:'#fff',fontWeight:800}
    },...holders.map((h,i)=>({
      id:'h'+i,name:h.listedCompanyName||h.name,
      symbolSize:Math.min(58,30+Number(h.shareholdingRatio||0)*1.5),
      itemStyle:{color:h.listedSecurityCode?'#334155':'#94a3b8'},
      label:{show:true,fontSize:9,formatter:p=>p.name.length>18?p.name.slice(0,18)+'…':p.name},
      url:h.listedSecurityCode?`/listed-companies/${h.listedSecurityCode}/`:null,
      ratio:h.shareholdingRatio
    }))];
    const links=holders.map((h,i)=>({
      source:'h'+i,target:'company',value:h.shareholdingRatio,
      lineStyle:{width:Math.max(1,Math.min(8,Number(h.shareholdingRatio||0)/2)),opacity:.55}
    }));
    ownershipChart=echarts.init(ownershipEl);
    ownershipChart.setOption({
      tooltip:{formatter:p=>p.dataType==='edge'
        ?`持株比率 ${Number(p.data.value).toFixed(2)}%`
        :p.data.ratio!=null?`${esc(p.data.name)}<br>持株比率 ${Number(p.data.ratio).toFixed(2)}%`:esc(p.data.name)},
      series:[{type:'graph',layout:'force',roam:true,draggable:true,
        force:{repulsion:220,edgeLength:[90,180]},data:nodes,links,
        lineStyle:{curveness:.08},emphasis:{focus:'adjacency'}}]
    });
    ownershipChart.on('click',p=>{
      if(p.dataType==='node'&&p.data.url) location.href=p.data.url;
    });
  }

  window.addEventListener('resize',()=>{
    timeline?.resize();
    segmentChart?.resize();
    ownershipChart?.resize();
  });
})();
