"""Bounded second-surface evidence cannot change an accepted HP proposal."""
import contextlib
import copy
import io
import json
import sys
from pathlib import Path
import types
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/res/scripts/client'))
from gui.mods.offline_lan_0922.battle_runtime import BattleRuntime


class RicochetEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.battle=BattleRuntime.__new__(BattleRuntime)
        self.battle._start_message={'round_id':2}
        self.material=types.SimpleNamespace(kind=17,armor=100.,vehicleDamageFactor=1.)
        self.contact=dict(component='vehicleHull',distance=.4,material=self.material,
            result=0,layer='structural',angle_cos=.1,effective_armor=1000.,piercing=200.)
        self.data=dict(target_key='bot:21',impact=(1.,2.,3.),world_normal=(0.,1.,0.))
        self.meta=dict(projectile_id='2:p:1:5',ricochet_count=0,
            segment_origin=[0.,0.,0.],segment_velocity=[100.,0.,0.])

    def emit(self, meta, contact, effect):
        self.battle._report_ricochet_contact_evidence(meta,{'elapsed':.1},
            self.data,contact,effect,())

    def test_pairs_distinct_surfaces_and_never_changes_damage(self):
        effect={'shot_result':0,'damage':0}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.emit(self.meta,self.contact,effect)
            self.emit(self.meta,self.contact,effect)
            self.meta.update(ricochet_count=1,segment_start_time_ms=100)
            self.contact.update(component='vehicleTurret',result=2)
            effect={'shot_result':2,'damage':504}
            frozen=copy.deepcopy(effect)
            self.emit(self.meta,self.contact,effect)
        rows=[json.loads(line.split('RICOCHET SURFACE EVIDENCE ',1)[1])
              for line in output.getvalue().splitlines()]
        self.assertEqual(2,len(rows))
        self.assertEqual(2,rows[0]['round'])
        self.assertEqual('vehicleHull',rows[1]['bounce']['component'])
        self.assertEqual('vehicleTurret',rows[1]['component'])
        self.assertEqual(504,rows[1]['damage'])
        self.assertEqual(frozen,effect)

    def test_budget_resets_by_round_and_logging_failure_is_contained(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            for unused in range(100):
                self.emit(dict(self.meta),self.contact,{'shot_result':0,'damage':0})
            self.battle._start_message={'round_id':3}
            fresh=dict(self.meta)
            self.emit(fresh,self.contact,{'shot_result':0,'damage':0})
        self.assertEqual(65,len(output.getvalue().splitlines()))
        self.data['impact']=object()
        effect={'shot_result':2,'damage':504}
        self.emit(dict(self.meta,ricochet_count=1),self.contact,effect)
        self.assertEqual({'shot_result':2,'damage':504},effect)

    def test_recorded_24mm_rehit_leaves_first_plane_and_keeps_microsecond_flight(self):
        from gui.mods.offline_lan_0922.projectile_runtime import (
            ideal_reflection_velocity, ricochet_departure_origin)
        import math
        impact = (-142.26346002889326, 2.5354233364855077, 4.089098255990514)
        normal = (.2917238175868988, .8402507901191711, -.4570293128490448)
        incoming = (-717.771343, 2.286192, -56.560478)
        velocity = ideal_reflection_velocity(incoming, normal)
        origin = ricochet_departure_origin(impact, velocity, normal)
        dot = lambda a,b: sum(x*y for x,y in zip(a,b))
        self.assertGreater(dot(velocity, normal), 0.)
        self.assertAlmostEqual(dot(incoming,incoming), dot(velocity,velocity), places=6)
        for actual, expected in zip(origin, (-142.262877, 2.537104, 4.088184)):
            self.assertAlmostEqual(actual, expected, places=6)
        second_normal = (.8388340473, .1034143269, .5344742537)
        self.assertLess(dot(velocity, second_normal), 0.)
        flight = .002417796291410923 / math.sqrt(dot(velocity,velocity))
        end = tuple(origin[i] + velocity[i] * .05 for i in range(3))
        self.data.update(query=(origin,end), impact=impact, world_normal=second_normal)
        self.contact.update(distance=.002417796291410923, result=2)
        self.meta.update(ricochet_count=1, segment_origin=origin,
            segment_velocity=velocity, ricochet_first_contact_evidence=dict(
                impact=impact, normal=normal, component='vehicleGun', material_kind=1))
        effect = {'shot_result':2,'damage':561}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.battle._report_ricochet_contact_evidence(self.meta,
                {'elapsed':flight}, self.data,self.contact,effect,())
        row=json.loads(output.getvalue().split('RICOCHET SURFACE EVIDENCE ',1)[1])
        self.assertAlmostEqual(3.35805, row['segment_elapsed_us'], places=3)
        self.assertGreater(row['contact_first_plane_mm'], 2.)
        self.assertLess(row['contact_from_bounce_mm'], 4.)
        self.assertEqual({'shot_result':2,'damage':561},effect)

    def test_rehit_preserves_native_surface_and_physical_inputs(self):
        collision=types.SimpleNamespace(compName='_reserved',dist=.26,hitAngleCos=.26,matInfo=self.material)
        self.data.update(penetration_factor=1.1,piercing_loss=3.,
            collision_evidence=[types.SimpleNamespace(collision=collision,
                worldNormal=(0.,-1.,0.),localPoint=(1.,2.,3.))])
        self.meta.update(ricochet_count=1,source_shot={'shell':{'kind':'ARMOR_PIERCING','caliber':90.}})
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.emit(self.meta,self.contact,{'shot_result':2,'damage':216})
        row=json.loads(output.getvalue().split('RICOCHET SURFACE EVIDENCE ',1)[1])
        self.assertEqual([0.,-1.,0.],row['surface_evidence'][0]['world_normal'])
        self.assertEqual([1.,2.,3.],row['surface_evidence'][0]['local_point'])
        self.assertEqual(90.,row['source_shot']['shell']['caliber'])
        self.assertEqual(1.1,row['penetration_factor'])

    def test_extended_armour_query_uses_extended_surface_evidence(self):
        collision=types.SimpleNamespace(compName='vehicleTurret',dist=4.,hitAngleCos=.9,matInfo=self.material)
        evidence=types.SimpleNamespace(collision=collision,
            worldNormal=(0.,1.,0.),localPoint=(4.,0.,0.))
        self.data['collision_evidence']=[]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.battle._report_ricochet_contact_evidence(self.meta,{},self.data,
                self.contact,{'shot_result':0,'damage':0},(),None,[evidence],
                ((0.,0.,0.),(5.,0.,0.)))
        row=json.loads(output.getvalue().split('RICOCHET SURFACE EVIDENCE ',1)[1])
        self.assertEqual(4.,row['surface_evidence'][0]['distance'])
        self.assertEqual([[0.,0.,0.],[5.,0.,0.]],row['resolved_query'])

    def test_selected_plate_is_distinct_from_the_first_contact(self):
        self.data.update(query=((0.,0.,0.),(10.,0.,0.)),impact=(.1,0.,0.),
            ricochet_contact={'impact':(4.,0.,0.),'resolved_time_ms':200})
        self.contact['distance']=4.
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.emit(self.meta,self.contact,{'shot_result':0,'damage':0})
        row=json.loads(output.getvalue().split('RICOCHET SURFACE EVIDENCE ',1)[1])
        self.assertEqual([.1,0.,0.],row['impact'])
        self.assertEqual([4.,0.,0.],row['selected_contact_impact'])
        self.assertEqual((4.,0.,0.),self.meta['ricochet_first_contact_evidence']['selected_contact_impact'])

    def test_raw_interface_input_output_is_linked_to_selected_surface(self):
        self.contact.update(component='vehicleHull',distance=.4,angle_cos=.1)
        collision=types.SimpleNamespace(compName='vehicleHull',dist=.4,hitAngleCos=.1,matInfo=self.material)
        native_query={'interface':'hitTester.localHitTest','native_interface':'BSPModel.collideSegment',
            'local_segment':[[0.,0.,0.],[1.,0.,0.]],
            'raw_hits':[{'distance':.4,'local_normal':[0.,1.,0.],'material_kind':17}]}
        evidence=types.SimpleNamespace(collision=collision,worldNormal=(0.,1.,0.),
            localPoint=(.4,0.,0.),nativeQuery=native_query)
        self.data['collision_evidence']=[evidence,evidence]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.emit(self.meta,self.contact,{'shot_result':0,'damage':0})
        row=json.loads(output.getvalue().split('RICOCHET SURFACE EVIDENCE ',1)[1])
        self.assertEqual([native_query],row['native_queries'])
        self.assertEqual(0,row['surface_evidence'][0]['native_query_index'])
        self.assertTrue(row['surface_evidence'][0]['selected'])
        self.assertEqual([native_query],self.meta['ricochet_first_contact_evidence']['native_queries'])

    def test_optional_metadata_failure_preserves_native_query_inputs(self):
        from gui.mods.offline_lan_0922.entities import remote_vehicle as rv
        class Tester:
            bbox = ((0.,0.,0.), (1.,2.,3.), 4.0)
            def getBspModel(self):
                raise KeyError('not_loaded')
            @property
            def bspModelName(self):
                raise KeyError('model_name')
        class Matrix:
            def applyPoint(self, point): return point
            def applyVector(self, point): return point
        matrix = Matrix()
        maths = types.SimpleNamespace(Vector3=lambda *xyz: xyz)
        row = rv._collision_interface_evidence(Tester(),
            {'itemTypeName': 'vehicleHull'}, 1, (1.,2.,3.), (4.,5.,6.),
            (7.,8.,9.), (10.,11.,12.), matrix, matrix, matrix, matrix, maths)
        self.assertEqual([(1.,2.,3.), (4.,5.,6.)], row['local_segment'])
        self.assertEqual([(0.,0.,0.), (1.,2.,3.)], row['bbox'])
        self.assertEqual([], row['raw_hits'])
        self.assertEqual('KeyError', row['metadata_errors']['getBspModel']['type'])
        self.assertEqual('KeyError', row['metadata_errors']['bspModelName']['type'])
        self.assertNotIn('capture_error', row)


if __name__=='__main__': unittest.main()
