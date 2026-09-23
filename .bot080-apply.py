from pathlib import Path
import ast, hashlib, json, subprocess
ROOT=Path.cwd()
BASE='beb750bcc368bb4279959b53ef5aa4022158cba7'
OLD='5a7c20a124ab8ad76dc40db3012a31436ae6905b'
MP='src/res/scripts/client/gui/mods/offline_lan_0922/'
def show(ref,path):
    return subprocess.check_output(['git','show',ref+':'+path])
def nodes(s,cl):
    c=next(n for n in ast.parse(s).body if isinstance(n,ast.ClassDef) and n.name==cl)
    return {n.name:n for n in c.body if isinstance(n,ast.FunctionDef)}
def span(s,n):
    ls=s.splitlines(True);start=min([n.lineno]+[d.lineno for d in n.decorator_list])-1
    return sum(map(len,ls[:start])),sum(map(len,ls[:n.end_lineno]))
def method(s,name,source,cl='BotRuntime'):
    n=nodes(source,cl)[name];a,b=span(source,n);chunk=source[a:b];ns=nodes(s,cl)
    if name in ns:
        i,j=span(s,ns[name]);return s[:i]+chunk+s[j:]
    i,j=span(s,ns['_navigation_target']);return s[:i]+chunk+'\n'+s[i:]
def remove(s,name,cl='BotRuntime'):
    i,j=span(s,nodes(s,cl)[name]);return s[:i]+s[j:]
core=('ai/adapter.py','ai/driver.py','ai/traffic.py','ai/navigation.py')
for name in core:
    path=MP+name
    assert (ROOT/path).read_bytes()==show(BASE,path),path
    (ROOT/path).write_bytes(show(OLD,path))
p=ROOT/MP/'bot_runtime.py'
assert p.read_bytes()==show(BASE,MP+'bot_runtime.py')
t=p.read_text();old=show(OLD,MP+'bot_runtime.py').decode('utf-8')
for name in ('_planner_corridor_clear','_route_lane_target','_safe_route_lane_goal','_navigation_target','_traffic_stopping_distance','_cached_traffic_stopping_distance','_hard_contact_response'):
    t=method(t,name,old)
a='            planner_probe_samples = {}\n';b='            # Preserve the old refresh point:'
i=t.index(a,t.index('    def _update_once'));j=t.index(b,i)
u=old.index(a,old.index('    def _update_once'));v=old.index(b,u)
control=old[u:v]
needle="                command = timed_call(\n                    self._combat_diagnostics, 'bot.traffic',"
control=control.replace(needle,"                self._record_navigation_decision(\n                    state, command, reposition_order or server_order,\n                    planner_probe_samples, now)\n"+needle)
needle="                    decision_state['neighbours'], now, sample_clear)\n"
control=control.replace(needle,needle+"                self._record_navigation_adjustment(state, command, now)\n")
t=t[:i]+control+t[j:]
t=t.replace("'direction': key[2], 'result': summary", "'direction': key[2] if len(key) > 2 else 1.0, 'result': summary")
i=t.index('            # Pending routes belong to the authority frame,');j=t.index('        # Native terrain and visibility probes',i);t=t[:i]+t[j:]
t=t.replace("command.get('combat_mode') != 'base_defense',\n                combat_mode=command.get('combat_mode', 'route'),\n                movement_intent=command.get('movement_intent', True))", "command.get('combat_mode') != 'base_defense')")
i=t.index('            safety_body = {',t.index('    def _update_once'));j=t.index('            if siege_braking:',i)
t=t[:i]+"            active_brake = bool(siege_braking or command.get('brake', False))\n"+t[j:]
t=t.replace('pose_frozen, traffic_input, safety)', 'pose_frozen)')
a='            maximum_probe_distance = None\n';b='            cached_motion_probe = '
i=t.index(a,t.index('    def _update_once'));j=t.index(b,i);u=old.index(a,old.index('    def _update_once'));v=old.index(b,u);t=t[:i]+old[u:v]+t[j:]
a='            if not path_clear:\n';b='            steer_dir = 0\n'
i=t.index(a,t.index('    def _update_once'));j=t.index(b,i);u=old.index(a,old.index('    def _update_once'));v=old.index(b,u);t=t[:i]+old[u:v]+t[j:]
i=t.index('            self._settled_navigation_feedback(',t.index('    def _update_once'));j=t.index('            self._finish_motion_stall(',i);t=t[:i]+t[j:]
t=remove(t,'_settled_navigation_feedback');t=remove(t,'_navigation_recovery_allowed')
t=t.replace('        navigation_motion = {}\n','')
i=t.index("                if (resolved_motion and\n                        motion_status in ('clear', 'crushed')):",t.index('    def _update_once'));j=t.index('                if resolved_motion and callable(self.motion_report):',i);t=t[:i]+t[j:]
i=t.index('                    report_hard_contact = getattr(',t.index('    def _update_once'));j=t.index("                elif motion_status in ('soft', 'cap_crushed'):",i)
u=old.index('                    report_contact = getattr(',old.index('    def _update_once'));v=old.index("                elif motion_status in ('soft', 'cap_crushed'):",u);t=t[:i]+old[u:v]+t[j:]
t=t.replace('descriptor, step, now, normal=hard_contact_normal)', 'descriptor, step, now)')
i=t.index('                    rejected_delta = _angle_delta(',t.index('    def _update_once'));j=t.index('                    # Turning is a pose change',i);t=t[:i]+t[j:]
i=t.index('                    if abs(turn) > 0.01 and abs(throttle) > 0.01:',t.index('    def _update_once'));j=t.index("                self._turn_speeds[state['id']] = turn_speed",i);t=t[:i]+t[j:]
t=t.replace("(self._capability_probe(\n                                self.navigator.grid.segment_clear,\n                                self.navigation_planning_capability(bot_id))\n                             if self.navigator is not None else None)","(self.navigator.grid.segment_clear\n                             if self.navigator is not None else None)")
t=remove(t,'_capability_probe')
t=t.replace('                rotation_drive_held = False\n','').replace("                        'rotation_drive_held': rotation_drive_held,\n",'')
t=t.replace('        drive_support_failures = {}\n','').replace("                drive_support_failures[state['id']] = bool(\n                    state.get('_navigation_support_blocked', False))\n",'')
ast.parse(t)
assert hashlib.sha256(t.encode()).hexdigest()=='904e77f969fe46c145218425bfad0c934d2d1ea5fd2f22333cc370572a08ffec'
p.write_text(t)
# Restore the regression's original local-contact expectation with the code.
p=ROOT/'tests/test_port_0922_bot_runtime.py'
s=method(p.read_text(),'test_realised_hard_contact_invalidates_cached_command_and_probe',show(OLD,'tests/test_port_0922_bot_runtime.py').decode(),'BotRuntimeTests')
assert hashlib.sha256(s.encode()).hexdigest()=='d7f9cde178c3a47b2cd689d9078b2899ee718399c20a718f621c1aad3ef7a01e'
p.write_text(s)
# Retain immutable graph/material contracts; discard only tests requiring the
# explicitly reverted later connector/climb/contact-report policies.
s=(ROOT/'tools/test_immutable_navigation.py').read_text()
for name in ('test_contact_reporting_no_longer_enrols_a_region','test_read_only_displaced_hull_connector_keeps_wall_checks','test_baked_climb_approach_is_retained','test_runtime_reset_has_no_deleted_callback'):
    s=remove(s,name,'ImmutableNavigationTests')
s=s.replace('Static navigation removal contracts; not a native game-play or FPS test.','v0.8.0 driving rollback contracts; not native game-play or an FPS test.')
s=s.replace('IMMUTABLE_CLIENT_SOURCE','BOT080_CLIENT_SOURCE').replace('IMMUTABLE_TEST_REPORT','BOT080_TEST_REPORT').replace('immutable-navigation-tests.json','bot080-contract-tests.json')
insert='''    def test_four_driving_modules_match_the_verified_v080_source(self):
        proof=read_json(os.path.join(ROOT,'docs/testing/airfield-build-inputs-20260923.json'))
        for path,expected in proof['bot080_rollback']['core_sha256'].items():
            with open(os.path.join(ROOT,*path.split('/')),'rb') as stream:
                self.assertEqual(expected,hashlib.sha256(stream.read()).hexdigest(),path)

    def test_second_traffic_and_rotation_veto_owners_are_absent(self):
        from gui.mods.offline_lan_0922.ai.traffic import TrafficCoordinator
        from gui.mods.offline_lan_0922.ai.driver import LocalDriver
        self.assertFalse(hasattr(TrafficCoordinator,'safe_controls'))
        self.assertFalse(hasattr(LocalDriver,'wait_for_navigation'))
        source=os.path.join(ROOT,'src','res','scripts','client','gui','mods','offline_lan_0922','bot_runtime.py')
        with open(source,'rb') as stream: text=stream.read().decode('utf-8')
        for symbol in ('_blocked_rotations','sample_rotation_clear','traffic_obstacles','_settled_navigation_feedback'):
            self.assertNotIn(symbol,text)

'''
s=s.replace('    def test_removed_mechanism_has_no_methods_or_state(self):',insert+'    def test_removed_mechanism_has_no_methods_or_state(self):')
ast.parse(s);(ROOT/'tools/test_v080_bot_behavior.py').write_text(s)
s=(ROOT/'tools/verify_immutable_build.py').read_text()
s=s.replace('IMMUTABLE_CLIENT_SOURCE','BOT080_CLIENT_SOURCE').replace('IMMUTABLE_TEST_REPORT','BOT080_TEST_REPORT').replace('IMMUTABLE_SOURCE_SHA','BOT080_SOURCE_SHA')
s=s.replace('test_immutable_navigation','test_v080_bot_behavior').replace('immutable-','bot080-').replace('NO_NATIVE_REVIEW_BUILD_EVIDENCE.json','BOT080_BUILD_EVIDENCE.json').replace('dcbc5b686bb8f522175fc80d38cade4f756ccca6',BASE).replace('compiled navigation removal regressions failed','compiled v080 rollback contracts failed').replace('compiled removal tests','compiled rollback tests')
ast.parse(s);(ROOT/'tools/verify_v080_bot_build.py').write_text(s)
runner='''from pathlib import Path
import contextlib, os, subprocess, sys, types, unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'server'),str(ROOT/'tools')]
if len(sys.argv)>1 and sys.argv[1]=='historical':
    source=subprocess.check_output(['git','show','5a7c20a124ab8ad76dc40db3012a31436ae6905b:tests/test_port_0922_ai.py'],cwd=str(ROOT))
    module=types.ModuleType('v080_ai_tests');module.__file__=str(ROOT/'tests/test_port_0922_ai.py')
    exec(compile(source,module.__file__,'exec'),module.__dict__)
    suite=unittest.defaultTestLoader.loadTestsFromModule(module)
else:
    names=__NAMES__
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName('test_port_0922_bot_runtime.BotRuntimeTests.'+name) for name in names)
with open(os.devnull,'w') as noise,contextlib.redirect_stdout(noise):
    result=unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
'''
names='''test_decision_and_copied_motion_reuse_installed_physics
test_direction_probe_receives_speed_and_descriptor_contract
test_baked_planner_clear_cannot_bypass_native_selected_wall
test_reverse_final_world_receipt_receives_exact_travel_heading
test_hard_final_world_receipt_blocks_the_selected_motion
test_bot_soft_motion_contact_preserves_speed_without_moving
test_realised_hard_contact_invalidates_cached_command_and_probe
test_bot_cap_crush_keeps_real_speed_then_moves_next_tick
test_bot_drowning_requires_ten_continuous_seconds_and_publishes_death
test_bot_water_uses_hull_top_pose_and_recovery
test_bot_overturn_matches_ignore_recovery_and_death_law
test_bot_drive_uses_contacted_plane_instead_of_corridor_grade
test_bot_bridges_a_trench_narrower_than_its_chassis
test_bot_still_falls_off_a_cliff_edge_with_one_supported_end
test_hydraulic_bot_height_and_attitude_share_uneven_contact_plane
test_initial_and_restored_manifests_share_physics_installation
test_injected_baked_graph_replaces_runtime_grid_and_passes_routes
test_worker_stall_refreshes_control_once_and_consumes_all_elapsed
test_worker_low_fps_reuses_valid_drive_and_moves_continuously
test_worker_four_fps_keeps_turning_drive_active_between_plans
test_reverse_recovery_uses_driver_turn_sign_not_target_bearing
test_driver_proportional_turn_is_not_collapsed_to_keyboard_sign
test_limited_traverse_tank_turns_hull_before_advancing_or_firing
test_target_solution_cache_invalidates_and_burst_forces_freshness
test_the_manifest_publishes_each_bot_gunnery_tier
test_bot_physics_uses_plain_default_crew_factors
test_high_fps_contact_lease_pays_the_consumed_physical_time
test_baked_planner_ranking_never_replaces_selected_native_gate
test_traffic_wait_does_not_enter_reverse_recovery'''.split()
(ROOT/'tools/test_v080_runtime_boundaries.py').write_text(runner.replace('__NAMES__',repr(names)))
p=ROOT/'docs/testing/airfield-build-inputs-20260923.json';proof=json.loads(p.read_text())
proof['bot080_rollback']={'base':BASE,'behavior_source':OLD,'verified_v080_build_source':'4b532dabe74f9a63ef880bb8286ad3c61aec742e','core_sha256':{MP+n:hashlib.sha256((ROOT/MP/n).read_bytes()).hexdigest() for n in core},'source_report':'wot-error-report-20260923-170444-493dd6c415a7.zip','native_gameplay_tested':False,'preserved':'Current game features, final collision, vehicle physics, stun/radio/gunnery and all graph assets. Driving core and runtime decision ownership restored.'}
changed=[]
for path in proof['runtime_source_sha256_lf']:
    data=(ROOT/path).read_bytes().replace(b'\r\n',b'\n')
    proof['runtime_source_sha256_lf'][path]=hashlib.sha256(data).hexdigest()
    if data!=show(BASE,path).replace(b'\r\n',b'\n'):changed.append(path)
assert sorted(changed)==sorted([MP+n for n in core]+[MP+'bot_runtime.py']),changed
for rec in proof['changed_files']:
    if (ROOT/rec['path']).is_file():rec['sha256']=hashlib.sha256((ROOT/rec['path']).read_bytes()).hexdigest()
proof['scope']='v0.8.0 driving-core rollback on latest 0.9.3 feature/physics baseline; retain rebuilt Airfield and other 40 graphs; native test pending.'
p.write_text(json.dumps(proof,sort_keys=True,indent=2)+'\n')
for path in subprocess.check_output(['git','ls-tree','-r','--name-only',BASE,'navgraphs']).decode().splitlines():
    assert (ROOT/path).read_bytes()==show(BASE,path),path
subprocess.check_call(['git','add','src','tests/test_port_0922_bot_runtime.py','tools/test_v080_bot_behavior.py','tools/test_v080_runtime_boundaries.py','tools/verify_v080_bot_build.py','docs/testing/airfield-build-inputs-20260923.json'])
subprocess.check_call(['git','rm','.bot080-apply.py','.github/workflows/bot-rollback-source-audit.yml'])
print('Verified exact rollback: four v0.8.0 driving modules plus runtime control ownership; other 134 modules and all maps preserved.')
