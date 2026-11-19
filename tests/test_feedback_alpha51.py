"""Behavioral regressions for grounded goals and cylindrical mechanism intent."""
import copy
import math
import unittest
from sw_mcp import assembly_connections as j,connection_trials as t,connection_groups as groups
from sw_mcp import connection_mate_changes as masks,connection_batches as batches,mechanism_loop as loop
from sw_mcp import mate_redundancy
from tests.test_assembly_connections import survey
from tests.test_assembly_constraints import component,mate
from tests.test_mechanism_loop import fixture


class ConnectionFeedbackTests(unittest.TestCase):
    def test_public_schema_accepts_cylinder_and_rejects_coerced_mate_ids(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        import motion_server as server
        tid='a'*32;engine=SimpleNamespace(tasks={tid:{}},plan=Mock(return_value={'accepted':True}))
        args={'task_id':tid,'connection_intent':[{'component_a':'moving','component_b':'body','kind':'cylindrical'}],
              'mate_changes':[{'native_feature_id':7,'suppressed':True}]}
        with patch.object(server,'_task_engine',engine):
            value=asyncio.run(server.mcp.call_tool('plan_mechanism_task',args));self.assertFalse(value.is_error)
            self.assertEqual(engine.plan.call_args.kwargs['mate_changes'],args['mate_changes'])
            for field,bad in [('native_feature_id',True),('native_feature_id','7'),('suppressed',1)]:
                request=copy.deepcopy(args);request['mate_changes'][0][field]=bad;engine.plan.reset_mock()
                value=asyncio.run(server.mcp.call_tool('plan_mechanism_task',request));self.assertTrue(value.is_error)
                engine.plan.assert_not_called()

    def test_grounded_group_pair_order_does_not_require_releasing_body(self):
        s=survey();s['components'].append(component('foot'));old=copy.deepcopy(s)
        group=[{'name':'frame','members':['body','foot'],'anchor':'body'}]
        outcomes=[]
        for a,b in [('body','moving'),('moving','body')]:
            p=groups.expand(s,[{'component_a':a,'component_b':b,'kind':'prismatic'}],group,whole_assembly=True)
            self.assertEqual(p['status'],'group_expanded');self.assertFalse(p['fixed_state_changes']);outcomes.append(p['goals'])
        self.assertEqual(outcomes[0],outcomes[1]);self.assertEqual(s,old)

    def test_cylinder_rank_and_material_axis_at_offset_and_arbitrary_angle(self):
        axis=j.ac.unit([1,2,3]);point=[.2,.3,.7];origin=[.1,-.2,.4];scale=.013
        rows=j.target_rows('cylindrical',axis,point,origin,scale);v=j.mobility(rows,origin,scale)
        self.assertEqual(len(j.ac.basis(rows)),4);self.assertEqual(v['local_free_coordinates'],2)
        self.assertEqual(v['recommended_joint_type'],'cylindrical')
        self.assertTrue(j._line_matches({'axis_global':axis,'reference_point_global_m':point},
                                      {'axis_global':v['axis_global'],'reference_point_global_m':v['axis_point_global_m']}))
        # A screw-like 2-space with transverse freedom is not a cylinder.
        self.assertIsNone(j.mobility([[float(i==k) for i in range(6)] for k in [0,1,2,3]],origin,scale)['recommended_joint_type'])

    def test_cylinder_requires_only_unlocked_concentric_and_both_drivers(self):
        p=j.plan(survey(),[{'component_a':'moving','component_b':'body','kind':'cylindrical'}])
        self.assertEqual(p['status'],'plan_ready');self.assertEqual([a['kind'] for a in p['actions']],['concentric'])
        self.assertIsNotNone(p['goals'][0]['rotary_trial_driver'])
        existing=survey([mate(1,'body','moving','cylindrical_axis')])
        self.assertEqual(j.plan(existing,[{'component_a':'moving','component_b':'body','kind':'cylindrical'}])['actions'],[])

    def test_cylindrical_measure_allows_axial_and_twist_but_rejects_radial_tilt(self):
        s=survey();poses={c['component_id']:c['transform'] for c in s['components']}
        goal={'component_a':'moving','component_b':'body','kind':'cylindrical','axis_global':[0,0,1],'reference_point_global_m':[0,0,0]}
        bound=t.bind(goal,poses)
        for amount in [-.0001,.0001]:
            after=copy.deepcopy(poses);after['moving']=t.target(poses['moving'],[0,0,1],amount)
            after['moving']=t.target(after['moving'],[0,0,1],.0008,True,[0,0,0])
            self.assertTrue(t.measure(bound,after)['passed'])
        for axis,angular in [([1,0,0],False),([0,1,0],True)]:
            after=copy.deepcopy(poses);after['moving']=t.target(poses['moving'],axis,.0001,angular,[0,0,0])
            self.assertFalse(t.measure(bound,after)['passed'])
        trials=t.trials(goal,poses);self.assertEqual(len(trials),8)
        self.assertEqual(sum(v['allowed'] for v in trials),4)

    def test_empty_axes_return_measured_radial_gap_and_never_a_choice_question(self):
        s=survey();s['components'][1]['cylinders'][0]['reference_point_global_m']=[3.1e-7,0,1.5e-3]
        p=j.plan(s,[{'component_a':'moving','component_b':'body','kind':'cylindrical'}])
        self.assertEqual(p['status'],'axis_reference_unavailable');self.assertEqual(p['axis_choices'],[])
        self.assertAlmostEqual(p['axis_diagnostics']['parallel_axis_radial_gap_min_m'],3.1e-7)
        self.assertFalse(p['axis_diagnostics']['automatic_alignment_performed'])

    def test_locked_loop_names_prefix_witness_without_deletion_instruction(self):
        s,goals,primary=fixture();goals.append({'component_a':'drive','component_b':'frame','kind':'rigid'})
        with self.assertRaises(loop.LoopReviewError) as caught:loop.review(s,goals,loop.ideal_graph(s,goals).matrix,primary,['output'])
        witness=caught.exception.diagnostics['conflict_witness'];self.assertEqual(witness['goal_index'],4)
        self.assertEqual((witness['input_rank_before'],witness['input_rank_after']),(5,6))
        self.assertTrue(witness['witness_is_not_unique_cause_or_deletion_authorization'])

    def test_cylindrical_coupling_in_closed_loop_retains_primary_check(self):
        s,goals,p=fixture();goals[-1]['kind']='cylindrical'
        r=loop.review(s,goals,loop.ideal_graph(s,goals).matrix,p,['output'])
        self.assertEqual(r['coupled_goal_indices'],[3]);self.assertFalse(r['finite_motion_verified'])

    def test_masks_virtual_only_exact_freeze_and_no_silent_noop(self):
        s=survey([mate(5,'body','moving','planar_normal')]);s['mates'][0]['name']='axial';old=copy.deepcopy(s)
        virtual,changes=masks.prepare(s,[{'native_feature_id':5,'suppressed':True}])
        self.assertEqual(s,old);self.assertTrue(virtual['mates'][0]['suppressed']);self.assertFalse(changes[0]['before'])
        p=j.plan(virtual,[{'component_a':'moving','component_b':'body','kind':'cylindrical'}],whole_assembly=True)
        p['mate_changes']=changes;tx=batches.prepare(p)
        import json
        self.assertEqual(json.loads(tx['payloads'][0])['mate_changes'],changes)
        with self.assertRaisesRegex(ValueError,'already_in_requested_state'):masks.prepare(virtual,[{'native_feature_id':5,'suppressed':True}])
        with self.assertRaisesRegex(ValueError,'duplicate'):masks.prepare(s,[{'native_feature_id':5,'suppressed':True}]*2)
    def test_advanced_limit_distance_is_not_accepted_as_a_basic_distance_mask_change(self):
        s=survey([mate(5,'body','moving','planar_normal')]);s['mates'][0].update(name='limit',native_feature_type='MateLimitDistance')
        with self.assertRaisesRegex(ValueError,'healthy_basic_mate'):masks.prepare(s,[{'native_feature_id':5,'suppressed':True}])
        s['mates'][0].pop('native_feature_type');s['nonlinear_constraints']=[{'native_feature_id':5,'kind':'limit_distance'}]
        with self.assertRaisesRegex(ValueError,'healthy_basic_mate'):masks.prepare(s,[{'native_feature_id':5,'suppressed':True}])

    def test_local_mask_requires_the_exact_declared_pair(self):
        s=survey([mate(5,'body','moving','planar_normal')]);s['components'].append(component('unrelated'))
        request=[{'native_feature_id':5,'suppressed':True}]
        local=[{'component_a':'moving','component_b':'unrelated'}]
        with self.assertRaisesRegex(ValueError,'matching_declared_pair'):masks.prepare(s,request,local_goals=local)
        local[0]['component_b']='body'
        self.assertTrue(masks.prepare(s,request,local_goals=local)[1][0]['after'])

    def test_drive_review_differentiates_unconnected_and_axially_blocked(self):
        s=survey()
        drive={'component_id':'moving','axis_global':[0,0,1],'reference_point_global_m':[0.,0.,0.]}
        body={'component_id':'body'}
        unattached=mate_redundancy.drive_review(s,drive,body,'linear')
        self.assertFalse(unattached['reference_link_observed'])
        s=survey([mate(0,'body','moving','planar_normal')])
        blocked=mate_redundancy.drive_review(s,drive,body,'linear')
        self.assertTrue(blocked['reference_link_observed'])
        self.assertEqual(blocked['status'],'supported_direction_blocked_at_start')
        self.assertFalse(blocked['root_cause_proven'])

    def test_existing_mixed_coincident_mate_needs_a_complete_matching_ring(self):
        feature=mate(1,'moving','body','cylindrical_axis',t=0)
        face=feature['entities'][0]['geometry']
        circle=feature['entities'][1]['geometry']
        face['cylinder_radius_m']=.01
        circle.update(kind='circular_edge',circle_radius_m=.01,full_circle=True)
        self.assertEqual(len(j.ac.basis(j.ac._rows(feature,feature['entities'],[0,0,0],1))),4)
        circle['full_circle']=False
        with self.assertRaisesRegex(ValueError,'contact_unverified'):
            j.ac._rows(feature,feature['entities'],[0,0,0],1)

    def test_same_part_pairs_report_an_extra_axial_location_as_a_candidate(self):
        members=[{**component(name),'path':path,'configuration':'Default'}
                 for name,path in [('base-left','base.SLDPRT'),('base-right','base.SLDPRT'),
                                   ('slider-left','slider.SLDPRT'),('slider-right','slider.SLDPRT')]]
        mates=[mate(1,'base-left','slider-left','cylindrical_axis'),mate(2,'base-right','slider-right','cylindrical_axis'),
               mate(3,'base-right','slider-right','planar_normal')]
        result=mate_redundancy.axial_variations({'components':members,'mates':mates})
        self.assertEqual([(row['native_feature_id'],row['local_rank_without_candidate']) for row in result],[(3,4)])
        self.assertEqual(result[0]['peer_pairs_with_observed_axial_freedom'],[['base-left','slider-left']])
        self.assertFalse(result[0]['automatic_suppression_allowed'])


if __name__=='__main__':unittest.main()
