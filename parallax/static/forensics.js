'use strict';
function renderForensics(a) {
  const d=$('#forensics');d.replaceChildren();
  d.append(el('h3','Evidence-derived case note'),el('p',a.case_note||'Rescore this case to generate the new forensic analysis.'));
  if(!a.taint)return;
  d.append(el('h3','Fracture Index'),el('p',a.priority+' / 100 · '+a.confidence_band+' score band'));
  d.append(el('p','Bands describe priority, not statistical confidence or criminality.','muted'));
  d.append(el('h3','Haircut seed exposure'),el('p',a.taint.available?(100*a.taint.fraction).toFixed(1)+'% estimated decayed exposure':'No seed set supplied.'));
  for(const s of a.taint.sources||[])d.append(el('p',s.source+' · '+s.hops+' hops','mono'));
  d.append(el('h3','Behavioral changepoints'),el('p',a.behavioral_drift.status.replaceAll('_',' ')));
  for(const c of a.behavioral_drift.changes)d.append(el('p',c.timestamp+' · shift '+c.standardized_shift));
  d.append(el('h3','Likely cash-out targets (unverified)'));
  if(!a.cashout_targets.length)d.append(el('p','No supported candidate in the observed downstream graph.','muted'));
  for(const t of a.cashout_targets){d.append(el('p',t.address,'mono'),el('p',t.basis+' · '+t.hops+' hops'),el('p',t.caveat,'muted'));}
}
async function loadWeights(){
  const c=await api('/api/fracture-config'),box=$('#weights');box.replaceChildren(el('p','Weight configuration v'+c.version,'muted'));
  for(const [k,v] of Object.entries(c.weights)){const row=el('div',undefined,'feature');row.append(el('span',k.replaceAll('_',' ')),el('strong',(100*v).toFixed(2)+'%'));box.append(row);}
}
document.addEventListener('DOMContentLoaded',()=>{
  run(loadWeights)();
  $('#attempt-evasion').addEventListener('click',run(async()=>{
    const button=$('#attempt-evasion');button.disabled=true;
    try{
      message('Running one synthetic evasion round…');
      const result=await api('/api/evasion',{method:'POST'}),box=$('#evasion-result');box.replaceChildren(el('p',result.scope,'muted'));
      const table=el('table'),head=el('tr');['Synthetic actor','Technique','Before','After','Change'].forEach(x=>head.append(el('th',x)));table.append(head);
      for(const a of result.after.actors){const b=result.before.actors.find(x=>x.actor===a.actor);const row=el('tr');[a.actor,a.technique,b.priority.toFixed(2),a.priority.toFixed(2),(a.priority-b.priority).toFixed(2)].forEach(x=>row.append(el('td',x)));table.append(row);}
      box.append(table,el('p',result.mutations.length+' flagged actors mutated. Misses and non-decreasing scores are retained.'));
      message('Evasion round complete. Results belong to a separate synthetic sandbox.');
    }finally{button.disabled=false;}
  }));
});
