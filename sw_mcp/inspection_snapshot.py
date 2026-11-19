"""Bounded reads of one frozen full inspection, with stable section cursors."""
import hashlib
import json
import re

from .conversation import core


SECTIONS = ('components', 'mates', 'geometry', 'mirror_dependencies', 'redundancy_candidates', 'axial_mate_variations')
PAGE_BUDGET = 12_000


def store(root, value):
    from .mirror_connections import review
    from .mate_redundancy import axial_variations,review as redundancy
    components = value['components']
    mates = []
    geometry = []
    for mate in value['mates']:
        row = {k:v for k,v in mate.items() if k!='entities'}
        row['entities'] = []
        for index, entity in enumerate(mate.get('entities', [])):
            row['entities'].append({k:v for k,v in entity.items() if k not in {'geometry','constraint_geometry'}})
            geometry.append({'native_feature_id':mate['native_feature_id'],'entity_index':index,
                'component_id':entity.get('component_id'),'geometry':entity.get('geometry'),
                'constraint_geometry':entity.get('constraint_geometry')})
        mates.append(row)
    sections = dict(components=components,mates=mates,geometry=geometry,mirror_dependencies=review(value),
                    redundancy_candidates=redundancy(value),axial_mate_variations=axial_variations(value))
    record = {'model_id':value['model_id'],'sections':sections,'component_count':len(components),'mate_count':len(mates)}
    blob = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',',':'), allow_nan=False).encode('utf-8')
    token = hashlib.sha256(blob).hexdigest()
    directory = core.no_links(root/'runs'/'inspections')
    directory.mkdir(parents=True,exist_ok=True)
    path = core.no_links(directory/(token+'.json'))
    if not path.exists():
        candidate = path.with_suffix('.tmp-'+__import__('uuid').uuid4().hex)
        candidate.write_bytes(blob)
        candidate.replace(path)
    counts = {k:len(v) for k,v in sections.items()}
    return {'model_id':value['model_id'],'configuration':value.get('configuration'),'snapshot_id':token,
        'counts':counts,'mate_health':value.get('mate_health'),'degrees_of_freedom':value.get('degrees_of_freedom'),
        'source_files_unchanged':value.get('source_files_unchanged'),
        'constraint_review_counts':(value.get('assembly_constraint_review') or {}).get('counts'),
        'queries':{s:{'model_id':value['model_id'],'detail_level':'page','cursor':token+':'+s+':0'} for s in SECTIONS if counts[s]},
        'scope':'frozen_snapshot_not_live_geometry_or_motion_authority'}


def page(root, model_id, cursor, limit):
    match=re.fullmatch(r'([a-f0-9]{64}):('+('|'.join(SECTIONS))+r'):([0-9]{1,6})',cursor)
    if match is None or type(limit) is not int or not 1<=limit<=100:
        raise ValueError('快照游标格式或页大小无效。')
    token,section,offset=match[1],match[2],int(match[3])
    path=core.no_links(root/'runs'/'inspections'/(token+'.json'))
    blob=path.read_bytes()
    if hashlib.sha256(blob).hexdigest()!=token:
        raise ValueError('快照哈希不符。')
    data=json.loads(blob)
    if data['model_id']!=model_id:
        raise ValueError('快照与所请求的模型不一致。')
    rows=data['sections'][section]
    if offset>=len(rows):
        raise ValueError('快照游标超出集合范围。')
    output=[]
    used=0
    for row in rows[offset:offset+limit]:
        size=len(json.dumps(row,ensure_ascii=False,allow_nan=False).encode('utf-8'))+2
        if used+size>PAGE_BUDGET:
            break
        output.append(row)
        used+=size
    if not output:
        raise ValueError('此记录超出分页预算，请用完整工件检查。')
    end=offset+len(output)
    return {'model_id':model_id,'snapshot_id':token,'section':section,'rows':output,'range_start':offset,
        'range_end_exclusive':end,'total_count':len(rows),'next_cursor':token+':'+section+':'+str(end) if end<len(rows) else None,
        'scope':'frozen_snapshot_not_current_CAD','cad_dispatched':False}
