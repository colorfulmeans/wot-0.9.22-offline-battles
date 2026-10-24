"""The reviewed complete owner baseline ships to every installation."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import bot_tactics_store as storage


ROOT=Path(__file__).resolve().parents[2]
EXPECTED=json.loads((ROOT/'tests/fixtures/default_tactics_owner_20261024.json').read_text(encoding='utf8'))


class AdoptedDefaultTests(unittest.TestCase):
    def test_first_run_and_every_map_equal_the_reviewed_complete_owner_document(self):
        with tempfile.TemporaryDirectory() as temp:
            profile=storage.Store(temp).active()
            self.assertEqual('Default',profile['name'])
            self.assertEqual(EXPECTED['profile_digest'],storage.contract.digest(profile))
            for name,expected in EXPECTED['maps'].items():
                entry=profile['maps'][name]
                digest=hashlib.sha256(storage.contract.dumps(entry).encode('ascii')).hexdigest()
                self.assertEqual(expected['digest'],digest,name)
                self.assertEqual(expected['routes'],len(entry['default_routes']))
                self.assertEqual(expected['points'],sum(len(r['points']) for r in entry['default_routes']))

    def test_final_rear_guard_and_class_exclusions_survive_profile_one_deletion(self):
        profile=storage.contract.default_profile()
        entry=profile['maps']['04_himmelsdorf']
        rows=entry['default_routes']
        expected=[[2.0,-250.0,0],[-54.5749,-217.1544,0],[-125.8231,-164.8773,0],
                  [-130.4093,-62.6351,0],[-149.5248,0.9548,0],[-127.1684,159.9135,0],
                  [-123.0571,266.5681,0],[-93.5783,318.1559,0],[5.8701,326.0228,0],[70.0,346.0,0]]
        for team,points in ((1,expected),(2,list(reversed(expected)))):
            rear=next(r for r in rows if r['team']==team and r['id']=='rear_guard' and r.get('class_tag','all')=='all')
            self.assertEqual(points,rear['points'])
            self.assertFalse(rear.get('disabled',False))
            for identity,tag in (('rear_guard','lightTank'),('rail','heavyTank')):
                excluded=next(r for r in rows if r['team']==team and r['id']==identity and r.get('class_tag')==tag)
                self.assertFalse(excluded.get('disabled'))
                self.assertEqual('reserve',excluded['tier'])
        with tempfile.TemporaryDirectory() as temp:
            store=storage.Store(temp)
            store.save(storage.contract.default_profile('1'),apply=True)
            store.delete('1')
            self.assertEqual(['Default'],store.names())
            self.assertEqual(profile,store.active())
            self.assertEqual(profile,storage.Store(temp).active())

    def test_every_enabled_route_and_parking_exit_has_no_silent_fallback(self):
        profile=storage.contract.default_profile()
        for name in profile['maps']:
            graph=storage.graph_data(name)
            routes,outcomes=storage.runtime.default_routes(profile,name,graph)
            for edit in profile['maps'][name]['default_routes']:
                key='%s:%s'%(edit['team'],storage.contract.default_route_id(edit))
                self.assertEqual('route_deleted' if edit.get('disabled') else 'baked_route_connected',outcomes[key],(name,key))
            for identity,status,issues in storage.runtime.authoring_check(profile,name,graph,details=True):
                self.assertIn(status,('baked_route_connected','generic_parking_found'),(name,identity,issues))

    def test_existing_default_updates_but_independent_profiles_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            store=storage.Store(temp)
            root=Path(temp)
            root.mkdir(exist_ok=True)
            store.active_path.write_text(storage.contract.dumps(storage.contract.empty()),encoding='ascii')
            self.assertEqual(EXPECTED['profile_digest'],storage.contract.digest(store.active()))
            independent=storage.contract.empty('User custom')
            store.save(independent,apply=True)
            self.assertEqual(independent,storage.Store(temp).active())
            self.assertEqual(EXPECTED['profile_digest'],storage.contract.digest(store.read('Default')))


if __name__=='__main__':unittest.main()
