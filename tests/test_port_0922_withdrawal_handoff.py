"""Withdrawal safety refusal and defensive holds preserve recovery ownership."""
import unittest
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter


class WithdrawalHandoffTests(unittest.TestCase):
    def setUp(self):
        self.adapter = BotAdapter('04_himmelsdorf', 1)
        self.state = dict(id=24, slot=0, team=2, position=(0.,0.,0.), yaw=0.,
                          speed=0., dt=.1, half_length=3.5, half_width=1.5,
                          neighbours=[], pose_clear=lambda yaw: True)
        self.order = dict(combat_mode='under_fire_withdraw', target_id=5,
                          aim_position=(0.,0.,100.), face_position=(0.,0.,100.),
                          move_position=(0.,0.,-20.), fire_range=500.,
                          throttle_override=None)

    def decide(self, clear=lambda *args: True):
        return self.adapter.decide_with_order(self.state,self.order,clear)

    def test_denied_reverse_immediately_returns_to_checked_driver(self):
        command = self.decide(lambda *args: False)
        self.assertEqual('rear_refused',command['withdrawal']['phase'])
        self.assertGreater(self.adapter.driver.states[24]['clock'], 0.)
        self.assertTrue(self.adapter._withdrawal_attempts[24]['fallback'])

    def test_friendly_rear_sweep_veto_does_not_freeze_driver_clock(self):
        self.state['neighbours'] = [dict(id=23,team=2,alive=True,
            position=(0.,0.,-8.),yaw=0.,half_width=1.5,half_length=3.5)]
        command = self.decide()
        self.assertEqual(23,command['withdrawal']['reverse_blocked_by'])
        self.assertGreater(self.adapter.driver.states[24]['clock'], 0.)

    def test_defensive_hold_does_not_erase_spent_withdrawal(self):
        for unused in range(90): self.decide()
        receipt = self.adapter._withdrawal_attempts[24]
        self.assertTrue(receipt['fallback'])
        self.order.update(throttle_override=0.,move_position=(0.,0.,0.))
        self.decide()
        self.assertIs(receipt,self.adapter._withdrawal_attempts[24])
        self.order.update(throttle_override=None,move_position=(0.,0.,-20.))
        self.assertNotEqual('reverse_withdraw',self.decide()['recovery_mode'])

    def test_tiny_forward_backward_oscillation_does_not_renew_withdrawal(self):
        for frame in range(100):
            self.state['position']=(0.,0.,.05 if frame%2 else -.05)
            command=self.decide()
        self.assertNotEqual('reverse_withdraw',command['recovery_mode'])

    def test_real_reverse_progress_keeps_frontal_withdrawal(self):
        for frame in range(120):
            self.state['position']=(0.,0.,-frame*.03)
            self.assertEqual('reverse_withdraw',self.decide()['recovery_mode'])
