"""Minimal independent supplements to a declared grouping, never blanket fixes.

The supported Jacobian is a planning aid. Native solver, pose and motion gates
remain mandatory; omitted native constraints cannot be certified by this model.
"""
import math
from . import assembly_constraints as ac


class SparseBasis:
    def __init__(self):
        self.pivots={}

    def add(self, row, commit=True):
        v={i:x for i,x in row.items() if abs(x)>1e-12}
        n=math.sqrt(sum(x*x for x in v.values()))
        if n<1e-12:return False
        v={i:x/n for i,x in v.items()}
        for pivot,b in self.pivots.items():
            k=v.get(pivot,0)
            if abs(k)<1e-12:continue
            for i,x in b.items():
                value=v.get(i,0)-k*x
                if abs(value)>1e-12:v[i]=value
                else:v.pop(i,None)
        if not v:return False
        # Choosing the first spatial column amplified nearly-zero direction
        # cosines by 1e8 and created false residual freedoms. Full row pivoting
        # and back elimination keep every existing pivot column reduced.
        pivot=max(v,key=lambda i:abs(v[i]));k=v[pivot]
        if abs(k)<1e-8:return False
        if commit:
            new={i:x/k for i,x in v.items()}
            for other,row in list(self.pivots.items()):
                factor=row.get(pivot,0)
                if abs(factor)>1e-12:
                    updated=dict(row)
                    for i,x in new.items():
                        value=updated.get(i,0)-factor*x
                        if abs(value)>1e-12:updated[i]=value
                        else:updated.pop(i,None)
                    self.pivots[other]=updated
            self.pivots[pivot]=new
        return True

    def trial(self, rows):
        old=self.pivots.copy()
        delta=sum(self.add(row) for row in rows)
        self.pivots=old
        return delta


def declared_groups(components, intent):
    """Exact names, complete disjoint ownership; no substring substitutions."""
    if not isinstance(intent,dict) or 'stationary' not in intent or not 1<=len(intent)<=128 or any(not isinstance(k,str) or not 1<=len(k)<=64 for k in intent):
        raise ValueError('intent_requires_named_groups_and_stationary_reference')
    by_name={}
    for c in components:by_name.setdefault(c['instance'].casefold(),[]).append(c['component_id'])
    groups={};seen=set()
    for key,names in intent.items():
        if not isinstance(names,list) or not names:raise ValueError('empty_or_invalid_intent_group')
        groups[key]=[]
        for name in names:
            if not isinstance(name,str) or len(by_name.get(name.casefold(),[]))!=1:raise ValueError('intent_name_not_unique')
            cid=by_name[name.casefold()][0]
            if cid in seen:raise ValueError('intent_groups_overlap')
            seen.add(cid);groups[key].append(cid)
    if seen!={c['component_id'] for c in components}:raise ValueError('intent_inventory_incomplete')
    if not any(c.get('fixed_component') for c in components if c['component_id'] in groups['stationary']):
        raise ValueError('stationary_group_has_no_existing_ground')
    return groups


def plan(survey, groups, anchors):
    cs=survey['components'];ids={c['component_id']:i for i,c in enumerate(cs)}
    if 'stationary' not in groups or set(anchors)!=set(groups) or any(not members for members in groups.values()):raise ValueError('invalid_declared_groups')
    labels={cid:label for label,members in groups.items() for cid in members}
    if len(labels)!=sum(map(len,groups.values())) or set(labels)!=set(ids):raise ValueError('incomplete_or_overlapping_groups')
    if any(anchors[label] not in members for label,members in groups.items()):raise ValueError('invalid_group_anchor')
    origin,scale=ac._frame(cs);matrix=SparseBasis();omitted=[]
    def lifted(rows,a,b=None):
        result=[]
        for row in rows:
            data={6*ids[a]+i:x for i,x in enumerate(row) if abs(x)>1e-12}
            if b is not None:
                data.update({6*ids[b]+i:-x for i,x in enumerate(row) if abs(x)>1e-12})
            result.append(data)
        return result
    for c in cs:
        if c.get('fixed_component') and labels[c['component_id']]=='stationary':
            for row in lifted([[float(i==j) for i in range(6)] for j in range(6)],c['component_id']):matrix.add(row)
    for m in survey['mates']:
        if m.get('suppressed') is not False or type(m.get('error')) is not int or m['error']!=0 or m.get('warning'):continue
        es=m.get('entities') or [];cids=[e.get('component_id') for e in es]
        if len(es)!=2 or len(set(cids))!=2 or any(cid not in ids for cid in cids):
            omitted.append(m.get('native_feature_id'));continue
        try:rows=ac._rows(m,es,origin,scale)
        except (ValueError,KeyError,TypeError):omitted.append(m.get('native_feature_id'));continue
        for row in lifted(rows,*cids):matrix.add(row)
    initial_rank=len(matrix.pivots)
    structure=survey.get('structural_relations') or {}
    pattern_ids={c['component_id'] for c in structure.get('components',[]) if c.get('is_pattern_instance')}
    planes={c['component_id']:c.get('completion_planes',[]) for c in cs}
    actions=[];uncompleted=[]
    for label in ['stationary']+sorted(set(groups)-{'stationary'}):
        anchor=anchors[label]
        # Existing relations are never suppressed. Pattern instances are never
        # individually constrained just because direct mate references are few.
        for cid in groups[label]:
            if cid==anchor or cid in pattern_ids:continue
            target=lifted([[float(i==j) for i in range(6)] for j in range(6)],cid,anchor)
            needed=matrix.trial(target)
            if not needed:continue
            native_links=[m for m in survey['mates'] if m.get('suppressed') is not True and any(e.get('component_id')==cid for e in m.get('entities',[]))]
            if not native_links:
                # A genuinely unmated seed can be attached by one native rigid
                # mate. This does not fix it to the world or suppress old mates.
                for row in target:matrix.add(row)
                actions.append({'kind':'rigid_lock','component_a':cid,'component_b':anchor,'group':label,
                    'reference_a':cid,'reference_b':anchor,'reference_kind_a':'component','reference_kind_b':'component',
                    'independent_constraint_gain':needed,'value':None,
                    'reason':'unmated_nonpattern_seed_attach_to_declared_group_without_fixing'})
                continue
            candidates=[]
            for a in planes.get(cid,[]):
                for b in planes.get(anchor,[]):
                    na,nb=ac.unit(a['axis_global']),ac.unit(b['axis_global'])
                    cosine=max(-1,min(1,ac.dot(na,nb)))
                    if abs(cosine)>1-1e-8:
                        rows=[[0.,0.,0.]+list(v) for v in ac.perpendiculars(na)]
                        candidates.append((0,'parallel',a,b,rows,None))
                        p=[(b['reference_point_global_m'][i]-origin[i])/scale for i in range(3)]
                        rows=rows+[na+ac.cross(p,na)]
                        distance=abs(ac.dot(na,[a['reference_point_global_m'][i]-b['reference_point_global_m'][i] for i in range(3)]))
                        candidates.append((2,'distance',a,b,rows,distance))
                    else:
                        normal=ac.unit(ac.cross(na,nb))
                        kind='perpendicular' if abs(cosine)<1e-8 else 'angle'
                        candidates.append((0 if kind=='perpendicular' else 1,kind,a,b,[[0.,0.,0.]+normal],math.acos(cosine)))
            while matrix.trial(target):
                options=[]
                for priority,kind,a,b,rows,value in candidates:
                    lifted_rows=lifted(rows,cid,anchor);delta=matrix.trial(lifted_rows)
                    if delta:options.append((priority,delta,kind,a,b,lifted_rows,value))
                if not options:break
                priority,delta,kind,a,b,rows,value=min(options,key=lambda r:(-r[1],r[0],r[2],r[3]['native_reference'],r[4]['native_reference']))
                for row in rows:matrix.add(row)
                actions.append({'kind':kind,'component_a':cid,'component_b':anchor,'group':label,
                    'reference_a':a['native_reference'],'reference_b':b['native_reference'],
                    'reference_kind_a':a['reference_kind'],'reference_kind_b':b['reference_kind'],
                    'independent_constraint_gain':delta,'value':value,
                    'reason':'supplement_declared_rigid_group_keep_existing_mates_and_current_pose'})
            if matrix.trial(target):uncompleted.append(cid)
    # A part processed before its support may become fully constrained when
    # later supplements anchor that support. Judge completeness at the end.
    uncompleted=[cid for label,members in groups.items() for cid in members if cid!=anchors[label] and cid not in pattern_ids
                 and matrix.trial(lifted([[float(i==j) for i in range(6)] for j in range(6)],cid,anchors[label]))]
    return {'schema_version':1,'groups':groups,'anchors':anchors,'actions':actions,
        'initial_supported_rank':initial_rank,'planned_supported_rank':len(matrix.pivots),
        'uncompleted_components':uncompleted,'omitted_native_feature_ids':omitted,
        'reused_pattern_component_ids':sorted(pattern_ids),'pattern_motion_verified':False,
        'fixed_state_changes':[],'existing_mates_suppressed':[],'existing_mates_deleted':[],
        'minimality_scope':'greedy_independent_supplements_not_proven_global_minimum_mate_count',
        'requires_explicit_confirmation':True,'native_compatibility_verified':False,
        'motion_verified':False,'write_dispatched':False}
