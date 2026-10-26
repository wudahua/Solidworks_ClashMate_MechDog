"""Mechanically distinct counterexamples for the shared constraint analyzer."""
import copy
import asyncio
import math
import unittest
from pathlib import Path
from unittest.mock import patch
from sw_mcp import assembly_constraints as ac
from sw_mcp import assembly_completion as completion
from sw_mcp.bridge import Bridge


def component(cid, fixed=False, point=None):
    return {'component_id':cid, 'instance':cid, 'fixed_component':fixed,
            'transform':[1,0,0,0,1,0,0,0,1]+(point or [0,0,0])+[1,0,0,0]}


def mate(mid, a, b, kind, axis=None, point=None, t=None):
    types={'cylindrical_axis':1, 'planar_normal':0, 'lock':16}
    entities=[]
    for cid in (a,b):
        entities.append({'component_id':cid, 'geometry':{'kind':kind,
            'axis_global':axis or [0,0,1], 'reference_point_global_m':point or [0,0,0]}})
    return {'native_feature_id':mid,'name':'native_'+str(mid),'type':types[kind] if t is None else t,
            'error':0,'warning':False,'suppressed':False,'entities':entities}


class AssemblyConstraintTests(unittest.TestCase):
    def analyze_pair(self, mates, a_fixed=True, seeds=None):
        return ac.analyze([component('a',a_fixed),component('b')],mates,seeds)

    def test_native_floating_or_fully_constrained_flag_never_proves_grounding(self):
        cs=[component('a',True),component('b')]
        cs[1]['constraint_state']={'status':'observed','fully_constrained':True,'native_value':3}
        r=ac.analyze(cs,[])
        self.assertEqual(r['groups']['stationary'],['a'])
        self.assertIsNone(r['components'][1]['global_remaining_DOF'])
        self.assertEqual(r['components'][1]['status'],'mechanical_intent_required')

    def test_concentric_retains_axial_and_rotary_freedoms(self):
        r=self.analyze_pair([mate(1,'a','b','cylindrical_axis')])
        self.assertEqual(r['pair_constraints'][0]['supported_local_rank'],4)
        self.assertEqual(r['completion_suggestions'][0]['missing_relative_constraints_if_rigid_intent_confirmed'],2)
        self.assertFalse(r['completion_suggestions'][0]['fix_component_recommended'])

    def test_concentric_plus_axial_plane_is_revolute_not_rigid(self):
        r=self.analyze_pair([mate(1,'a','b','cylindrical_axis'),mate(2,'a','b','planar_normal')])
        self.assertEqual(r['pair_constraints'][0]['supported_local_rank'],5)
        self.assertIsNone(r['components'][1]['suggested_group'])
        self.assertEqual(r['completion_suggestions'][0]['missing_relative_constraints_if_rigid_intent_confirmed'],1)
        self.assertTrue(r['completion_suggestions'][0]['requires_mechanical_intent_confirmation'])

    def test_unknown_lock_property_does_not_lock_rotation(self):
        for observation in ({},{'status':'unavailable','locked':True},{'status':'observed','locked':False}):
            m=mate(1,'a','b','cylindrical_axis');m['rotation_lock_observation']=observation
            self.assertEqual(self.analyze_pair([m,mate(2,'a','b','planar_normal')])['pair_constraints'][0]['supported_local_rank'],5)

    def test_observed_lock_with_axial_constraint_is_conditionally_rigid(self):
        m=mate(1,'a','b','cylindrical_axis');m['rotation_lock_observation']={'status':'observed','locked':True}
        r=self.analyze_pair([m,mate(2,'a','b','planar_normal')])
        self.assertEqual(r['groups']['stationary'],['a','b'])
        self.assertFalse(r['motion_verified'])
        self.assertFalse(r['redundancy_or_compatibility_verified'])

    def test_three_orthogonal_planes_ground_all_six_relative_coordinates(self):
        ms=[mate(i,'a','b','planar_normal',axis=n) for i,n in enumerate(([1,0,0],[0,1,0],[0,0,1]))]
        r=self.analyze_pair(ms)
        self.assertEqual(r['pair_constraints'][0]['supported_local_rank'],6)
        self.assertEqual(r['groups']['stationary'],['a','b'])
        self.assertEqual(r['counts']['minimum_complement_suggestions'],0)

    def test_duplicate_mates_never_inflate_rank_or_prove_redundancy(self):
        ms=[mate(i,'a','b','planar_normal') for i in range(8)]
        p=self.analyze_pair(ms)['pair_constraints'][0]
        self.assertEqual(p['supported_local_rank'],3)
        self.assertFalse(p['redundant_mate_proven'])

    def test_suppressed_failed_and_unsupported_mates_cannot_ground_components(self):
        for key,value in [('suppressed',True),('error',1),('warning',True),('type',10)]:
            m=mate(1,'a','b','lock');m[key]=value
            r=self.analyze_pair([m])
            self.assertEqual(r['groups']['stationary'],['a'])
            self.assertEqual(r['components'][1]['status'],'mechanical_intent_required')

    def test_ground_and_rotor_on_same_rigid_cluster_are_conflicting(self):
        r=self.analyze_pair([mate(1,'a','b','lock')],seeds={'input':['b']})
        self.assertEqual(r['components'][1]['status'],'group_conflict')
        self.assertFalse(r['write_dispatched'])

    def test_seed_fixed_rotor_release_is_distinct_from_grounded_housing(self):
        cs=[component('a',True),component('b',True),component('c',True)]
        r=ac.analyze(cs,[mate(1,'b','c','lock')],{'input':['b','c']})
        self.assertEqual(set(r['groups']['input']),{'b','c'})
        self.assertEqual(r['groups']['stationary'],['a'])

    def test_moving_neighbors_and_stationary_neighbors_remain_distinct(self):
        cs=[component('a',True),component('b'),component('bearing')]
        ms=[mate(1,'a','bearing','cylindrical_axis'),mate(2,'b','bearing','cylindrical_axis')]
        r=ac.analyze(cs,ms,{'input':['b']})
        q=next(q for q in r['questions'] if q['component_id']=='bearing')
        self.assertEqual(set(q['candidate_groups']),{'stationary','input'})
        self.assertFalse(any(s['component_id']=='bearing' for s in r['completion_suggestions']))

    def test_constraints_to_multiple_grounded_peers_combine_without_false_pair_rigidity(self):
        cs=[component('a',True),component('b',True),component('c')]
        ms=[mate(1,'a','c','planar_normal',axis=[1,0,1]),mate(2,'b','c','cylindrical_axis',axis=[1,0,0])]
        r=ac.analyze(cs,ms)
        self.assertIn('c',r['groups']['stationary'])
        self.assertTrue(all(p['supported_local_rank']<6 for p in r['pair_constraints']))

    def test_names_and_instance_count_do_not_control_classification(self):
        cs=[component('a',True),component('b')];ms=[mate(1,'a','b','lock')]
        before=ac.analyze(cs,ms)
        cs[0]['instance']='轴承螺栓齿轮';cs[1]['instance']='unknown_shape_471'
        after=ac.analyze(cs,ms)
        self.assertEqual(before['groups'],after['groups'])
        self.assertNotEqual(before['input_sha256'],after['input_sha256'])

    def test_coordinate_translation_and_scale_do_not_change_rank(self):
        for scale in (.001,1,1000):
            p=[x*scale for x in (100,-250,80)]
            ms=[mate(1,'a','b','cylindrical_axis',point=p),mate(2,'a','b','planar_normal',point=p)]
            cs=[component('a',True,p),component('b',False,p)]
            self.assertEqual(ac.analyze(cs,ms)['pair_constraints'][0]['supported_local_rank'],5)

    def test_unsupported_inventory_does_not_return_partial_success(self):
        r=ac.analyze([component('a'),component('a')],[])
        self.assertEqual(r['status'],'unsupported_inventory')
        self.assertFalse(r['motion_verified'])

    def test_missing_geometry_is_preserved_as_unknown_not_absence(self):
        m=mate(1,'a','b','cylindrical_axis');m['entities'][1]['geometry']={}
        r=self.analyze_pair([m])
        self.assertEqual(r['counts']['omitted_constraints'],1)
        self.assertTrue(r['unsupported_constraints_are_not_absent'])

    def test_missing_activity_or_health_evidence_cannot_prove_rigidity(self):
        for key in ('suppressed','error'):
            m=mate(1,'a','b','lock');m.pop(key)
            r=self.analyze_pair([m])
            self.assertEqual(r['groups']['stationary'],['a'])
            self.assertEqual(r['counts']['omitted_constraints'],1)

    def test_cone_and_datum_axes_are_read_only_constraint_evidence(self):
        for kind in ('conical_axis','reference_axis'):
            m=mate(1,'a','b','cylindrical_axis')
            g=m['entities'][1].pop('geometry');g.update(kind=kind,creation_reference_supported=False)
            m['entities'][1]['constraint_geometry']=g
            self.assertEqual(self.analyze_pair([m])['pair_constraints'][0]['supported_local_rank'],4)

    def test_analysis_is_pure_and_summary_is_bounded(self):
        cs=[component('a',True)]+[component('b'+str(i)) for i in range(30)]
        ms=[mate(i,'a','b'+str(i),'planar_normal') for i in range(30)]
        original=copy.deepcopy((cs,ms));r=ac.analyze(cs,ms,inventory_complete=False)
        self.assertEqual((cs,ms),original)
        summary=ac.summary(r,3)
        self.assertFalse(summary['inventory_complete'])
        self.assertEqual(len(summary['mechanical_questions']),3)
        self.assertTrue(summary['questions_truncated'])

    def test_pattern_members_are_not_marked_missing_mates_or_rigid(self):
        cs=[component('a',True),component('b')]
        structure={'components':[{'component_id':'a','instance':'a','native_feature_id':1},
            {'component_id':'b','instance':'b','native_feature_id':2,'is_pattern_instance':True,
             'parent_features':[{'native_feature_id':1},{'native_feature_id':3}]}],
            'patterns':[{'native_feature_id':3,'suppressed':False,'seed_component_ids':['a'],
                         'child_features':[{'native_feature_id':2}]}]}
        r=ac.analyze(cs,[],structural_relations=structure)
        self.assertEqual(r['pattern_dependencies'][0]['seed_component_ids'],['a'])
        self.assertFalse(r['pattern_dependencies'][0]['rigid_motion_proven'])
        self.assertFalse(r['pattern_dependencies'][0]['missing_mates_proven'])
        self.assertIsNone(r['components'][1]['suggested_group'])

    def test_bridge_report_failure_preserves_native_result_without_requery(self):
        b=Bridge.__new__(Bridge);b.root=Path('unused')
        native={'components':[component('a',True)],'mates':[],'model_id':'example'}
        with patch('sw_mcp.conversation.core.write',side_effect=OSError('test disk failure')):
            out=b._annotate_constraint_review(native)
        self.assertEqual(out['model_id'],'example')
        self.assertEqual(out['components'],native['components'])
        self.assertEqual(out['assembly_constraint_review']['status'],'analysis_unavailable')
        self.assertFalse(out['assembly_constraint_review']['automatic_CAD_retry'])


class CompletionTests(unittest.TestCase):
    def fixture(self):
        cs=[component('a',True),component('b'),component('i'),component('o')]
        for c in cs:
            c['completion_planes']=[{'native_reference':c['component_id']+'-'+str(i),
                'reference_kind':'datum_plane','axis_global':n,'reference_point_global_m':[0,0,0]}
                for i,n in enumerate(([1,0,0],[0,1,0],[0,0,1]))]
        return {'components':cs,'mates':[mate(1,'a','b','cylindrical_axis'),mate(2,'a','b','planar_normal')]}

    def plan(self,s):
        return completion.plan(s,{'stationary':['a','b'],'input':['i'],'output':['o']},
            {'stationary':'a','input':'i','output':'o'})

    def test_revolute_attachment_gets_one_independent_supplement_and_no_fix(self):
        p=self.plan(self.fixture())
        self.assertEqual(len(p['actions']),1)
        self.assertEqual(p['actions'][0]['independent_constraint_gain'],1)
        self.assertEqual(p['fixed_state_changes'],[])
        self.assertEqual(p['existing_mates_deleted'],[])
        self.assertEqual(p['existing_mates_suppressed'],[])
        self.assertEqual(p['uncompleted_components'],[])
        self.assertFalse(p['native_compatibility_verified'])

    def test_existing_rigid_connection_needs_no_added_mate(self):
        s=self.fixture();s['mates']=[mate(1,'a','b','lock')]
        self.assertEqual(self.plan(s)['actions'],[])

    def test_pattern_child_is_reused_without_individual_constraint(self):
        s=self.fixture();s['structural_relations']={'components':[{'component_id':'b','is_pattern_instance':True}]}
        p=self.plan(s)
        self.assertEqual(p['actions'],[])
        self.assertEqual(p['reused_pattern_component_ids'],['b'])
        self.assertFalse(p['pattern_motion_verified'])

    def test_independent_free_body_uses_independent_constraints_instead_of_fix(self):
        s=self.fixture();s['mates']=[];p=self.plan(s)
        self.assertEqual(sum(a['independent_constraint_gain'] for a in p['actions']),6)
        self.assertEqual(p['planned_supported_rank']-p['initial_supported_rank'],6)
        self.assertEqual(p['fixed_state_changes'],[])
        self.assertEqual(len(p['actions']),1)
        self.assertEqual(p['actions'][0]['kind'],'rigid_lock')

    def test_missing_references_are_uncompleted_not_guessed(self):
        s=self.fixture();s['components'][1]['completion_planes']=[]
        p=self.plan(s)
        self.assertEqual(p['actions'],[])
        self.assertEqual(p['uncompleted_components'],['b'])

    def test_group_names_are_exact_complete_and_disjoint(self):
        cs=self.fixture()['components']
        for intent in ({'stationary':['a'],'input':['i'],'output':['o']},
                       {'stationary':['a','b'],'input':['i','b'],'output':['o']},
                       {'stationary':['a','b'],'input':['I-wrong'],'output':['o']}):
            with self.assertRaises(ValueError):completion.declared_groups(cs,intent)
        self.assertEqual(completion.declared_groups(cs,{'stationary':['a','b'],'input':['i'],'output':['o']})['stationary'],['a','b'])

    def test_sparse_rank_trial_is_nonmutating_and_duplicate_independent_gain_zero(self):
        b=completion.SparseBasis();self.assertTrue(b.add({0:1.,2:2.}))
        before=copy.deepcopy(b.pivots)
        self.assertEqual(b.trial([{0:2.,2:4.},{1:1.}]),1)
        self.assertEqual(b.pivots,before)
        self.assertFalse(b.add({0:3.,2:6.}))

    def test_general_engine_is_not_limited_to_two_gear_group_names(self):
        s=self.fixture()
        groups={'stationary':['a','b'],'slider':['i'],'connecting_rod':['o']}
        p=completion.plan(s,groups,{'stationary':'a','slider':'i','connecting_rod':'o'})
        self.assertEqual(p['groups'],groups)
        self.assertEqual(len(p['actions']),1)

    def test_declared_groups_remain_intent_and_never_certify_constraints(self):
        r=ac.analyze([component('a',True),component('b')],[],{'stationary':['a','b']})
        self.assertEqual(r['components'][1]['group_source'],'proposed_intent_seed')
        self.assertFalse(r['components'][1]['group_seed_is_rigidity_proof'])
        self.assertFalse(r['classification_complete_means_constraints_complete'])

    def test_plan_permutation_does_not_turn_a_rotary_joint_into_ground(self):
        s=self.fixture();s['components'].reverse()
        p=self.plan(s)
        self.assertEqual(len(p['actions']),1)
        self.assertEqual(p['actions'][0]['independent_constraint_gain'],1)

    def test_missing_native_constraint_geometry_is_not_a_no_mates_lock_trigger(self):
        s=self.fixture();s['mates'][0]['entities'][0]['geometry']={}
        p=self.plan(s)
        self.assertFalse(any(a['kind']=='rigid_lock' for a in p['actions']))

    def test_existing_circle_to_plane_coincidence_keeps_the_axial_constraint(self):
        m=mate(2,'a','b','planar_normal');m['entities'][0]['geometry']['kind']='circular_edge'
        r=ac.analyze([component('a',True),component('b')],[mate(1,'a','b','cylindrical_axis'),m])
        self.assertEqual(r['pair_constraints'][0]['supported_local_rank'],5)
        self.assertFalse(r['write_dispatched'])

    def test_public_intent_schema_accepts_name_lists_and_rejects_wrong_nested_types_without_dispatch(self):
        import motion_server
        calls=[]
        async def dispatcher(name,args):
            calls.append((name,args));return {'accepted':True}
        args={'task_id':'f'*32,'assembly_intent':{'stationary':['frame'],'input':['shaftA'],'output':['shaftB']}}
        with patch.object(motion_server.mcp,'tool_dispatcher',dispatcher,create=True):
            result=asyncio.run(motion_server.mcp.call_tool('plan_mechanism_task',args))
            self.assertEqual(result,{'accepted':True})
            for bad in (True,{'stationary':True},{'stationary':[False]}):
                result=asyncio.run(motion_server.mcp.call_tool('plan_mechanism_task',{**args,'assembly_intent':bad}))
                self.assertTrue(result.is_error)
                self.assertEqual(result.structured_content['error']['code'],'INVALID_ARGUMENT')
        self.assertEqual(len(calls),1)

    def test_public_card_excludes_opaque_completion_references(self):
        from test_external_gears import survey
        from sw_mcp.conversation.external_gears import recommend,public_card
        p=recommend(survey())['proposals'][0]
        p['constraint_completion']={'actions':[{'kind':'parallel','component_a':'a','component_b':'b',
            'reference_a':'opaque_native_a','reference_b':'opaque_native_b','reference_kind_a':'datum_plane'}]}
        text=str(public_card(p))
        self.assertNotIn('opaque_native',text)
        self.assertIn('parallel',text)



class ExactNativeSubsetTests(unittest.TestCase):
    def test_recommendation_is_explicit_and_respects_all_budgets(self):
        from sw_mcp.native_grid import recommend_exact_native_subset as recommend
        r=recommend(1,30,80,[2500])
        self.assertEqual(r['requested_output_fps'],30);self.assertEqual(r['recommended_sampling_fps'],50)
        self.assertTrue(r['requires_plan_confirmation']);self.assertTrue(r['future_native_grid_not_proven'])
        self.assertFalse(r['interpolation_allowed'])
        self.assertEqual(recommend(1,30,80,[30,60,True])['recommended_sampling_fps'],30)
        self.assertIsNone(recommend(1,30,80,[8,True]))
        self.assertEqual(recommend(1,30,80,[50])['recommended_sampling_fps'],50)
        self.assertEqual(recommend(1,100,80,[2500])['recommended_sampling_fps'],100)
        with self.assertRaises(ValueError):recommend(30,30,128,[2500])
        with self.assertRaises(ValueError):recommend(.001,30,80,[2500])

    @unittest.skipUnless(__import__('os').name=='nt','Windows C# pure policy compiler')
    def test_exact_native_membership_and_failure_counterexamples_in_production_policy(self):
        import os,subprocess,uuid
        root=Path(__file__).resolve().parents[1];folder=root/'runs/subset-policy'/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
        source=folder/'Checks.cs'
        source.write_text(r"""
using System;using System.Linq;
class Checks {
 static int checks;static void Check(bool ok){checks++;if(!ok)throw new Exception("check "+checks);}
 static bool Test(double[] raw,double[] expected,double duration,int fps,int native){double[] selected;int[] indices;double e;return NativeGridSubset.TrySelect(raw,expected,duration,fps,native,out selected,out indices,out e);}
 static int Main(){try{
 var raw=Enumerable.Range(0,2501).Select(i=>(double)i/2500).ToArray();var expected=Enumerable.Range(0,51).Select(i=>(double)i/50).ToArray();
 double[] selected;int[] indices;double error;
 Check(NativeGridSubset.TrySelect(raw,expected,1,50,2500,out selected,out indices,out error));
 Check(selected.Length==51&&indices[1]==50&&indices[50]==2500&&selected.Select((x,i)=>x==raw[indices[i]]).All(x=>x));
 Check(!Test(raw,Enumerable.Range(0,31).Select(i=>(double)i/30).ToArray(),1,30,2500));
 Check(!Test(raw.Take(2500).ToArray(),expected,1,50,2500));
 foreach(double bad in new[]{double.NaN,double.PositiveInfinity}){var x=(double[])raw.Clone();x[1]=bad;Check(!Test(x,expected,1,50,2500));}
 var corrupt=(double[])raw.Clone();corrupt[1]+=.00001;Check(!Test(corrupt,expected,1,50,2500));
 corrupt=(double[])raw.Clone();corrupt[1]=corrupt[0];Check(!Test(corrupt,expected,1,50,2500));
 var wrong=(double[])expected.Clone();wrong[1]+=.0001;Check(!Test(raw,wrong,1,50,2500));
 Check(!Test(raw,expected,double.NaN,50,2500));Check(!Test(raw,expected,1,50,5000));
 Check(!Test(raw.Reverse().ToArray(),expected,1,50,2500));
 Check(!Test(null,expected,1,50,2500));Check(!Test(new double[100002],expected,1,50,2500));
 Check(!Test(Enumerable.Range(0,126).Select(i=>(double)i/2500).ToArray(),new[]{0.0,.02,.04},.05,50,2500));
 raw[50]+=1e-9;Check(NativeGridSubset.TrySelect(raw,expected,1,50,2500,out selected,out indices,out error));
 Check(selected[1]==raw[50]&&selected[1]!=expected[1]&&error>0&&error<1e-7);
 Console.WriteLine(checks);return 0;}catch(Exception e){Console.Error.WriteLine(e);return 1;}}
}
""",encoding='utf8',newline='\n')
        exe=folder/'Checks.exe';csc=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        compile_result=subprocess.run([str(csc),'/nologo','/out:'+str(exe),str(root/'executor/NativeGridSubset.cs'),str(source)],capture_output=True)
        (folder/'compile.log').write_bytes(compile_result.stdout+compile_result.stderr)
        self.assertEqual(compile_result.returncode,0,(compile_result.stdout+compile_result.stderr).decode('utf8',errors='replace'))
        result=subprocess.run([str(exe)],capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
        self.assertGreaterEqual(int(result.stdout.strip()),17)

if __name__=='__main__':unittest.main()
