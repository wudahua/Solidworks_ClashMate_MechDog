"""Bounded, read-only joint drafts. Geometric evidence is not design intent."""
import hashlib
import itertools
import math
import json
import re
from . import assembly_connections as joints

MAX_PAIRS=64
MAX_CANDIDATES=8


def _parallel(a,b):
    return abs(joints.ac.dot(joints.ac.unit(a),joints.ac.unit(b)))>1-1e-8


def _coaxial(a,b):
    found=[]
    for fa in a.get('cylinders',[])[:24]:
        for fb in b.get('cylinders',[])[:24]:
            try:
                if joints._line_matches(fa,fb) and not any(joints._line_matches(fa,row) for row in found):
                    found.append({'axis_global':fa['axis_global'],'reference_point_global_m':fa['reference_point_global_m'],
                                  'source':'current_coaxial_cylindrical_geometry'})
            except (KeyError,TypeError,ValueError):continue
    return found


def _guide_hints(a,b,rows,origin,scale):
    """Global AABB elongation is only a hypothesis, never a material axis proof."""
    if not rows:return []
    hints=[]
    for c in (b,a):
        box=c.get('box')
        if not isinstance(box,(list,tuple)) or len(box)!=6 or any(type(v) not in (int,float) or not math.isfinite(v) for v in box):continue
        spans=[box[i+3]-box[i] for i in range(3)]
        if min(spans)<=1e-9:continue
        order=sorted(range(3),key=lambda i:spans[i],reverse=True)
        if spans[order[0]]<.001 or spans[order[0]]<3*spans[order[1]]:continue
        other=b if c is a else a;other_box=other.get('box')
        if not isinstance(other_box,(list,tuple)) or len(other_box)!=6 or any(type(v) not in (int,float) or not math.isfinite(v) for v in other_box):continue
        if any(min(box[i+3],other_box[i+3])<max(box[i],other_box[i])-.0001 for i in range(3) if i!=order[0]):continue
        axis=[float(i==order[0]) for i in range(3)]
        target=joints.target_rows('prismatic',axis,a['transform'][9:12],origin,scale)
        if len(joints.ac.basis(target+rows))>5:continue
        if any(_parallel(axis,h['axis_global']) for h in hints):continue
        hints.append({'axis_global':axis,'reference_point_global_m':a['transform'][9:12],
                      'source':'elongated_global_bounding_box_heuristic','reference_instance':c['instance'],
                      'elongation_ratio':spans[order[0]]/spans[order[1]],'design_intent_proven':False})
    return hints


def draft(survey,review=None,cursor='',binding=''):
    review=review or joints.review(survey)
    result={'schema_version':1,'status':'review_required','candidates':[],
            'write_dispatched':False,'confirmation_token_created':False,'mechanical_intent_proven':False,
            'global_DOF_certified':False,'scope':'bounded_pair_draft_not_whole_assembly_completion',
            'suppressed_mates_used_as_active_constraints':False,
            'omitted_native_feature_ids':review.get('omitted_native_feature_ids',[]),
            'instruction':'AI结合用户已说的机械目标选择候选输入并集中解释歧义；先plan取得具体原生方案，再确认执行。候选不直接写入，也不默认把浮动件锁死。'}
    if not review.get('complete') or review.get('mate_health_issues'):
        result['reason']='native_inventory_or_health_requires_review';return result
    try:snapshot=hashlib.sha256((binding+'\n'+json.dumps(survey,sort_keys=True,separators=(',',':'),allow_nan=False)).encode()).hexdigest()
    except (TypeError,ValueError):
        result['reason']='non_json_or_nonfinite_native_snapshot';return result
    offset=0
    if cursor:
        match=re.fullmatch(r'([a-f0-9]{64}):([0-9]{1,5})',cursor)
        if not match or match[1]!=snapshot:raise ValueError('draft_cursor_snapshot_or_scope_mismatch')
        offset=int(match[2])
    cs=survey['components'];by_id={c['component_id']:c for c in cs}
    pairs,omitted,origin,scale=joints.observed_rows(survey)
    eligible=[key for key in itertools.combinations(sorted(by_id),2) if not all(by_id[x].get('fixed_component') for x in key)]
    eligible.sort(key=lambda key:(0 if key in pairs and len(joints.ac.basis(pairs[key]['rows']))<5 else 1 if key in pairs else 2,key))
    if offset>=len(eligible) and cursor:raise ValueError('draft_cursor_outside_pair_scope')
    candidates=[];end=offset
    for key in eligible[offset:offset+MAX_PAIRS]:
        end+=1
        a,b=(by_id[x] for x in key)
        if a.get('fixed_component'):a,b=b,a
        pair=pairs.get(key,{'rows':[],'native_feature_ids':[]});rows=pair['rows']
        observed=joints.mobility(rows,origin,scale)
        axes=_coaxial(a,b)
        guides=_guide_hints(a,b,rows,origin,scale)
        if not rows and not axes:continue  # Datum alignment alone is not a connection.
        full=bool((a.get('constraint_state') or {}).get('fully_constrained'))
        locked=any(m.get('type')==16 and m.get('suppressed') is not True and
                   any(e.get('component_id')==a['component_id'] for e in m.get('entities',[])) for m in survey['mates'])
        options=[]
        def option(kind,axis=None,source=None,point_hint=None):
            point=point_hint or a['transform'][9:12]
            if kind=='revolute':
                matching=[r for r in axes if _parallel(r['axis_global'],axis)]
                if source=='supported_existing_constraint_rows':point=observed['axis_point_global_m']
                elif point_hint is not None:point=point_hint
                elif matching:point=matching[0]['reference_point_global_m']
                else:return
            if any(o['kind']==kind and (kind=='rigid' or
                   (_parallel(o['axis_global'],axis) and (kind=='prismatic' or joints._line_matches(
                       {'axis_global':axis,'reference_point_global_m':point},
                       {'axis_global':o['axis_global'],'reference_point_global_m':o['axis_point_global_m']})))) for o in options):return
            target=joints.target_rows(kind,axis,point,origin,scale)
            if len(joints.ac.basis(target+rows))>len(joints.ac.basis(target)):return
            intent={'component_a':a['instance'],'component_b':b['instance'],'kind':kind}
            if kind!='rigid':
                intent['axis_hint']=list(axis)
                choices=joints._axes(survey,a,b,axis,pair,origin,scale,kind)
                matching=[i for i,c in enumerate(choices) if kind=='prismatic' or joints._line_matches(c,{'axis_global':axis,'reference_point_global_m':point})]
                if not matching:return
                if len(choices)>1:intent['candidate_id']='axis-'+str(matching[0]+1)
            options.append({'kind':kind,'axis_global':axis,'axis_point_global_m':point if kind=='revolute' else None,'source':source,
                'connection_intent':intent,'requires_goal_confirmation':True,
                'supported_local_missing_coordinates_if_goal_chosen':len(joints.ac.basis(target+rows))-len(joints.ac.basis(rows)),
                'native_plan_required':True,'executable':False})
        if observed['recommended_joint_type']:
            kind=observed['recommended_joint_type']
            option(kind,observed.get('axis_global'),'supported_existing_constraint_rows')
        else:
            for axis in axes[:3]:
                option('revolute',axis['axis_global'],axis['source'],axis['reference_point_global_m'])
                option('prismatic',axis['axis_global'],axis['source'])
            for guide in guides[:2]:option('prismatic',guide['axis_global'],guide['source'])
            if rows or axes:option('rigid',source='alternative_only_if_rigid_mechanical_goal_confirmed')
        if not options:continue
        option_count=len(options);options=options[:4]
        has_motion=any(o['kind']!='rigid' for o in options)
        blocker='native_lock_trial_unsupported' if locked else 'native_full_constraint_mobile_goal_requires_review' if full and has_motion else None
        preferred=next((i for i,o in enumerate(options) if o['source']=='supported_existing_constraint_rows'),None)
        if preferred is None:
            guide_indices=[i for i,o in enumerate(options) if o['source']=='elongated_global_bounding_box_heuristic']
            if len(guide_indices)==1:preferred=guide_indices[0]
        candidates.append({'candidate_id':'joint-'+hashlib.sha256(('|'.join(key)).encode()).hexdigest()[:12],
            'component_a':a['component_id'],'component_b':b['component_id'],'instance_a':a['instance'],'instance_b':b['instance'],
            'supported_local_rank':observed['supported_local_rank'],'native_feature_ids':pair['native_feature_ids'],
            'missing_connection_proven':False,'indirect_connection_sufficiency_not_evaluated':True,
            'status':'review_required' if blocker else 'existing_supported_joint' if observed['recommended_joint_type'] else 'mechanical_goal_confirmation_required',
            'blocker':blocker,'preferred_option_index':preferred if not blocker else None,
            'options':options,'options_complete':option_count<=4,'omitted_option_count':max(0,option_count-4),
            'evidence':{'coaxial_material_lines_observed':len(axes),'material_lines_considered_for_options':min(len(axes),3),'guide_direction_hypotheses':guides,
                'geometry_complete_for_pair':all(c.get('geometry_complete',True) for c in (a,b)),
                'native_fully_constrained_observed':full,'suppressed_feature_names_not_used_to_infer_goal':True},
            'question':'按已有机械目标确认连接类型与方向；同轴还可能需要转动、滑动、刚性或本版未支持的圆柱自由度。几何线索不能替代设计用途。'})
        if len(candidates)==MAX_CANDIDATES:break
    result.update(status='draft_ready',candidates=candidates,snapshot_id=snapshot,
        next_cursor=snapshot+':'+str(end) if end<len(eligible) else None,
        cursor_scope='frozen_prepare_snapshot_readonly_not_current_COM_state',
        search={'eligible_pairs':len(eligible),'examined_pairs':end-offset,'pair_budget':MAX_PAIRS,
            'pair_range_start':offset,'pair_range_end_exclusive':end,
            'all_eligible_pairs_examined':offset==0 and end==len(eligible),
            'complete_for_remaining_suffix':end==len(eligible),'all_prior_pages_read_by_client':None,
            'candidate_count_found':len(candidates),'returned_candidates':len(candidates),'candidate_budget':MAX_CANDIDATES,
            'candidate_list_complete':offset==0 and end==len(eligible),
            'unexamined_pair_count':len(eligible)-end,'omitted_candidate_count':None,
            'geometry_complete':review['geometry_scope']['complete'],
            'absence_is_not_proof_of_no_missing_connection':True})
    return result
