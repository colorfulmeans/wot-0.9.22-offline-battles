"""Analytic native world for the real concurrent BOT combat control loop.

Only the external native world (flat ground, component boxes, visibility and
rendered matrices) is synthetic.  Orders are produced by BotPlanner and then
consumed by BotRuntime, BotAdapter/LocalDriver, BotControlBinding, AttackPolicy,
NativeAttackEvaluator, TriggerAdmission and the native worker gun/ammo classes.
No candidate, armor outcome, fire command, readiness or debit is prescribed.
These timings describe this Python fixture, never BigWorld frame rate.
"""
import collections
import copy
import math
import time

from test_player_combat_ownership import OwnershipScene
from test_player_fire_admission_complete import Pose, f, shot_geometry
from test_port_0922_bot_runtime import _flat_open_graph
from gui.mods.offline_lan_0922 import bot_runtime
from gui.mods.offline_lan_0922.vehicle_control.bot_binding import BotControlBinding
from gui.mods.offline_lan_0922.vehicle_control.strategy import BotPlanner


class MultiBotScene(OwnershipScene):
    def configure_workers(self, count=6, enemies=True, diverse=True, schedule='stress20'):
        self.configure(clip=1, burst=1)
        self.control.close()
        self.schedule = schedule
        self.battle._player_control = None
        template = copy.deepcopy(self.entity.typeDescriptor)
        observed = copy.deepcopy(self.runtime.state)
        self.battle._records.clear()
        self.battle._runtime.bigworld.entities.clear()
        self.descriptors = {}
        self.native_entities = {}
        self.actor_ids = tuple(range(11, 11 + count))
        self.current_actor = None
        self.current_channel = 'other'
        self.current_stage = None
        self.counts = collections.Counter()
        self.frame_counts = collections.Counter()
        self.evaluations = []
        self.evaluation_seconds = collections.Counter()
        self.frames = []
        self.launches_observed = []
        self.fire_attempts = []
        self.initial_ammo = {}
        self.routes = {}
        self.manifest = []
        self.latest_orders = {}
        self.next_plan = 0.
        native_blast = self.battle._projectile_he_blast_contact
        def blast(*args, **kwargs):
            previous = self.current_stage
            self.current_stage = 'he_surface'
            self.count('he_blast')
            try:
                return native_blast(*args, **kwargs)
            finally:
                self.current_stage = previous
        self.battle._projectile_he_blast_contact = blast
        half = (count + 1) // 2
        for index, actor in enumerate(self.actor_ids):
            side = 0 if index < half else 1
            slot = index if side == 0 else index - half
            team = 1 + side if enemies else 1
            x, z = (slot - (half - 1) / 2.) * 16., (-25. if side == 0 else 25.)
            yaw = 0. if side == 0 else math.pi
            descriptor = copy.deepcopy(template)
            descriptor.name = descriptor.type.name = 'japan:J16_ST_B1'
            descriptor.gun.reloadTime = 1.6 + (index % 3) * .4 if diverse else 2.
            descriptor.gun.clip = (2 if diverse and index % 2 else 1, .4)
            descriptor.gun.burst = (1, .1)
            descriptor.gun.rotationSpeed = 10.
            descriptor.turret.rotationSpeed = 10.
            shots = list(descriptor.gun.shots[:2])
            shots.append(copy.deepcopy(shots[0]))
            for shell_index, shot in enumerate(shots):
                shot.shell.compactDescr = 101 + shell_index
                shot.piercingPower = (300., 300.)
                shot.speed, shot.gravity, shot.maxDistance = 1000., 10., 5000.
                shot.shell.damage = (240., 60.)
            shots[2].shell.kind = 'HIGH_EXPLOSIVE'
            shots[2].shell.explosionRadius = 2.
            shots[2].piercingPower = (1., 1.)
            descriptor.gun.shots = shots
            self.descriptors[str(actor)] = descriptor
            self.manifest.append(dict(id=actor, team=team, slot=slot,
                name='Analytic actor %s' % actor, vehicle=str(actor),
                x=x, y=0., z=z, yaw=yaw))
        graph = _flat_open_graph()
        graph.update(origin=(-240., -240.), cell_size=16.,
                     bounds=(-248., -248., 248., 248.))
        self.battle._navigation_graph = graph
        self.battle._arena_bounds = graph['bounds']
        self.engine = bot_runtime.BotRuntime(1,
            descriptor_resolver=lambda name: self.descriptors[name],
            vehicle_selector=lambda raw: raw['vehicle'],
            ground_probe=lambda *unused: 0., physics_ground_probe=lambda *unused: 0.,
            direction_probe=lambda *args, **kwargs: dict(
                clear=True, collision=False, slope=0., water=False),
            world_receipt_probe=lambda *args, **kwargs: dict(
                clear=True, collision=False, slope=0., water=False),
            visibility_probe=self.visibility, firing_lane_probe=self.lane,
            direct_launch_origin_probe=lambda source, *unused: (
                source['x'], source['y'] + 2., source['z']),
            spawn_resolver=lambda team, slot: ((0., 0., 0.), 0.),
            baked_graph=graph, bounds=graph['bounds'], arena_bounds=graph['bounds'],
            control_seconds=(bot_runtime.WORKER_CONTROL_SECONDS if schedule == 'worker10' else None),
            control_factory=lambda engine, actor: self.make_binding(engine, actor))
        self.addCleanup(self.engine.close)
        self.engine.battle_start(dict(round_id=7, map='01_karelia',
            bot_authority_id=1, bot_skill_mode='brutal', bots=self.manifest))
        self.battle._bots = self.engine
        for index, actor in enumerate(self.actor_ids):
            raw, state = self.manifest[index], self.engine.states[actor]
            # Measured native critical/support inputs required by admission.
            state.update(critical=copy.deepcopy(observed['critical']), airborne=False,
                vertical_speed=0., siege_state=0, speed=0., fire_seq=0,
                yaw=raw['yaw'], pitch=0., roll=0., turret_yaw=0., gun_pitch=0.,
                gun_aligned=False)
            route = dict(id='analytic_route_%s' % actor,
                waypoints=[(raw['x'], raw['z'], False),
                           (raw['x'] + 8., raw['z'], False)],
                capacity=1, role_weights=dict(frontline=1.))
            state['route'] = route
            self.routes[actor] = copy.deepcopy(route)
            desc = self.descriptors[str(actor)]
            entity = self.vehicle(1000 + actor, (raw['x'], 0., raw['z']), raw['team'])
            # Source and target share the same installed physical descriptor.
            for component in ('chassis', 'hull', 'turret', 'gun'):
                observed_component = getattr(entity.typeDescriptor, component)
                installed = getattr(desc, component)
                installed.hitTester = observed_component.hitTester
                installed.materials = observed_component.materials
                installed.materials[0].armor = 30.
                installed.hitTester.on_hit = self.component_query
            entity.typeDescriptor = desc
            self.native_entities[actor] = entity
            record = self.battle._records.pop('bot:%s' % (1000 + actor))
            record.update(network_id=actor, state=state, spot_visible=True)
            self.battle._records['bot:%s' % actor] = record
            gun = self.engine._gun_states[actor]
            gun.elapsed = 100.
            gun.fully_aimed_dispersion = gun.dispersion = 1.e-7
            shell = 2 if diverse and index % 3 == 1 else 0
            remaining = [0, 0, 24] if shell == 2 else [24, 12, 12]
            self.engine._ammo_states[actor].restore(dict(ammo_remaining=remaining,
                shell_index=shell, next_shell_index=shell, ammo_reload_pending=False))
            self.engine._ammo_states[actor].publish(state)
            self.initial_ammo[actor] = tuple(remaining)
        self.sync_native_poses()
        self.battle._last_frame_time = self.now
        self.planner = BotPlanner()
        self.planner.reset(7)
        self.engine.control_planner = self.planner
        # Observe actual committed transactions without changing their result.
        native_queue = self.engine._queue_pending_launch
        def queue(launch, *args, **kwargs):
            binding = self.engine._actor_controls[int(launch['id'])]
            context = binding._trigger_context or {}
            evidence = dict(at=self.now, launch=copy.deepcopy(launch),
                actor=binding.actor_id, target=(context.get('candidate') or {}).get('target', {}).get('network_id'),
                context_source=(context.get('solution') or {}).get('source_pose'),
                actual_source=binding.source_pose(),
                ammo=tuple(binding.gun.ammo), clip=binding.gun.clip)
            result = native_queue(launch, *args, **kwargs)
            if result:
                self.launches_observed.append(dict(launch, evidence=evidence))
            return result
        self.engine._queue_pending_launch = queue
        self.world_queries[:] = []
        self.counts.clear()
        return self

    def count(self, kind):
        key = (self.current_actor, self.current_channel, kind)
        self.counts[key] += 1
        self.frame_counts[key] += 1

    def component_query(self):
        self.count('component')
        if self.current_stage == 'he_surface':
            self.count('he_surface_component')

    def world_probe(self, space, first, last, mask):
        if hasattr(self, 'counts'):
            self.count('world')
            if self.current_stage == 'he_surface':
                self.count('he_surface_world')
        return super(MultiBotScene, self).world_probe(space, first, last, mask)

    def visibility(self, source, target, *unused):
        # Analytic direct sight is independent of the native armor/fire proof.
        self.count('visibility')
        return True

    def lane(self, source, target):
        self.count('strategic_lane')
        start = (source['x'], source['y'] + 2., source['z'])
        end = target.get('position') or (target['x'], target['y'], target['z'])
        end = (end[0], end[1] + 1., end[2])
        return not any(shot_geometry.segment_box_entry_distance(start, end, box)
                       is not None for box in self.world)

    def make_binding(self, engine, actor):
        binding = BotControlBinding(self.battle, engine, actor)
        evaluator = binding.attack_policy.evaluator
        native_evaluate = evaluator.evaluate
        def evaluate(*args, **kwargs):
            previous = self.current_actor, self.current_channel
            self.current_actor = actor
            self.current_channel = args[6] if len(args) > 6 else kwargs['channel']
            started = time.perf_counter()
            try:
                self.count('candidate')
                result = native_evaluate(*args, **kwargs)
                self.evaluations.append((self.now, actor, self.current_channel,
                    result.get('target', {}).get('network_id'), result.get('line'),
                    result.get('passed'), result.get('reason')))
                return result
            finally:
                self.evaluation_seconds[(actor, self.current_channel)] += time.perf_counter() - started
                self.current_actor, self.current_channel = previous
        evaluator.evaluate = evaluate
        for name, channel in (('refine_order', 'control'), ('after_control', 'control'),
                              ('after_native_update', 'background'),
                              ('prepare_trigger', 'trigger'), ('validate_trigger', 'trigger')):
            native = getattr(binding, name)
            def wrapped(*args, _native=native, _channel=channel, _name=name, **kwargs):
                previous = self.current_actor, self.current_channel
                self.current_actor, self.current_channel = actor, _channel
                try:
                    source = binding.source_pose() if _name in ('prepare_trigger', 'validate_trigger') else None
                    solution = (binding.attack_policy.decision.get('candidate') or {}).get('solution') or {}
                    result = _native(*args, **kwargs)
                    if source is not None:
                        self.fire_attempts.append(dict(at=self.now, actor=actor,
                            stage=_name, observed=source, proved=solution.get('source_pose'),
                            result=({key: result.get(key) for key in ('status', 'reason')}
                                    if isinstance(result, dict) else result)))
                    return result
                finally:
                    self.current_actor, self.current_channel = previous
            setattr(binding, name, wrapped)
        return binding

    def sync_native_poses(self):
        for actor, entity in self.native_entities.items():
            state = self.engine.states[actor]
            point = state['x'], state['y'], state['z']
            self.pose(entity, point)
            entity.matrix.setRotateYPR((state['yaw'], state['pitch'], state['roll']))
            entity.matrix.translation = point
            entity.appearance.turretMatrix.setRotateYPR((state['turret_yaw'], 0., 0.))
            entity.appearance.gunMatrix.setRotateYPR((0., state['gun_pitch'], 0.))

    def plan(self):
        states = list(self.engine.states.values())
        contacts = []
        for target in states:
            sources = [row for row in states if row['team'] != target['team']]
            if not sources:
                continue
            contacts.append(dict(observing_team=3-target['team'],
                target_kind='bot', target_id=target['id'], target_team=target['team'],
                visible=True, fresh=True, time_left=2., health=target['health'],
                max_health=target['max_health'], x=target['x'], y=target['y'], z=target['z'],
                class_tag='mediumTank', shootable_by_bot_ids=[source['id']
                    for source in sources if self.lane(source, target)]))
        self.planner.report_contacts(contacts, self.planner.known_targets(states, []), self.now)
        manifest = [dict(self.manifest[index], profile=state['profile'], route=state['route'])
                    for index, state in enumerate(states)]
        for row in manifest:
            row['route'] = dict(row['route'], waypoints=[
                dict(x=point[0], y=0., z=point[1], pause=bool(point[2]))
                for point in row['route']['waypoints']])
        result = self.planner.build_orders(manifest, states, [], self.now)
        self.latest_orders = dict((row['id'], row) for row in result['orders'])
        self.engine._apply_orders(dict(bot_orders=result['orders'],
                                      bot_order_revision=result['revision']))

    def step(self, seconds=.05):
        self.fixture.now += seconds
        self.battle._last_frame_time = self.now
        self.frame_counts.clear()
        self.world_queries[:] = []
        self.sync_native_poses()
        wall, cpu = time.perf_counter(), time.process_time()
        if self.now >= self.next_plan:
            self.plan()
            self.next_plan = self.now + 1.
        if self.schedule == 'worker10':
            result = self.engine.update(seconds, self.now, [], [])
        else:
            result = self.engine._run_update_once(seconds, self.now, [], [], True, True)
        row = dict(at=self.now, wall=time.perf_counter()-wall,
            cpu=time.process_time()-cpu, counts=dict(self.frame_counts),
            shots=len(self.launches_observed), actors={})
        budget = getattr(self.engine, '_evaluation_budget', None)
        row['work_budget'] = budget.receipt() if budget is not None else None
        for actor, binding in self.engine._actor_controls.items():
            policy = binding.attack_policy
            atomic = policy._atomic_receipt
            row['actors'][actor] = dict(
                target=policy.decision.get('target'),
                action=policy.decision.get('action'), reason=policy.decision.get('reason'),
                ammo=tuple(binding.gun.ammo),
                loaded=binding.gun.shot_index, clip=binding.gun.clip,
                reload=binding.gun.reload_time, seq=binding.state['fire_seq'],
                armor_batches=policy.evaluator.cache_observations['armour_batches'],
                atomic_evaluations=atomic.get('evaluations', 0),
                atomic_world=atomic.get('world_chords', 0),
                atomic_armor=atomic.get('armour_collision_batches', 0),
                atomic_status=atomic.get('status'),
                atomic_reason=atomic.get('reason'))
        self.frames.append(row)
        return row

    def state_summary(self):
        return dict((actor, dict(ammo=list(self.engine._ammo_states[actor].remaining),
            seq=self.engine.states[actor]['fire_seq'],
            target=self.engine._actor_controls[actor].attack_policy.status(),
            failure=self.engine._actor_controls[actor]._last_fire_failure,
            mode=self.engine._decision_cache.get(actor, (None, None, None, {}))[3]))
            for actor in self.actor_ids)
