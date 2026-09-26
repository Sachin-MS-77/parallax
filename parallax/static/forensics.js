'use strict';
function renderForensics(a) {
  const d=$('#forensics');d.replaceChildren();
  const integrity=el('div',undefined,'integrity-badge '+(summary.integrity?.valid?'verified':'review'));integrity.textContent=summary.integrity?.valid?'✓ Evidence chain verified':'! Evidence chain requires review';d.append(integrity,el('h3','Case identity'),el('p',a.entity_id||'Unresolved entity','mono'),el('p',`Hypothesis confidence: ${a.entity_members?.length>1?'candidate multi-address cluster':'single-address profile'} · ownership is unverified.`,'muted'));
  d.append(el('h3','Competing entity hypotheses'));
  const members=a.entity_members||[];
  d.append(el('p',members.length>1?`${members.length} addresses share a candidate entity. Review each merge signal before treating them as one actor.`:'No merge was asserted; this address remains an independent profile.','muted'));
  for(const member of members.slice(0,8))d.append(el('p',member,'mono'));
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
  const evasionButton=$('#attempt-evasion');const picker=document.createElement('select');picker.id='evasion-technique';picker.setAttribute('aria-label','Red-team technique');['all','peel_chain','fan_out','mixer_hops','timing_jitter'].forEach(x=>{const option=document.createElement('option');option.value=x;option.textContent=x==='all'?'All techniques':x.replaceAll('_',' ');picker.append(option);});evasionButton.parentNode.insertBefore(picker,evasionButton);
  $('#attempt-evasion').addEventListener('click',run(async()=>{
    const button=$('#attempt-evasion');button.disabled=true;
    try{
      message('Running one synthetic evasion round…');
      const result=await api('/api/evasion',{method:'POST'}),box=$('#evasion-result');box.replaceChildren(el('p',result.scope,'muted'));
      const table=el('table'),head=el('tr');['Synthetic actor','Technique','Before','After','Change'].forEach(x=>head.append(el('th',x)));table.append(head);
      const technique=picker.value;for(const a of result.after.actors){if(technique!=='all'&&a.technique!==technique)continue;const b=result.before.actors.find(x=>x.actor===a.actor);const row=el('tr');[a.actor,a.technique,b.priority.toFixed(2),a.priority.toFixed(2),(a.priority-b.priority).toFixed(2)].forEach(x=>row.append(el('td',x)));table.append(row);}
      box.append(table,el('p',result.mutations.length+' flagged actors mutated. Misses and non-decreasing scores are retained.','muted'),el('p',`Displayed technique filter: ${technique==='all'?'all techniques':technique.replaceAll('_',' ')}. Results remain in the separate synthetic sandbox.`,'muted'));
      message('Evasion round complete. Results belong to a separate synthetic sandbox.');
    }finally{button.disabled=false;}
  }));
});
