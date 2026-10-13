"""Real MCP schema and explicit offline history export; no native CAD calls."""
import asyncio,csv,hashlib,json,shutil,sys,uuid
from pathlib import Path
from mcp import Client,StdioServerParameters
ROOT=Path(__file__).resolve().parents[1]

async def main():
    identifier=uuid.uuid4().hex;folder=ROOT/'runs'/identifier;folder.mkdir(parents=True)
    journal=ROOT/'runs/executor-state.json';journal_before=journal.read_bytes() if journal.exists() else None
    fields=['frame','time_s','component_id','instance','x_m','y_m','z_m','r00','r01','r02','r10','r11','r12','r20','r21','r22']
    path=folder/'component-poses.csv'
    with path.open('w',newline='',encoding='utf-8') as out:
        writer=csv.writer(out);writer.writerow(fields)
        for i in range(3):writer.writerow([i,i/5,'component_protocol_fixture','synthetic_unit_fixture',i*.002,0,0,1,0,0,0,1,0,0,0,1])
    data={'run_id':identifier,'test_fixture':True,'poses_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'sampling_status':'completed','native_time_axis_verified':True,'frames':3,'output_fps':5,'duration_s':.4,'result_validity':'inconclusive','restoration_status':'unknown'}
    (folder/'solve.json').write_text(json.dumps(data),encoding='utf-8')
    try:
        async with Client(StdioServerParameters(command=sys.executable,args=[str(ROOT/'motion_server.py')],cwd=ROOT)) as client:
            info=client.server_info
            assert info is not None and info.name=='SolidWorks ClashMate MechDog' and info.version
            server_info=info.model_dump()
            tools={t.name:t for t in (await client.list_tools()).tools}
            assert len(tools)==24
            expected={'reset_study_time':'allow_recalculate','create_motion_study':'reference_component_id','verify_motion_preservation':'reference_component_id','export_motion_curve':'allow_unverified_history','list_drive_candidates':'detail_level','list_mate_references':'detail_level'}
            for name,parameter in expected.items():assert parameter in tools[name].input_schema['properties']
            for name in ('apply_mate','create_motion_study','convert_motion_study','reset_study_time','create_model_checkpoint'):
                assert tools[name].input_schema['properties']['wait_for_completion']['default'] is False
            for parameter in ('duration_s','output_fps'):
                assert parameter in tools['create_motion_study'].input_schema['properties']
            assert 'request_id' in tools['get_recovery_state'].input_schema['properties']
            response=await client.call_tool('export_motion_curve',{'run_id':identifier,'component_id':'component_protocol_fixture','quantity':'linear_velocity','axis':'x','allow_unverified_history':True})
            assert not response.is_error,response
            result=response.structured_content['result']
            assert result['result_validity']=='inconclusive' and result['restoration_status']=='unknown' and result['physical_validation_claim'] is False
            assert result['sample_count']==3 and abs(result['max']-.01)<1e-12
        assert (journal.read_bytes() if journal.exists() else None)==journal_before
        report={'all_passed':True,'server_info':server_info,'tools':len(tools),'new_option_schemas_verified':expected,'public_offline_export_verified':True,'unknown_recovery_journal_unchanged':True,'cad_connection_used':False,'export_data_source':'explicit_synthetic_protocol_fixture_not_native_acceptance'}
        (ROOT/'runs/mechanism-protocol-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
    finally:
        folder.resolve().relative_to((ROOT/'runs').resolve())
        if folder.is_symlink():raise RuntimeError('unexpected fixture link')
        shutil.rmtree(folder)

if __name__=='__main__':asyncio.run(main())
