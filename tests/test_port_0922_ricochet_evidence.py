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
        self.material=types.SimpleNamespace(kind=17,armor=100.,vehicleDamageFactor=1.)
        self.contact=dict(component='vehicleHull',distance=.4,material=self.material,
            result=0,layer='structural',angle_cos=.1,effective_armor=1000.,piercing=200.)
        self.data=dict(target_key='bot:21',impact=(1.,2.,3.),world_normal=(0.,1.,0.))
        self.meta=dict(projectile_id='2:p:1:5',round_id=2,ricochet_count=0,
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
        self.assertEqual('vehicleHull',rows[1]['bounce']['component'])
        self.assertEqual('vehicleTurret',rows[1]['component'])
        self.assertEqual(504,rows[1]['damage'])
        self.assertEqual(frozen,effect)

    def test_budget_resets_by_round_and_logging_failure_is_contained(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            for unused in range(100):
                self.emit(dict(self.meta),self.contact,{'shot_result':0,'damage':0})
            fresh=dict(self.meta,round_id=3)
            self.emit(fresh,self.contact,{'shot_result':0,'damage':0})
        self.assertEqual(65,len(output.getvalue().splitlines()))
        self.data['impact']=object()
        effect={'shot_result':2,'damage':504}
        self.emit(dict(self.meta,ricochet_count=1),self.contact,effect)
        self.assertEqual({'shot_result':2,'damage':504},effect)


if __name__=='__main__': unittest.main()
