'use strict';
function renderOverview(data) {
  const c=data.counts, threshold=data.model?.priority_threshold??80;
  $('#band option[value="high"]').textContent='High · ≥ '+threshold.toFixed(1);
  $('#band option[value="review"]').textContent='Review · ≥ '+(.75*threshold).toFixed(1);
  $('#band option[value="low"]').textContent='Low · < '+(.75*threshold).toFixed(1);
  const rows=data.timeline||[], chart=$('#activity-chart');
  chart.replaceChildren();
  if(rows.length) {
    const plot=svg('svg',{viewBox:'0 0 650 150',role:'img','aria-label':'Transaction counts by recorded UTC hour'});
    const maximum=Math.max(...rows.map(r=>r.transactions),1);
    // Combine contiguous observed buckets for legibility; never fabricate missing traffic.
    const stride=Math.max(1,Math.ceil(rows.length/48)), buckets=[];
    for(let i=0;i<rows.length;i+=stride) buckets.push({label:rows[i].hour,value:rows.slice(i,i+stride).reduce((n,r)=>n+r.transactions,0)});
    const peak=Math.max(...buckets.map(r=>r.value),1);
    for(let y=20;y<140;y+=40)plot.append(svg('line',{x1:0,y1:y,x2:650,y2:y,stroke:'#302b39','stroke-dasharray':'3 5'}));
    buckets.forEach((r,i)=>{
      const w=650/buckets.length,h=r.value/peak*118;
      const bar=svg('rect',{x:i*w+2,y:140-h,width:Math.max(2,w-5),height:h,rx:3,fill:i%4===0?'#bd91ff':'#7551a7'});
      const title=svg('title');title.textContent=r.label+' UTC: '+r.value+' transactions';bar.append(title);plot.append(bar);
    });
    chart.append(plot);
    $('#activity-caption').textContent=rows[0].hour.replace('T',' ')+' → '+rows.at(-1).hour.replace('T',' ')+' UTC · '+maximum+' peak / observed hour';
  } else chart.append(el('p','Import metadata to see transaction activity.','muted'));
  const box=$('#priority-chart');box.replaceChildren();
  const ratio=c.alerts?c.high_priority/c.alerts:0, ring=el('div',undefined,'priority-ring');
  ring.style.setProperty('--angle',(ratio*360)+'deg');
  const center=el('div');center.append(el('strong',Math.round(ratio*100)+'%'),el('small','HIGH PRIORITY'));ring.append(center);box.append(ring);
  const legend=el('div',undefined,'priority-legend');
  [['High',c.high_priority],['Review',c.review_priority],['Low',c.low_priority]].forEach(([label,n])=>{const r=el('div');r.append(el('span',label),el('strong',fmt(n)));legend.append(r);});box.append(legend);
  const comparison=$('#comparison-chart');comparison.replaceChildren();
  const baselines=data.evaluation?.baselines;
  if(!baselines)comparison.append(el('p','No held-out evaluation attached.','muted'));
  else {
    [['chain_only_ml','Chain-only ML'],['fused_ml','Fused ML'],['fused_priority','Fused priority']].forEach(([key,label])=>{
      const value=baselines[key]?.precision_at_20;if(value==null)return;
      const row=el('div',undefined,'feature');row.append(el('span',label),el('strong',Math.round(value*100)+'%'));
      const bar=el('div',undefined,'bar'),fill=el('i');fill.style.width=value*100+'%';bar.append(fill);comparison.append(row,bar);
    });
    comparison.append(el('p','Precision@20 · held-out synthetic fixtures only','chart-caption'));
  }
}
