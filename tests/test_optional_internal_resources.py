"""Source leads cannot silently become invented internal collision zones."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import audit_optional_internal_resources as audit


class InventoryTests(unittest.TestCase):
    def test_exact_identity_geometry_marker_and_absence_stay_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'res/packages').mkdir(parents=True)
            (root/'version.xml').write_text('<version>test fixture</version>')
            with zipfile.ZipFile(root/'res/packages/vehicles_level_06.pkg', 'w') as archive:
                archive.writestr('vehicles/german/G136_Tiger_131/collision_client/Hull.havok', b'armor_01')
                archive.writestr('vehicles/american/A104_M4A3E8A/normal/lod0/Hull.primitives', b'\0ammoBay\0')
                archive.writestr('vehicles/american/A86_T23E3_variant/Hull.hkx', b'\0fuelTank\0')
            report = audit.scan(root)['vehicles']
            self.assertEqual('no_named_interior_source_found', report['G136_Tiger_131']['conclusion'])
            self.assertEqual('needs_mesh_and_0922_registration_review', report['A104_M4A3E8A']['conclusion'])
            self.assertEqual(0, report['A86_T23E3']['members'])


if __name__ == '__main__':
    unittest.main()
