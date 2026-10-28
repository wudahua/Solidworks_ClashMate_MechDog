"""Grouping counterexamples and real task discovery contracts; no CAD."""
import copy
import itertools
import os
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sw_mcp import assembly_groups as ag
from sw_mcp.conversation import external_gear_task as task, external_gears as eg
from test_assembly_constraints import component, mate
from test_external_gears import survey
from test_service import temporary_workspace


def model(names=('ground', 'shaft', 'other', 'cover', 'bolt')):
    cs = [component(name, name == names[0]) for name in names]
    return {'components': cs, 'mates': [], 'inventory_complete': True,
            'reference_state_signature': 'current-model'}


class GroupTests(unittest.TestCase):
    def test_explicit_group_order_does_not_reassign_shaft_role_to_a_key(self):
        for incoming in itertools.permutations(['input_shaft', 'input_gear', 'input_key']):
            for outgoing in itertools.permutations(['output_shaft', 'output_gear', 'output_key']):
                s = survey()
                groups = {'stationary': ['body'], 'input': list(incoming), 'output': list(outgoing)}
                card = eg.recommend(s, intent_groups=groups)['proposals'][0]
                self.assertEqual(card['roles']['input_shaft'], 'input_shaft')
                self.assertEqual(card['roles']['output_shaft'], 'output_shaft')
                self.assertEqual(card['roles']['input_gear'], 'input_gear')
                self.assertEqual(card['roles']['output_gear'], 'output_gear')
                self.assertEqual(card['groups']['input'], list(incoming))

    def test_partial_constraint_paths_generate_draft_but_no_rigidity_claim(self):
        s = model()
        s['mates'] = [mate(1, 'ground', 'cover', 'cylindrical_axis'),
                      mate(2, 'cover', 'bolt', 'cylindrical_axis')]
        original = copy.deepcopy(s)
        r = ag.recommend(s, {'input': ['shaft'], 'output': ['other']})
        self.assertTrue(r['complete'])
        self.assertEqual(set(r['assembly_intent_draft']['stationary']), {'ground', 'cover', 'bolt'})
        self.assertTrue(r['requires_plan_confirmation'])
        self.assertFalse(r['write_dispatched'])
        self.assertFalse(r['automatic_assignment'])
        self.assertEqual(s, original)
        for row in r['component_recommendations']:
            self.assertFalse(row['evidence']['rigidity_proven'])

    def test_two_anchor_paths_stay_ambiguous_regardless_of_component_order(self):
        s = model()
        s['mates'] = [mate(1, 'ground', 'cover', 'planar_normal'),
                      mate(2, 'cover', 'bolt', 'cylindrical_axis'),
                      mate(3, 'bolt', 'shaft', 'planar_normal')]
        for order in (s['components'], list(reversed(s['components']))):
            with self.subTest(order=[c['component_id'] for c in order]):
                r = ag.recommend({**s, 'components': order}, {'input': ['shaft'], 'output': ['other']})
                self.assertFalse(r['complete'])
                self.assertEqual({c['component_id'] for c in r['pending_components']}, {'cover', 'bolt'})

    def test_bearings_never_follow_shaft_from_single_revolute_connection(self):
        s = model(('ground', 'shaft', 'other', 'bearing1', '轴承端盖'))
        s['mates'] = [mate(1, 'shaft', 'bearing1', 'cylindrical_axis'),
                      mate(2, 'ground', '轴承端盖', 'planar_normal')]
        r = ag.recommend(s, {'input': ['shaft'], 'output': ['other']})
        self.assertEqual(r['pending_component_count'], 1)
        self.assertEqual(r['mechanical_questions'][0]['reason'], 'integral_bearing_motion_intent')
        self.assertIn('轴承端盖', r['assembly_intent_draft']['stationary'])
        self.assertNotIn('bearing1', r['assembly_intent_draft']['input'])

    def test_names_without_observed_relations_cannot_assign_stationary(self):
        s = model(('ground', 'shaft', 'other', '螺栓1', 'washer1'))
        r = ag.recommend(s, {'input': ['shaft'], 'output': ['other']})
        self.assertEqual(r['pending_component_count'], 2)
        self.assertEqual(r['assembly_intent_draft']['stationary'], ['ground'])

    def test_healthy_pattern_seed_proposes_members_but_conflicting_seeds_do_not(self):
        s = model()
        s['structural_relations'] = {'components': [
            {'native_feature_id': 10, 'component_id': 'bolt', 'instance': 'bolt', 'is_pattern_instance': True}],
            'patterns': [{'native_feature_id': 20, 'suppressed': False,
                'seed_component_ids': ['ground'], 'child_features': [{'native_feature_id': 10}]}]}
        r = ag.recommend(s, {'input': ['shaft'], 'output': ['other']})
        self.assertIn('bolt', r['assembly_intent_draft']['stationary'])
        row = next(c for c in r['component_recommendations'] if c['instance'] == 'bolt')
        self.assertFalse(row['evidence']['pattern_motion_proven'])
        s['structural_relations']['patterns'][0]['seed_component_ids'].append('shaft')
        r = ag.recommend(s, {'input': ['shaft'], 'output': ['other']})
        self.assertIn('bolt', [c['instance'] for c in r['pending_components']])

    def test_suppressed_or_failed_constraints_do_not_seed_a_proposal(self):
        for change in ({'suppressed': True}, {'error': 1}, {'warning': True}):
            s = model(); s['mates'] = [{**mate(1, 'ground', 'cover', 'lock'), **change}]
            r = ag.recommend(s, {'input': ['shaft'], 'output': ['other']})
            self.assertNotIn('cover', r['assembly_intent_draft']['stationary'])

    def test_partial_inventory_cannot_produce_complete_draft(self):
        s = model(); s['inventory_complete'] = False
        self.assertFalse(ag.recommend(s, {})['complete'])

    def test_discovery_reuses_complete_native_survey_without_duplicate_inspection(self):
        s = survey(); calls = []
        def call(op, **kw):
            calls.append(op)
            self.assertEqual(op, '_survey_external_gear_pair')
            return s
        with temporary_workspace() as folder:
            session = SimpleNamespace(call=call, model=s['model_id'], folder=Path(folder),
                state=lambda *a: None, moving_hint='', reference_hint='', import_preflight=None)
            with patch.object(task.component_constraints, 'require_import_health'):
                task.discover(session)
            self.assertEqual(calls, ['_survey_external_gear_pair'])
            self.assertEqual(session.initial_inspection, {'components': s['components'], 'mates': s['mates']})

    def test_scope_review_returns_draft_and_questions_without_write_or_extra_native_call(self):
        s = survey(); extra = copy.deepcopy(s['components'][0])
        extra.update(component_id='extra', instance='unidentified', fixed_component=False, cylinders=[])
        s['components'].append(extra)
        with temporary_workspace() as folder:
            calls = []
            def call(op, **kw):
                calls.append(op); return s
            session = SimpleNamespace(call=call, model=s['model_id'], folder=Path(folder),
                state=lambda *a: None, moving_hint='', reference_hint='', import_preflight=None)
            with patch.object(task.component_constraints, 'require_import_health'):
                value = task.discover(session)['external_gear_pair']
            grouping = value['assembly_group_recommendation']
            self.assertFalse(grouping['complete'])
            self.assertEqual(grouping['pending_component_count'], 1)
            self.assertTrue((Path(folder)/'机械分组推荐.json').is_file())
            self.assertEqual(calls, ['_survey_external_gear_pair'])

    def test_nested_native_read_batches_restore_original_flag_after_each_failure_stage(self):
        source = r'''
using System;
class Check {
 static void Main(){
  foreach(bool initial in new[]{false,true}) foreach(int failedStage in new[]{-1,0,1,2}) {
   bool flag=initial;int writes=0;
   Func<bool> read=()=>flag;Action<bool> write=v=>{flag=v;writes++;};
   try {
    using(var outer=new NativeCommandBatch(read,write)) {
     for(int stage=0;stage<3;stage++) using(var nested=new NativeCommandBatch(read,write)) {
      if(!flag||!nested.Previous)throw new Exception("lost batch ownership");
      if(stage==failedStage)throw new InvalidOperationException("fixture");
     }
    }
   }catch(InvalidOperationException e){if(e.Message!="fixture")throw;}
   if(flag!=initial||writes!=(initial?0:2))throw new Exception("restoration or repeated writes");
  }
  Console.WriteLine("nested batches restored");
 }
}
'''
        with temporary_workspace() as folder:
            root = Path(__file__).resolve().parents[1]
            path = Path(folder)/'Check.cs'; path.write_text(source, encoding='utf8')
            exe = Path(folder)/'Check.exe'
            compiler = Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            subprocess.run([str(compiler), '/nologo', '/out:'+str(exe),
                str(root/'executor/NativeCommandBatch.cs'), str(path)], check=True, capture_output=True)
            self.assertEqual(subprocess.check_output([str(exe)], text=True).strip(), 'nested batches restored')


if __name__ == '__main__':
    unittest.main()
