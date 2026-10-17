"""Captured bridge-layer, physical support and carrier ownership regressions."""
import contextlib
import io
import math
import unittest
import types
import test_port_0922_battle_runtime as battle_fixture
from unittest import mock
import test_port_0922_contact_support_navigation as support
from test_port_0922_navigation import StaticHullNavigationTests, TerrainGrid
from gui.mods.offline_lan_0922 import vehicle_stack, vehicle_physics as vp


class BakedNavigationRollbackTests(unittest.TestCase):
    def scene(self):
        graph=StaticHullNavigationTests._flat_graph()
        return TerrainGrid(lambda x,z,hint:-15.,obstacle_probe=lambda *args:False,
                           baked_graph=graph,cell_size=4.)

    def test_baked_corridor_does_not_add_a_current_height_gate(self):
        grid=self.scene()
        with mock.patch.object(grid,'_live_baked_egress_clear') as live:
            self.assertTrue(grid.segment_clear((6.,-15.,6.),(10.,0.,6.)))
        live.assert_not_called()

    def test_local_candidates_keep_original_baked_height(self):
        grid=self.scene()
        target=grid.safe_local_target((6.,-15.,6.),(30.,0.,6.),0.)
        self.assertIsNotNone(target)
        self.assertEqual(0.,target[1])
        self.assertEqual(0.,grid._ground(6.,6.,-15.))

    def test_existing_short_egress_has_no_added_endpoint_storey_gate(self):
        grid=self.scene()
        self.assertTrue(grid._live_baked_egress_clear((6.,-15.,6.),(10.,0.,6.)))


class PhysicalPointTests(unittest.TestCase):
    scene=support.ContactSupportTests.scene

    def test_continuous_bank_support_does_not_inherit_drive_grade(self):
        runtime,state=self.scene(lambda x,z:.15*z*z)
        # The bank's derivative reaches 1.05: valid upward support, but
        # beyond the navigation climbing grade. The body has not pitched yet.
        self.assertTrue(runtime._basic_support_rise_is_continuous(state,0.,3.5,
            .15*3.5*3.5,0.))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(runtime._contact_edge_support_needed(state))
        self.assertEqual(5,sum(p['valid'] for p in runtime._basic_support_status(state)))

    def test_a_disconnected_deck_is_still_support_loss(self):
        runtime,state=self.scene(lambda x,z:0. if z<1.5 else 15.)
        self.assertFalse(runtime._basic_support_rise_is_continuous(state,0.,3.5,15.,0.))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(runtime._contact_edge_support_needed(state))


class CarrierTests(unittest.TestCase):
    def test_tilted_solver_contact_owns_carrier_even_when_origin_is_distant(self):
        point=dict(x=0.,y=0.,z=-3.,side='left',static_compression=.1)
        params=dict(springs=(point,),pseudo_contacts=())
        solved=dict(height=3.,pitch=-math.pi/4,roll=0.)
        # Native support ray was queried before the solver rotated the body.
        native=[(('bot',12),{},(0.,1.,-3.)),(('bot',15),{},(5.,2.9,5.))]
        self.assertEqual(['bot',12],vehicle_stack.settled_carrier(params,[1.],[],
            solved,(0.,3.,0.),0.,0.,0.,native))
        # The last ray is not the contact owner, nor may a stale ray survive
        # loss of geometric contact on a subsequent airborne frame.
        self.assertIsNone(vehicle_stack.settled_carrier(params,[1.],[],
            dict(solved,height=10.),(0.,10.,0.),0.,0.,0.,native))
        self.assertIsNone(vehicle_stack.settled_carrier(params,[1.],[],
            solved,(0.,3.,0.),0.,0.,0.,native[1:]))

    def test_adapter_uses_committed_contact_instead_of_the_last_ray(self):
        battle=battle_fixture.BattleRuntime(battle_fixture._runtime())
        battle.client=types.SimpleNamespace(player_id=1)
        battle._local_pitch=battle._local_roll=0.
        battle._collision_shape=lambda unused:(1.5,3.,0.,2.)
        entity=types.SimpleNamespace(typeDescriptor=object())
        def solve(*args):
            context=battle._stack_context
            context['actor']['_stack_carrier']=['bot',15]
            context['hits']=[(('bot',12),{},(0.,1.,0.)),(('bot',15),{},(0.,2.9,0.))]
            context['contact_carrier']=['bot',12]
            return (0.,3.,0.)
        battle._update_vertical_motion_impl=solve
        battle._update_vertical_motion(entity,(0.,3.,0.),0.,.1)
        self.assertEqual(['bot',12],battle._local_stack_carrier)
        battle._local_support_rise_blocked=True
        battle._update_vertical_motion(entity,(0.,3.,0.),0.,.1)
        self.assertIsNone(battle._local_stack_carrier)
        battle._local_support_rise_blocked=False
        def leave(*args):
            battle._stack_context['contact_carrier']=None
            return (0.,10.,0.)
        battle._update_vertical_motion_impl=leave
        battle._update_vertical_motion(entity,(0.,10.,0.),0.,.1)
        self.assertIsNone(battle._local_stack_carrier)

    def test_native_miss_cannot_be_replaced_by_box_overlap(self):
        params=dict(springs=(dict(x=0.,y=0.,z=0.,side='left',static_compression=.1),),pseudo_contacts=())
        self.assertIsNone(vehicle_stack.settled_carrier(params,[0.],[],
            dict(height=0.,pitch=0.,roll=0.),(0.,0.,0.),0.,0.,0.,[]))
