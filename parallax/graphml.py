"""Two-layer, sampled mean GraphSAGE on a provenance-labelled address projection.

Training labels are explicit. Graph construction never uses labels, IDs as features,
or test-set statistics. Inference applies frozen weights to unseen graphs.
"""
import numpy as np
import torch
from torch import nn

from .features import FEATURES, matrix


class GraphSAGE(nn.Module):
    def __init__(self, width, hidden=24):
        super().__init__()
        self.first = nn.Linear(width*2, hidden)
        self.second = nn.Linear(hidden*2, hidden)
        self.classifier = nn.Linear(hidden, 1)

    def forward(self, x, neighbors, mask):
        def aggregate(h):
            return (h[neighbors]*mask[:,:,None]).sum(1)/mask.sum(1).clamp(min=1)[:,None]
        h = torch.relu(self.first(torch.cat((x,aggregate(x)),1)))
        h = torch.relu(self.second(torch.cat((h,aggregate(h)),1)))
        return self.classifier(h).squeeze(1), h


def neighborhood(rows, count=16):
    index={r['address']:i for i,r in enumerate(rows)}
    edges=[set() for _ in rows]
    for i,r in enumerate(rows):
        for a in r.get('entity_members',[]):
            if a in index and index[a]!=i: edges[i].add(index[a])
        for a in r.get('network_associations',[]):
            other=a['target'] if a['source']==r['address'] else a['source']
            if other in index:
                edges[i].add(index[other]); edges[index[other]].add(i)
    neighbors=np.zeros((len(rows),count),dtype=np.int64)
    mask=np.zeros((len(rows),count),dtype=np.float32)
    for i,values in enumerate(edges):
        selected=sorted(values)[:count]
        neighbors[i,:len(selected)]=selected
        mask[i,:len(selected)]=1
    return torch.tensor(neighbors),torch.tensor(mask)


def fit_graph(rows, labels, seed=41, epochs=100):
    torch.set_num_threads(1); torch.manual_seed(seed)
    if set(labels)!=set(r['address'] for r in rows):
        raise ValueError('Graph training labels must exactly match training input profiles')
    y=torch.tensor([labels[r['address']]['label'] for r in rows],dtype=torch.float32)
    if set(y.tolist())!={0.,1.}: raise ValueError('Graph classifier needs both classes')
    x=matrix(rows); mean=x.mean(0); scale=np.maximum(x.std(0),1e-6)
    x=torch.tensor(np.clip((x-mean)/scale,-10,10),dtype=torch.float32)
    neighbors,mask=neighborhood(rows)
    model=GraphSAGE(len(FEATURES))
    optimizer=torch.optim.Adam(model.parameters(),lr=.008,weight_decay=.01)
    lossfn=nn.BCEWithLogitsLoss(pos_weight=(len(y)-y.sum())/y.sum())
    for _ in range(epochs):
        optimizer.zero_grad(); logits,_=model(x,neighbors,mask)
        loss=lossfn(logits,y); loss.backward(); optimizer.step()
    return {'state':{k:v.detach().numpy() for k,v in model.state_dict().items()},'mean':mean,'scale':scale,
            'training_loss':float(loss.detach()),'epochs':epochs,'neighbor_limit':16,
            'scope':'Labelled training distribution; graph classifier output is uncalibrated',
            'training_edges':int(mask.sum().item())}


def infer_graph(rows, bundle):
    if not bundle: return None, None
    model=GraphSAGE(len(FEATURES))
    model.load_state_dict({k:torch.tensor(v) for k,v in bundle['state'].items()})
    x=torch.tensor(np.clip((matrix(rows)-bundle['mean'])/bundle['scale'],-10,10),dtype=torch.float32)
    neighbors,mask=neighborhood(rows)
    model.eval()
    with torch.no_grad(): logits,embedding=model(x,neighbors,mask)
    return torch.sigmoid(logits).numpy(),embedding.numpy()
