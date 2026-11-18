"""Expand shared material axes into existing, independently stated joint goals."""
from . import assembly_connections as joints
from . import initial_translation


def _common_choices(options):
    common = []
    for choice in options[0]:
        carrier_line = choice['carrier_line']
        if any(joints._line_matches(carrier_line, old[0]['carrier_line']) for old in common):
            continue
        matches = [[row for row in rows if joints._line_matches(carrier_line, row['carrier_line'])]
                   for rows in options]
        if all(len(rows) == 1 for rows in matches):
            common.append([rows[0] for rows in matches])
    return common


def expand(survey, groups, translation_budget_mm=None):
    """Pick one common material line; keep each member's axial role separate."""
    if type(groups) is not list or not 1 <= len(groups) <= 16:
        raise ValueError('coaxial_group_count_invalid')
    by_id = {c['component_id']: c for c in survey['components']}
    pairs, _, origin, scale = joints.observed_rows(survey)
    goals, bindings, labels = [], [], set()
    for group in groups:
        name, carrier = group['name'], group['axis_component']
        members, hint = group['members'], group.get('axis_hint')
        if not name.strip() or name in labels or carrier not in by_id or not 2 <= len(members) <= 16:
            raise ValueError('coaxial_group_binding_invalid')
        labels.add(name)
        reference = by_id[carrier]
        options = []
        seen = {carrier}
        for member in members:
            cid, axial = member['component'], member['axial']
            if cid not in by_id or cid in seen or axial not in {'free', 'located'}:
                raise ValueError('coaxial_group_member_invalid')
            seen.add(cid)
            a = by_id[cid]
            kind = 'cylindrical' if axial == 'free' else 'revolute'
            goal = {'component_a':cid, 'component_b':carrier, 'kind':kind}
            if hint is not None:
                goal['axis_hint'] = hint
            if translation_budget_mm is not None:
                candidates = initial_translation._lines(a, reference, hint, translation_budget_mm/1000)
                choices = [(row['candidate_id'], row['geometry_b']) for row in candidates]
            else:
                pair = pairs.get(tuple(sorted((cid, carrier))), {'rows':[]})
                if a.get('fixed_component') and not reference.get('fixed_component'):
                    a, b = reference, a
                else:
                    b = reference
                candidates = joints._axes(survey, a, b, hint, pair, origin, scale, kind)
                choices = [('axis-'+str(i+1), axis) for i, axis in enumerate(candidates)
                           if any(joints._line_matches(axis, face) for face in reference.get('cylinders', []))]
            options.append([{'goal':{**goal, 'candidate_id':candidate}, 'carrier_line':line, 'axial':axial}
                            for candidate, line in choices])
        common = _common_choices(options)
        point = group.get('axis_point_hint_m')
        if point is not None:
            common = [rows for rows in common if joints._line_matches(rows[0]['carrier_line'],
                {'axis_global':rows[0]['carrier_line']['axis_global'],'reference_point_global_m':point})]
        if len(common) != 1:
            return [], [], {'status':'coaxial_group_axis_selection_required' if common else 'coaxial_group_axis_unavailable',
                'group':name, 'axis_component':reference['instance'],
                'shared_material_lines':[{k: rows[0]['carrier_line'][k] for k in ('axis_global','reference_point_global_m')} for rows in common],
                'member_candidate_counts':[len(rows) for rows in options],
                'instruction':'同轴组需要同一条材料轴线。AI核对轴肩、孔位和两端机械用途，仅在轴线仍有歧义时集中澄清。',
                'write_dispatched':False, 'confirmation_token_created':False}
        rows = common[0]
        line = rows[0]['carrier_line']
        goals.extend(row['goal'] for row in rows)
        bindings.append({'name':name, 'axis_component':carrier,
            'axis_global':line['axis_global'], 'reference_point_global_m':line['reference_point_global_m'],
            'members':[{'component':row['goal']['component_a'], 'axial':row['axial'], 'rotation':'free'} for row in rows]})
    return goals, bindings, None


def rebind(survey, goals, bindings, initialization):
    """Bind new candidate indices after virtual translation without changing the material line."""
    if not bindings:
        return
    by_id = {c['component_id']: c for c in survey['components']}
    translations = {row['component_id']:row['delta_m'] for row in (initialization or {}).get('entries', [])}
    pairs, _, origin, scale = joints.observed_rows(survey)
    goal_by_pair = {frozenset((g['component_a'],g['component_b'])):g for g in goals}
    for group in bindings:
        carrier = group['axis_component']
        group['reference_point_global_m'] = [x+d for x,d in zip(group['reference_point_global_m'],translations.get(carrier,[0]*3))]
        for member in group['members']:
            cid = member['component']
            goal = goal_by_pair[frozenset((cid,carrier))]
            a, b = by_id[cid], by_id[carrier]
            if a.get('fixed_component') and not b.get('fixed_component'):
                a, b = b, a
            pair = pairs.get(tuple(sorted((cid,carrier))), {'rows':[]})
            choices = joints._axes(survey,a,b,goal.get('axis_hint'),pair,origin,scale,goal['kind'])
            selected = [i for i, line in enumerate(choices,1) if joints._line_matches(line,group)]
            if len(selected) != 1:
                raise ValueError('coaxial_group_material_axis_binding_changed')
            goal['candidate_id'] = 'axis-'+str(selected[0])
