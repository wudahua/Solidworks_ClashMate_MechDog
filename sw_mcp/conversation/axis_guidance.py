"""Read-only native joint-axis hints; never a degree-of-freedom certificate."""
import math


def unit(value):
    if not isinstance(value,(list,tuple)) or len(value)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) for x in value):return None
    length=math.sqrt(sum(x*x for x in value))
    return [x/length for x in value] if length>1e-12 else None


def parallel(a,b):return a is not None and b is not None and abs(sum(x*y for x,y in zip(a,b)))>=1-1e-7


def annotate_linear_axes(rows,mates):
    """Keep all candidates/IDs; prefer a unique axis hinted by healthy concentric mates.

    Uses already inspected native mate geometry, including the moving body's
    own reference. A neighboring body may move too: this is a local joint hint,
    not proof that the requested global/relative motion is feasible. No trials,
    extra geometry scans, suppression or automatic fallback are performed.
    """
    for row in rows:
        moving=row['drive']['component_id'];hints=[]
        for mate in mates:
            if mate.get('type_name')!='swMateCONCENTRIC' or mate.get('error')!=0 or mate.get('warning'):continue
            entities=mate.get('entities',[])
            if len(entities)!=2:continue
            own=[e for e in entities if e.get('component_id')==moving]
            if len(own)!=1:continue
            other=next(e for e in entities if e is not own[0])
            if not other.get('component_id') or other['component_id']==moving:continue
            a=own[0].get('geometry') or {};b=other.get('geometry') or {}
            if a.get('kind')!='cylindrical_axis' or b.get('kind')!='cylindrical_axis':continue
            first=unit(a.get('axis_global'));second=unit(b.get('axis_global'))
            if not parallel(first,second):continue
            hints.append({'mate_name':mate.get('name'),'native_feature_id':mate.get('native_feature_id'),
                'moving_component_id':moving,'other_instance':other.get('instance'),'axis_global':first})
        consistent=bool(hints) and all(parallel(hints[0]['axis_global'],h['axis_global']) for h in hints)
        aligned=consistent and parallel(unit(row.get('axis_global')),hints[0]['axis_global'])
        row['axis_evidence']={'scope':'healthy_native_concentric_mate_axes_local_joint_hint_only',
            'native_mate_axes':hints,'mate_axis_hints_consistent':consistent,
            'parallel_to_native_mate_axis_hint':bool(aligned),'degrees_of_freedom_status':'unknown',
            'solve_required':True,'nonparallel_does_not_prove_blocked':True}
        row['recommended_from_native_mate_axis']=bool(aligned)
        if aligned:row['reason']+=' 该方向与已观测同轴配合的原生轴线一致，优先作为直线试算线索；相邻件可能共同运动，仍须验证，不按世界坐标字母猜纵向。'
    return rows
