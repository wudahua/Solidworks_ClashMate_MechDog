import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from sw_mcp.conversation.task_engine import HERE, core, mechanical_choices
from sw_mcp.conversation.runtime_location import choose_runtime


class RuntimeAndNamesTests(unittest.TestCase):
    def test_long_default_falls_back_without_configuration_or_policy_edit(self):
        root = HERE / 'test-runs' / uuid.uuid4().hex[:8]
        with patch.dict(os.environ, {'LOCALAPPDATA': str(HERE.parents[1] / 'runs/l')}):
            selected = choose_runtime(root / ('long' * 25), root)
        receipt = core.read(root / '运行目录选择.json')
        self.assertTrue(receipt['automatic_fallback'])
        self.assertLess(core.runtime_path_budget(selected / '000000')['atomic_metadata_maximum_path_characters'], 260)
        self.assertFalse(receipt['CAD_started'])
        self.assertFalse(receipt['global_long_path_policy_changed'])

    def test_all_paths_refused_preserves_diagnostics_and_never_starts_CAD(self):
        root = HERE / 'test-runs' / uuid.uuid4().hex[:8]
        with patch('sw_mcp.conversation.runtime_location.core.runtime_path_budget', side_effect=core.StopBatch('ACCEPTANCE_RUNTIME_PATH_TOO_LONG')):
            with self.assertRaises(core.StopBatch) as caught:
                choose_runtime(root, root)
        self.assertEqual(caught.exception.code, 'RUNTIME_LOCATION_UNAVAILABLE')
        self.assertFalse(caught.exception.diagnostics['CAD_started'])
        self.assertTrue(caught.exception.diagnostics['candidates'])

    def test_names_keep_instance_suffix_and_mechanical_role(self):
        components = [{'instance': '0005_abcd1234_0005_91ec3e42_gear-' + str(i),
                       'fixed_component': True, 'transform': list(range(13))} for i in [1, 2]]
        choices = mechanical_choices(components, 'gear', True)
        self.assertEqual([c['name'] for c in choices], ['gear-1', 'gear-2'])
        self.assertTrue(all(c['role'] == '固定参考件' for c in choices))
        self.assertEqual(choices[0]['component_origin_world_m'], [9, 10, 11])


if __name__ == '__main__': unittest.main(verbosity=2)
