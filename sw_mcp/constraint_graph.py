"""Whole-inventory, instantaneous supported-constraint evidence.

This projection includes indirect constraints. Its null space is a planning
aid, never a certificate of finite mobility, design intent or CAD health.
The cached input is the entire immutable JSON snapshot; no COM is retained.
"""
from functools import lru_cache
import copy
import json
import math
from . import assembly_constraints as ac
from .assembly_completion import SparseBasis


def _complement(rows):
    result=[];basis=ac.basis(rows)
    for i in range(6):
        v=[float(i==j) for j in range(6)]
        for _ in range(2):
            for b in basis+result:
                k=ac.dot(v,b);v=[x-k*y for x,y in zip(v,b)]
        n=math.sqrt(ac.dot(v,v))
        if n>1e-8:result.append([x/n for x in v])
    return result


class Graph:
    def __init__(self,survey):
        cs=survey['components'];ids=[c['component_id'] for c in cs]
        if not survey.get('inventory_complete') or not 1<=len(ids)<=128 or len(set(ids))!=len(ids):
            raise ValueError('graph_requires_complete_unique_inventory')
        self.survey=survey;self.ids=ids;self.index={cid:i for i,cid in enumerate(ids)}
        self.by_id={c['component_id']:c for c in cs};self.origin,self.scale=ac._frame(cs)
        self.matrix=SparseBasis();self.direct={};self.unknown=[];self.inactive=[]
        self.adj={cid:set() for cid in ids};self.links={cid:[] for cid in ids}
        self.ground_links=[];self.pairs={}
        self.patterns={c['component_id'] for c in (survey.get('structural_relations') or {}).get('components',[]) if c.get('is_pattern_instance') is True}
        for c in cs:
            if c.get('fixed_component') is True:
                for row in self.lift([[float(i==j) for j in range(6)] for i in range(6)],c['component_id']):self.matrix.add(row)
        for mate in survey['mates']:
            mid=mate.get('native_feature_id')
            if mate.get('suppressed') is True:self.inactive.append(mid);continue
            es=mate.get('entities') or [];cids=[e.get('component_id') for e in es]
            present=list(dict.fromkeys(cid for cid in cids if cid in self.index))
            for cid in present:
                self.links[cid].append(mid);self.adj[cid].update(set(present)-{cid})
            reason=None
            if mate.get('suppressed') is not False or type(mate.get('error')) is not int or mate.get('error')!=0 or mate.get('warning'):
                reason='native_activity_or_health_requires_review'
            elif len(es)!=2 or len(set(cids))!=2:reason='not_two_distinct_native_references'
            else:
                root=[i for i,e in enumerate(es) if e.get('reference_owner_scope')=='assembly_root' and e.get('root_reference_verified') is True]
                if len(present)==2:a,b=cids
                elif len(present)==1 and len(root)==1 and cids[root[0]] not in self.index:
                    a=present[0];b=None
                else:reason='reference_outside_observed_inventory_or_unverified_root'
            if reason is None:
                try:rows=ac._rows(mate,es,self.origin,self.scale)
                except (ValueError,KeyError,TypeError) as error:reason=str(error)
            if reason:
                self.unknown.append({'native_feature_id':mid,'reason':reason,'components':present});continue
            if b is None:self.ground_links.append({'component_id':a,'native_feature_id':mid})
            else:
                key=tuple(sorted((a,b)));self.direct.setdefault(key,[]).extend(rows)
            for row in self.lift(rows,a,b):self.matrix.add(row)

    def lift(self,rows,a,b=None):
        return [{**{6*self.index[a]+i:x for i,x in enumerate(row) if abs(x)>1e-12},
                 **({6*self.index[b]+i:-x for i,x in enumerate(row) if abs(x)>1e-12} if b is not None else {})} for row in rows]

    def relative(self,a,b=None):
        key=(a,b)
        if key not in self.pairs:
            residual=[]
            for row in self.lift([[float(i==j) for j in range(6)] for i in range(6)],a,b):
                residual.append(self._reduce(row))
            columns=set().union(*(set(r) for r in residual))
            free=ac.basis([[r.get(col,0.) for r in residual] for col in sorted(columns)])
            rows=_complement(free)
            direct=self.direct.get(tuple(sorted((a,b))),[]) if b is not None else []
            self.pairs[key]={'rows':rows,'free_basis':free,'supported_effective_rank':len(rows),
                'supported_direct_rank':len(ac.basis(direct)),
                'indirect_constraint_gain':len(rows)-len(ac.basis(direct)),
                'scope':'supported_instantaneous_whole_inventory_projection',
                'global_DOF_certified':False,'finite_motion_verified':False,
                'omitted_native_feature_ids':[r['native_feature_id'] for r in self.unknown]}
        return copy.deepcopy(self.pairs[key])

    def _reduce(self,row):
        v=dict(row)
        for pivot,basis in self.matrix.pivots.items():
            factor=v.get(pivot,0.)
            if abs(factor)<1e-12:
                v.pop(pivot,None);continue
            for col,x in basis.items():
                value=v.get(col,0.)-factor*x
                if abs(value)>1e-12:v[col]=value
                else:v.pop(col,None)
        return v

    def missing_target(self,rows,a,b=None):
        # The cached model is shared by read-only pages and background plans.
        # Never call the mutating SparseBasis.trial on its shared matrix.
        trial=SparseBasis();trial.pivots=self.matrix.pivots.copy()
        return sum(trial.add(row) for row in self.lift(rows,a,b))

    def rank(self,a,b=None):
        if (a,b) not in self.pairs:self.relative(a,b)
        return self.pairs[(a,b)]['supported_effective_rank']

    def report(self):
        groups=[];remaining=set(self.ids)
        for a in self.ids:
            if a not in remaining:continue
            group=[a]+[b for b in self.ids if b!=a and b in remaining and self.relative(a,b)['supported_effective_rank']==6]
            remaining.difference_update(group)
            if len(group)>1:groups.append({'components':sorted(group),'instances':[self.by_id[c]['instance'] for c in sorted(group)],
                'relation':'supported_instantaneous_rigid_group_not_motion_certificate'})
        islands=[];remaining=set(self.ids)
        while remaining:
            todo=[min(remaining)];seen=set()
            while todo:
                cid=todo.pop()
                if cid in seen:continue
                seen.add(cid);todo.extend(self.adj[cid]-seen)
            remaining.difference_update(seen);islands.append(sorted(seen))
        nodes=[]
        for cid in self.ids:
            grounded=self.relative(cid)['supported_effective_rank']==6
            nodes.append({'component_id':cid,'instance':self.by_id[cid]['instance'],
                'native_fixed_flag':self.by_id[cid].get('fixed_component'),
                'supported_ground_rigidity':grounded,'active_native_feature_ids':self.links[cid],
                'no_observed_active_native_links':not self.links[cid],
                'native_pattern_instance':cid in self.patterns,
                'no_observed_constraint_or_pattern_relation':not self.links[cid] and cid not in self.patterns,
                'native_constraint_state':self.by_id[cid].get('constraint_state'),
                'mechanical_role':None,'motion_verified':False})
        result={'schema_version':1,'status':'supported_graph_with_unknowns' if self.unknown else 'supported_graph_ready',
            'scope':'complete_inventory_supported_instantaneous_constraints_not_global_DOF_or_intent',
            'component_count':len(self.ids),'supported_constraint_rank':len(self.matrix.pivots),
            'rigid_groups':groups,'native_link_islands':islands,'components':nodes,
            'island_scope':'observed_native_mate_links_only_not_pattern_or_whole_mechanism_disconnection',
            'pattern_relations_observed_not_rigid_motion_proof':sorted(self.patterns),
            'verified_root_links':self.ground_links,'unknown_constraints':self.unknown,'suppressed_feature_ids':self.inactive,
            'nonlinear_constraint_observations':self.survey.get('nonlinear_constraints',[]),
            'unknown_constraints_treated_as_absent':False,'mechanical_intent_proven':False,
            'global_DOF_certified':False,'motion_verified':False,'write_dispatched':False}
        return copy.deepcopy(result)


@lru_cache(maxsize=2)
def _snapshot(text):
    return Graph(json.loads(text))


def model(survey):
    return _snapshot(json.dumps(survey,sort_keys=True,separators=(',',':'),allow_nan=False))


def report(survey):
    return model(survey).report()
