"""Single-mate leave-one-out review of supported local constraint rows."""
import ntpath
from collections import Counter, defaultdict

from . import assembly_constraints as ac, mirror_connections

MATE_TYPE_NAMES={0:'coincident',1:'concentric',2:'perpendicular',3:'parallel',5:'distance'}


def _pair_rows(inspection):
    components=inspection['components']
    if not components:return {}
    names={c['component_id']:c['instance'] for c in components}
    try:frame=ac._frame(components)
    except (TypeError,ValueError,KeyError):return {}
    pairs=defaultdict(list)
    incomplete=set()
    for mate in inspection.get('mates',[]):
        if mate.get('suppressed') is True:continue
        entities=mate.get('entities') or []
        members=tuple(sorted({e.get('component_id') for e in entities if e.get('component_id') in names}))
        if len(members)!=2:continue
        if len(entities)!=2 or mate.get('suppressed') is not False or mate.get('error')!=0 or mate.get('warning'):
            incomplete.add(members)
            continue
        try:rows=ac._rows(mate,entities,*frame)
        except (ValueError,TypeError,KeyError):
            incomplete.add(members)
            continue
        pairs[members].append((mate,rows))
    return {members:pair for members,pair in pairs.items() if members not in incomplete}


def review(inspection):
    names={c['component_id']:c['instance'] for c in inspection['components']}
    result=[]
    for members,pair in _pair_rows(inspection).items():
        if len(pair)<2:continue
        rank=len(ac.basis([r for _,rows in pair for r in rows]))
        for index,(mate,_) in enumerate(pair):
            reduced=len(ac.basis([r for pos,(_,rows) in enumerate(pair) if pos!=index for r in rows]))
            if reduced==rank:
                result.append({'native_feature_id':mate['native_feature_id'],'name':mate['name'],
                    'component_ids':list(members),'components':[names[c] for c in members],
                    'local_rank':rank,'rank_without_this_single_mate':reduced,
                    'scope':'local_linearized_candidate_not_proven_solver_conflict',
                    'automatic_suppression_allowed':False})
    return result


def axial_variations(inspection):
    """Compare repeated identical part pairs; verify axial freedom in local rows."""
    by_id={c['component_id']:c for c in inspection['components']}
    groups=defaultdict(list)
    for members,pair in _pair_rows(inspection).items():
        components=[by_id[c] for c in members]
        if not all(c.get('path') and c.get('configuration') and not c.get('subassembly') for c in components):continue
        key=tuple(sorted((ntpath.normcase(c['path']),c['configuration']) for c in components))
        supported=ac.basis([row for _,rows in pair for row in rows])
        if len(supported) not in {4,5}:continue
        axes=[]
        for mate,_ in pair:
            shapes=[ac._shape(e) for e in mate['entities']] if mate['type'] in {0,1} else []
            if len(shapes)==2 and all(shape[0] in {'cylindrical_axis','circular_edge'} for shape in shapes):
                axes.append(shapes[0][1])
        if not axes or any(abs(ac.dot(axes[0],axis))<1-1e-8 for axis in axes[1:]):continue
        axial=axes[0]+[0.,0.,0.]
        groups[key].append((members,pair,supported,axial))
    result=[]
    for occurrences in groups.values():
        free=[members for members,_,rows,axis in occurrences if len(rows)==4 and all(abs(ac.dot(row,axis))<1e-8 for row in rows)]
        if not free:continue
        reference_names=[[by_id[c]['instance'] for c in members] for members in free]
        for members,pair,rows,axis in occurrences:
            if len(rows)!=5 or all(abs(ac.dot(row,axis))<1e-8 for row in rows):continue
            for index,(mate,_) in enumerate(pair):
                if mate['type']!=0 or any(ac._shape(e)[0]!='planar_normal' for e in mate['entities']):continue
                remaining=ac.basis([row for pos,(_,mat) in enumerate(pair) if pos!=index for row in mat])
                if len(remaining)==4 and all(abs(ac.dot(row,axis))<1e-8 for row in remaining):
                    result.append({'native_feature_id':mate['native_feature_id'],'name':mate['name'],
                        'components':[by_id[c]['instance'] for c in members], 'peer_pairs_with_observed_axial_freedom':reference_names[:4],
                        'peer_pair_count':len(reference_names),
                        'local_rank':5,'local_rank_without_candidate':4,
                        'scope':'identical_part_configurations_local_candidate_may_be_intentional',
                        'automatic_suppression_allowed':False})
    return result


def connection_variations(inspection, mirrors=None):
    """Compare active mate inventories of observed pairs with the same part/configuration identities."""
    components={c['component_id']:c for c in inspection['components']}
    families={cid:(ntpath.normcase(c['path']),c['configuration']) for cid,c in components.items()
              if c.get('path') and c.get('configuration') and not c.get('subassembly')
              and not c.get('parent_component_id') and c.get('suppressed') is not True and c.get('loaded') is not False}
    pairs=defaultdict(Counter)
    excluded=set()
    for mate in inspection.get('mates',[]):
        entities=mate.get('entities') or []
        members=tuple(sorted({e.get('component_id') for e in entities if e.get('component_id') in families}))
        if len(members)!=2 or mate.get('suppressed') is True:continue
        mate_type=mate.get('type')
        if (len(entities)!=2 or mate.get('suppressed') is not False or mate.get('error')!=0
                or mate.get('warning') or type(mate_type) is not int):
            excluded.add(members)
            continue
        pairs[members][mate_type]+=1
    groups=defaultdict(list)
    for pair,counts in sorted(pairs.items()):
        if pair not in excluded:
            group=tuple(sorted(families[c] for c in pair))
            groups[group].append((pair,tuple(sorted(counts.items()))))
    mirrors=mirror_connections.review(inspection) if mirrors is None else mirrors
    native_sources={frozenset((m['component_id'],m['source_candidates'][0]['component_id'])) for m in mirrors
                    if m.get('source_binding_status')=='unique_native_source_observed' and len(m.get('source_candidates',[]))==1}
    for group,occurrences in sorted(groups.items()):
        signatures=defaultdict(list)
        for pair,counts in occurrences:signatures[counts].append(pair)
        if len(signatures)<2:continue
        for pair,counts in occurrences:
            other_signature,peers=next((key,items) for key,items in signatures.items() if key!=counts)
            peer=peers[0]
            confirmed_mirror_links=sorted((components[a]['instance'],components[b]['instance']) for a in pair for b in peer
                                          if a!=b and frozenset((a,b)) in native_sources)
            yield {'component_ids':list(pair),'components':[components[c]['instance'] for c in pair],
                   'compared_component_ids':list(peer),'compared_components':[components[c]['instance'] for c in peer],
                   'mate_type_counts':{MATE_TYPE_NAMES.get(t,f'native_type_{t}'):n for t,n in counts},
                   'compared_mate_type_counts':{MATE_TYPE_NAMES.get(t,f'native_type_{t}'):n for t,n in other_signature},
                   'observed_native_mirror_links':confirmed_mirror_links,
                   'matching_part_configuration_pair_count':len(occurrences),'variant_count':len(signatures),
                   'scope':'observed_active_mate_types_on_repeated_top_level_part_pairs',
                   'design_symmetry_proven':False,'mechanical_DOF_proven':False,'automatic_constraint_change_allowed':False}


def stale_motion_context(review):
    """Expose bounded observations without turning the supported graph into solver proof."""
    review=review or {}
    observations=[]
    if review.get('reference_link_observed') is False:
        observations.append('DRIVE_REFERENCE_MATE_PATH_NOT_OBSERVED')
    if review.get('reference_path_appears_only_with_observed_mirror_dependencies') is True:
        observations.append('REFERENCE_PATH_OBSERVED_ONLY_WITH_MIRROR_DEPENDENCIES')
    if review.get('status')=='supported_direction_blocked_at_start':
        observations.append('DIRECTION_BLOCKED_IN_SUPPORTED_LOCAL_PROJECTION')
    if (review.get('redundancy_candidate_count') or 0)>0:
        observations.append('LOCAL_REDUNDANCY_CANDIDATES')
    return {'observations':observations,'constraint_review_status':review.get('status'),
            'driven_mate_island_size':review.get('driven_mate_island_size'),
            'reference_is_native_fixed':review.get('reference_is_native_fixed'),
            'omitted_constraint_count':review.get('omitted_constraint_count'),
            'redundancy_candidate_count':review.get('redundancy_candidate_count'),
            'solver_root_cause_proven':False,'automatic_constraint_change_allowed':False}


def drive_review(inspection, drive, reference, motion):
    """Relate the selected drive coordinate to the supported constraint rows."""
    from . import constraint_graph,mirror_connections

    a,b=drive['component_id'],reference['component_id']
    axis=ac.unit(drive['axis_global'])
    nodes=inspection['components']
    candidates=review(inspection)
    variations=axial_variations(inspection)
    output={'scope':'instantaneous_supported_constraints_and_known_links',
            'global_DOF_certified':False,'solver_compatibility_verified':False,
            'root_cause_proven':False,'redundancy_candidate_count':len(candidates),
            'redundancy_candidates':sorted(candidates,key=lambda row:not ({a,b}&set(row['component_ids'])))[:8],
            'axial_variation_count':len(variations),'axial_variations':variations[:8],
            'automatic_suppression_allowed':False}
    if not 1<=len(nodes)<=128:
        return {**output,'status':'outside_instantaneous_projection_budget'}
    try:
        graph=constraint_graph.model({**inspection,'inventory_complete':True})
        projection=graph.relative(a,b)
        seen={a}
        pending=[a]
        while pending:
            peers=graph.adj[pending.pop()]-seen
            seen.update(peers)
            pending.extend(peers)
        if motion=='linear':
            point=[(p-o)/graph.scale for p,o in zip(drive['reference_point_global_m'],graph.origin)]
            row=axis+ac.cross(point,axis)
        else:
            row=[0.,0.,0.]+axis
        dependencies={component:set(peers) for component,peers in graph.adj.items()}
        for relation in mirror_connections.review(inspection):
            if relation['root_source_status']!='unique_root_of_observed_dependency_chain':continue
            for source in relation['source_candidates']:
                member,original=relation['component_id'],source['component_id']
                dependencies[member].add(original);dependencies[original].add(member)
        seen_with_mirrors=set(seen)
        pending=list(seen)
        while pending:
            peers=dependencies[pending.pop()]-seen_with_mirrors
            seen_with_mirrors.update(peers);pending.extend(peers)
        return {**output,'status':'supported_direction_blocked_at_start' if all(abs(ac.dot(row,v))<1e-8 for v in projection['free_basis']) else 'direction_not_blocked_by_supported_rows',
                'reference_link_observed':b in seen,'driven_mate_island_size':len(seen),
                'reference_path_appears_only_with_observed_mirror_dependencies':b not in seen and b in seen_with_mirrors,
                'mirror_dependency_is_rigidity_proof':False,
                'mate_island_scope':'observed_mates_and_native_parent_links_excludes_mirror_inference',
                'reference_is_native_fixed':graph.by_id[b].get('fixed_component'),
                'supported_relative_rank':projection['supported_effective_rank'],
                'omitted_constraint_count':len(projection['omitted_native_feature_ids'])}
    except (KeyError,TypeError,ValueError):
        return {**output,'status':'instantaneous_projection_unavailable'}
