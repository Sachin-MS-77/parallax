"""Evidence-backed hypotheses. No network edge establishes ownership."""
import hashlib
import json
from collections import Counter, defaultdict, deque
from datetime import datetime

from .storage import get_meta


def context(db, window=60, hub_limit=20):
    transactions = [dict(r) for r in db.execute('SELECT * FROM transactions ORDER BY first_seen,txid')]
    txs = {t['txid']: json.loads(t['chain_json']) for t in transactions}
    times = {t['txid']: t['first_seen'] for t in transactions}
    parents, reasons, candidates = {}, [], []
    outgoing, incoming, address_txs = defaultdict(set), defaultdict(set), defaultdict(set)
    def root(a):
        parents.setdefault(a, a)
        while parents[a] != a:
            parents[a] = parents[parents[a]]
            a = parents[a]
        return a
    def union(a, b):
        a, b = root(a), root(b)
        parents[max(a,b)] = min(a,b)
    mixers, reused, peel = set(), set(), set()
    seen = set()
    for t in transactions:
        txid = t['txid']; c = txs[txid]
        inputs, outputs = c['input_addresses'], c['output_addresses']
        collaborative = len(inputs) > 1 and max(Counter(c['output_sats']).values(), default=0) >= 3
        if collaborative:
            mixers.add(txid)
        for a in inputs + outputs:
            root(a); address_txs[a].add(txid)
        if 1 < len(set(inputs)) <= 20 and not collaborative:
            for a in inputs[1:]: union(inputs[0], a)
            reasons.append({'method':'common_input', 'txid':txid, 'addresses':inputs,
                            'confidence':'heuristic', 'caveat':'PayJoin and other collaborative spends can invalidate ownership inference.'})
        # Change is retained as a weak candidate, never automatically unioned.
        new_outputs = [a for a in outputs if a not in seen and a not in inputs]
        if len(inputs) == 1 and len(outputs) == 2 and len(new_outputs) == 1:
            candidates.append({'source':inputs[0], 'target':new_outputs[0], 'txid':txid,
                               'method':'single_new_output_change', 'confidence':'weak', 'merged':False})
        if any(a in seen for a in outputs): reused.add(txid)
        for a in inputs:
            outgoing[a].update(outputs)
        for a in outputs: incoming[a].update(inputs)
        seen.update(inputs + outputs)
    # A peel-like sequence must have connected, time-ordered 2-output transactions.
    peel_next = {}
    for txid, c in txs.items():
        if len(c['input_addresses']) == 1 and len(c['output_addresses']) == 2:
            j = max(range(2), key=lambda j:c['output_sats'][j])
            if c['output_sats'][j] / max(sum(c['output_sats']),1) >= .70:
                peel_next[c['input_addresses'][0]] = (c['output_addresses'][j], txid)
    for a in peel_next:
        path, visited, current, previous = [], set(), a, ''
        while current in peel_next and current not in visited and len(path) < 30:
            visited.add(current)
            nxt, txid = peel_next[current]
            if times[txid] < previous: break
            previous = times[txid]; path.append(txid); current = nxt
        if len(path) >= 3: peel.update(path)
    groups = defaultdict(list)
    for a in parents: groups[root(a)].append(a)
    entities, memberships = [], {}
    for members in groups.values():
        members.sort()
        eid = 'entity:' + hashlib.sha256('|'.join(members).encode()).hexdigest()[:16]
        entities.append({'id':eid, 'members':members, 'basis':'common-input hypothesis' if len(members)>1 else 'single address',
                         'ownership_verified':False})
        for a in members: memberships[a] = eid
    first_by_ip = defaultdict(list)
    for r in db.execute('SELECT txid,src_ip,MIN(timestamp) AS stamp FROM observations WHERE src_ip IS NOT NULL GROUP BY txid,src_ip ORDER BY stamp'):
        first_by_ip[r['src_ip']].append((datetime.fromisoformat(r['stamp']).timestamp(),r['txid']))
    associations, suppressed = [], 0
    for ip, observations in first_by_ip.items():
        if len(observations)>hub_limit:
            suppressed += 1; continue
        for i,(stamp,txid) in enumerate(observations):
            for otherstamp,othertx in observations[i+1:]:
                if otherstamp-stamp>window: break
                for a in txs[txid]['input_addresses']:
                    for b in txs[othertx]['input_addresses']:
                        if a != b:
                            associations.append({'source':a,'target':b,'ip':ip,'txids':[txid,othertx],
                                                 'delta_seconds':round(otherstamp-stamp,6),'confidence':'weak',
                                                 'method':'shared_first_observed_relay','ownership_claim':False})
    seeds = get_meta(db,'seed_addresses',[])
    distance = {s['address']:0 for s in seeds}
    queue = deque(distance)
    while queue:
        a = queue.popleft()
        if distance[a]>=6: continue
        for b in outgoing[a]:
            if b not in distance: distance[b]=distance[a]+1; queue.append(b)
    return {'entities':entities,'membership':memberships,'cluster_evidence':reasons,'change_candidates':candidates,
            'associations':associations,'suppressed_hubs':suppressed,'outgoing':outgoing,'incoming':incoming,
            'mixers':mixers,'reused':reused,'peel':peel,'seed_distance':distance,'seeds_available':bool(seeds),
            'address_txs':address_txs}


def enrich_profile(profile, ctx, records):
    import math
    import numpy as np
    txids = profile['txids']; stamps = [datetime.fromisoformat(r['first_seen']) for r in records]
    chains = [json.loads(r['chain_json']) for r in records]
    gaps = np.diff([t.timestamp() for t in stamps])
    bins = Counter(int(math.log2(max(1,g))) for g in gaps)
    entropy = -sum((v/max(1,len(gaps)))*math.log2(v/max(1,len(gaps))) for v in bins.values())
    hours = Counter(t.hour for t in stamps)
    outs = [v for c in chains for v in c['output_sats']]
    rates = [c['fee_sats']/c['vsize'] for c in chains if c.get('vsize')]
    address=profile['address']; distance=ctx['seed_distance'].get(address)
    related=[a for a in ctx['associations'] if address in (a['source'],a['target'])]
    extra={'in_degree':len(ctx['incoming'][address]),'out_degree':len(ctx['outgoing'][address]),
           'seed_hop_distance':distance if distance is not None else 7,
           'seed_evidence_available':int(ctx['seeds_available']),
           'round_output_ratio':sum(v%1000000==0 for v in outs)/max(1,len(outs)),
           'interval_entropy':entropy,'hour_concentration':max(hours.values())/len(stamps),
           'fee_rate_cv':float(np.std(rates)/max(np.mean(rates),1e-8)) if rates else 0,
           'fee_rate_available':int(bool(rates)),'relay_associations':len(related)}
    profile['features'].update(extra)
    profile['entity_id']=ctx['membership'][address]
    profile['entity_members']=next(e['members'] for e in ctx['entities'] if e['id']==profile['entity_id'])
    for name, hits, strength, reason in (
        ('Peeling-chain pattern',ctx['peel'],.85,'Connected, time-ordered 2-output sequence with dominant continuation outputs; a payment workflow is an alternative.'),
        ('Address reuse',ctx['reused'],.30,'An output address appeared earlier in this dataset; reuse alone is not illicit.'),
        ('CoinJoin-like shape',ctx['mixers'],.35,'Multiple inputs and 3+ equal outputs; privacy-preserving collaborative spending is a benign explanation.')):
        evidence=sorted(set(txids)&hits)
        if evidence: profile['rules'].append({'name':name,'strength':strength,'reason':reason,'txids':evidence})
    if profile['features']['max_fan_in']>=8:
        profile['rules'].append({'name':'High fan-in','strength':.55,'reason':'8+ inputs; consolidation can be benign.','txids':txids})
    profile['rule_score']=max((r['strength'] for r in profile['rules']),default=0)
    profile['seed_distance']=distance
    profile['network_associations']=related[:50]
    profile['caveats'].append('Entity membership is a revisable heuristic; change and relay candidates are not merged.')
    return profile
