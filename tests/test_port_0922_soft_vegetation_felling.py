"""Only low-health native bush taxonomy is excluded from felling."""
import os
import sys
import unittest
import zipfile
import types
from unittest import mock
from pathlib import Path
import test_port_0922_destructibles as fixture
sensor = fixture.destructibles_sensor

class SoftVegetationFellingTests(unittest.TestCase):
    def test_only_identified_low_health_plants_skip_felling(self):
        skip = sensor._skip_soft_vegetation_felling_1513
        for name in ('shrub2', 'CattailCluster', 'juniper_grass', 'bush_01',
                     'sedge_1', 'fern', 'marigoldpatch', 'waterlily'):
            for health in (1, 3, 5):
                self.assertTrue(skip('speedtree/%s.spt' % name,
                    dict(type=1, health=health), 1))
        for name, typ, health in (('BananaTree_03', 1, 3), ('applewowtree', 1, 3), ('jux', 1, 3),
                ('oak', 1, 10), ('shrub', 1, 10), ('bush', 3, 5),
                ('bush', 2, 5), ('bush', 4, 5), ('bush', 1, 0),
                ('bush', 1, True), ('bush', 1, float('nan'))):
            self.assertFalse(skip('speedtree/%s.spt' % name,
                dict(type=typ, health=health), 1))

    def test_material_contact_does_not_dispatch_fall_for_soft_plant(self):
        area = types.SimpleNamespace(DESTR_TYPE_TREE=1, DESTR_TYPE_FALLING_ATOM=2,
            DESTR_TYPE_FRAGILE=3, DESTR_TYPE_STRUCTURE=4, g_destructiblesManager=object())
        decoded = (None, None, 22, 37, 71, 'speedtree/CattailCluster.spt')
        with mock.patch.dict(sys.modules, {'AreaDestructibles': area}), \
                mock.patch.object(sensor, '_decode_mat_info_1513', return_value=decoded), \
                mock.patch.object(sensor, '_destructible_isolated_1513', return_value=False), \
                mock.patch.object(sensor, '_runtime_material_descriptor_1513',
                    return_value=dict(type=1, health=3)), \
                mock.patch.object(sensor, 'validate_tree_identity_1513') as identity, \
                mock.patch.object(sensor, 'LOG_DEBUG', create=True):
            self.assertFalse(sensor._try_destroy_destructible(1, (), 0., 10.))
            identity.assert_not_called()

    @unittest.skipUnless(os.environ.get('WOT_0922_CLIENT'), 'requires exact client')
    def test_taxonomy_matches_exact_client_foliage_baker(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
        import bake_foliage_0922 as baker
        with zipfile.ZipFile(Path(os.environ['WOT_0922_CLIENT']) /
                'res/packages/misc.pkg') as archive:
            tokens = baker.bush_tokens(archive.read('speedtree/bushes.xml'))
        self.assertEqual(tokens, sensor._SOFT_VEGETATION_TOKENS_1513)

    @unittest.skipUnless(os.environ.get('WOT_0922_CLIENT'), 'requires exact client')
    def test_all_low_health_native_resources_have_reviewed_felling_scope(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
        import bake_foliage_0922 as baker
        with zipfile.ZipFile(Path(os.environ['WOT_0922_CLIENT']) /
                'res/packages/scripts.pkg') as archive:
            records = baker.tree_descriptors(archive.read('scripts/destructibles.xml'))
        retained = {name.rsplit('/', 1)[-1] for name, row in records.items()
            if 0 < row['health'] <= 5 and not sensor._skip_soft_vegetation_felling_1513(
                name, dict(type=1, health=row['health']), 1)}
        # Two real trees and one unresolved species retain their existing behavior.
        self.assertEqual({'applewowtree.spt', 'bananatree_03.spt', 'jux.spt'}, retained)
        stems = {name.rsplit('/', 1)[-1].rsplit('.', 1)[0] for name, row in records.items()
                 if 0 < row['health'] <= 5}
        self.assertTrue(sensor._SOFT_PLANT_STEMS_1513.issubset(stems))
