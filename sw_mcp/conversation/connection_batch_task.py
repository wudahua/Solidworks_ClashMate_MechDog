"""One confirmed plan, serial native batches, and one import recovery boundary."""
import json
from . import core
from .. import connection_batches


def apply(engine,t,s):
    from .motion_tasks import pose_snapshot,require_same_poses
    tx=t['connection_transaction'];receipts=[]
    expected={c['component_id']:c['fixed_component'] for c in s.initial_inspection['components']}
    old={m['native_feature_id']:m for m in s.initial_inspection['mates']};added=0
    initialization=t['proposal'].get('initial_translation');expected_poses=pose_snapshot(s.initial_inspection['components'])
    if initialization:expected_poses={e['component_id']:e['after'][:12] for e in initialization['entries']}
    for i,summary in enumerate(tx['batches']):
        s.state('whole_assembly_native_batch','正在按已确认整装配方案执行并核对批次…',batch_index=i,batch_count=tx['batch_count'])
        if i==0:plan_id=t['proposal']['plan_id']
        else:
            signature=s.call('_connection_reference_state',model_id=s.model)['reference_state_signature']
            preview=s.call('_preview_assembly_connections',model_id=s.model,proposal_json=json.dumps(connection_batches.request(tx,i,signature),ensure_ascii=False))
            core.write(s.folder/f'整装配批次{i+1:02d}预演.json',preview)
            if preview['expected_added_mates']!=summary['added_mates']:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','批次预演与冻结方案不符。')
            plan_id=preview['plan_id']
        t['batch_progress']={'transaction_id':tx['transaction_id'],'batch_count':tx['batch_count'],'completed_batches':i,'current_batch_index':i,'stage':'native_apply_pending'};engine.save(t)
        kwargs={'alignment_confirmed':True} if i==0 and initialization and initialization['requires_alignment_confirmation'] else {}
        response=s.call('_apply_assembly_connections',plan_id=plan_id,confirmed=True,**kwargs)
        core.write(s.folder/f'整装配批次{i+1:02d}成果.json',response)
        header=response.get('batch_transaction') or {}
        if header.get('transaction_id')!=tx['transaction_id'] or header.get('batch_index')!=i or header.get('payload_sha256')!=tx['payload_hashes'][i] or response['added_mates']!=summary['added_mates']:
            raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','原生批次回执身份、载荷或新增数不符。')
        if header.get('all_batches_completed')!=(i+1==tx['batch_count']):raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','原生批次完整性标志不符。')
        for change in response['fixed_state_changes']:
            if expected.get(change['component_id']) is not True or change['before'] is not True or change['after'] is not False:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','跨批固定状态超出冻结名单。')
            expected[change['component_id']]=False
        added+=response['added_mates'];current=s.call('inspect_model',model_id=s.model,detail_level='full')
        readback_path=s.folder/f'整装配批次{i+1:02d}原生读回.json';core.write(readback_path,current)
        if initialization:
            from ..initial_translation import verify_native
            try:initialization_audit=verify_native(initialization,s.initial_inspection['components'],current['components'],solver_readback=True)
            except (ValueError,TypeError,KeyError) as error:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','初态微量平移的完整读回或跨批保持未通过。',{'reason':str(error),'pose_diagnostics':getattr(error,'diagnostics',None),'native_readback_path':str(readback_path)}) from error
            if i==0 and response.get('initial_translation_verified') is not True:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','首批缺少原生微量平移核验。')
            core.write(s.folder/f'微量初态跨批核对{i+1:02d}.json',initialization_audit)
        poses=require_same_poses(expected_poses,pose_snapshot(current['components']),'whole_batch_'+str(i+1))
        flags={c['component_id']:c['fixed_component'] for c in current['components']}
        new={m['native_feature_id']:m for m in current['mates']}
        if flags!=expected or len(new)!=len(old)+added or not set(old)<=set(new) or any(old[k]['type']!=new[k]['type'] or old[k]['suppressed']!=new[k]['suppressed'] for k in old):
            raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','跨批全组件状态或原配合清单未保持。')
        core.write(s.folder/f'整装配批次{i+1:02d}独立核对.json',{'passed':True,'inspection':current,'initial_pose_audit':poses,'fixed_flags':flags,'expected_fixed_flags':expected})
        receipts.append({'batch_index':i,'plan_id':plan_id,'payload_sha256':tx['payload_hashes'][i],'added_mates':response['added_mates'],'passed':True})
        t['batch_progress'].update(completed_batches=i+1,stage='batch_verified');engine.save(t)
        core.write(s.folder/'整装配批次执行回执.json',receipts)
    if len(receipts)!=tx['batch_count'] or added!=t['proposal']['expected_added_mates']:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','整装配批次数量或总新增数未闭合。')
    return {'model_id':s.model,'transaction_id':tx['transaction_id'],'batch_count':tx['batch_count'],'batches':receipts,'added_mates':added,
            'native_health_verified':True,'source_files_unchanged':True,'restoration_status':'restored','global_motion_verified':False}


def restore_failed_transaction(s,t,error):
    if s.unknown or getattr(error,'code',None)=='CONNECTION_NATIVE_UNKNOWN':return
    failure={'code':getattr(error,'code',type(error).__name__),'message':str(error),'diagnostics':getattr(error,'diagnostics',None)}
    try:
        restored=s.restore()
        if not core.restored_ok(restored):raise core.StopBatch('RESTORE_NOT_VERIFIED')
        audit={'status':'restored','full_import_checkpoint_restored':True,'original_failure':failure,'restoration':restored,'completed_batches':t.get('batch_progress',{}).get('completed_batches',0)}
        core.write(s.folder/'整装配失败整体回滚.json',audit)
        error.diagnostics={'original_diagnostics':getattr(error,'diagnostics',None),'whole_transaction_rollback':audit};error.restoration_status='restored'
    except Exception as rollback:
        s.unknown=True
        raise core.StopBatch('CONNECTION_NATIVE_UNKNOWN','整装配失败后的原始检查点恢复未验证，保留现场，不重放写入。',{'original_failure':failure,'rollback_failure':str(rollback)}) from rollback
