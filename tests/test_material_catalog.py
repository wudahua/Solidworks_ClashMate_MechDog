"""MCP inspection and production C# catalog behavior without a CAD connection."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import motion_server

ROOT = Path(__file__).resolve().parents[1]


class InspectionContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_material_query_rejections_do_not_dispatch(self):
        invalid = (
            {'detail_level':'material_names'},
            {'detail_level':'material_names','material_database':' '},
            {'detail_level':'material_names','material_database':'sample.sldmat','wait_for_completion':False},
            {'detail_level':'materials','material_database':'sample.sldmat'},
            {'detail_level':'mass_properties','material_query':'AISI'},
        )
        with patch.object(motion_server, 'call', new_callable=AsyncMock) as native, patch.object(motion_server, 'enqueue') as enqueue:
            for args in invalid:
                with self.subTest(args=args):
                    result = await motion_server.mcp.call_tool('inspect_model', {'model_id':'model', **args})
                    self.assertTrue(result.is_error)
                    self.assertEqual(result.structured_content['error']['code'], 'INVALID_ARGUMENT')
            native.assert_not_awaited()
            enqueue.assert_not_called()

    async def test_material_name_cursor_and_filters_are_passed_to_native(self):
        params = {'model_id':'model','detail_level':'material_names','material_database':'sample.sldmat',
                  'material_query':'6061','cursor':'1:key','page_size':1}
        response = motion_server.packed({'ok':True,'result':{'rows':[],'next_cursor':None}})
        with patch.object(motion_server, 'call', new_callable=AsyncMock, return_value=response) as native:
            result = await motion_server.mcp.call_tool('inspect_model', params)
            native.assert_awaited_once_with('inspect_model', **params)
        self.assertEqual(result.structured_content, response.structured_content)

    async def test_default_summary_freezes_full_native_data_and_mass_uses_own_mode(self):
        tools = await motion_server.mcp.list_tools()
        properties = next(tool for tool in tools if tool.name=='inspect_model').input_schema['properties']
        self.assertEqual(properties['detail_level']['default'], 'summary')
        mass = {'mass_kg':2.0, 'volume_m3':.001, 'center_of_mass_m':[0,1,2], 'principal_moments_kg_m2':[.1,.2,.3]}
        response = motion_server.packed({'ok':True,'result':mass})
        with (patch.object(motion_server, 'call', new_callable=AsyncMock, return_value=response) as native,
              patch('sw_mcp.inspection_snapshot.store', return_value={'frozen':True}) as freeze):
            result = await motion_server.mcp.call_tool('inspect_model', {'model_id':'model'})
            native.assert_awaited_once_with('inspect_model',model_id='model',detail_level='full')
            freeze.assert_called_once_with(motion_server.ROOT,mass)
            self.assertEqual(result.structured_content['result'],{'frozen':True})
            native.reset_mock()
            result = await motion_server.mcp.call_tool('inspect_model', {'model_id':'model','detail_level':'mass_properties'})
            native.assert_awaited_once_with('inspect_model',model_id='model',detail_level='mass_properties')
            self.assertEqual(result.structured_content['result'],mass)


@unittest.skipUnless(os.name=='nt', 'Windows .NET Framework compiler required')
class MaterialCatalogNativePolicyTests(unittest.TestCase):
    def test_catalog_and_pagination_using_production_code(self):
        compiler = Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory)/'catalog.exe'
            sources = ('executor/MaterialCatalog.cs','executor/CadFault.cs','tests/MaterialCatalogTests.cs')
            compile_result = subprocess.run([str(compiler),'/nologo','/codepage:65001','/reference:System.Web.Extensions.dll',
                '/out:'+str(exe), *(str(ROOT/name) for name in sources)],capture_output=True,timeout=30)
            self.assertEqual(compile_result.returncode,0,(compile_result.stdout+compile_result.stderr).decode(errors='replace'))
            result = subprocess.run([str(exe),directory],capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,(result.stdout+result.stderr).decode('utf-8',errors='replace'))
            self.assertIn(b'passed without CAD',result.stdout)
