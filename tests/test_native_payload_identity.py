"""An old prebuilt module must never pass the source/artifact package gate."""
from pathlib import Path
import importlib.util
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_payload_proof', ROOT/'tools/verify_native_payload.py')
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)


class NativePayloadIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ('native/bridge.cpp', 'native/law.h', 'native/law.inc',
                     'tools/build_math_batch_native.sh', 'tools/verify_native_payload.py'):
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'original input\n')

    def image(self, stamp=None, machine=0x14c):
        image = bytearray(160)
        image[:2] = b'MZ'
        struct.pack_into('<I', image, 60, 128)
        image[128:132] = b'PE\0\0'
        struct.pack_into('<H', image, 132, machine)
        return bytes(image)+(proof.source_stamp(str(self.root)) if stamp is None else stamp)+b'\0'

    def test_current_shipping_stamp_passes_but_old_binary_fails(self):
        self.assertTrue(proof.verify_bytes(str(self.root), self.image()))
        for data in (self.image(b'legacy unstamped payload'), self.image(machine=0x8664), b''):
            with self.assertRaises(ValueError):
                proof.verify_bytes(str(self.root), data)

    def test_all_native_inputs_invalidate_the_existing_image(self):
        for path in sorted(self.root.rglob('*')):
            if not path.is_file():
                continue
            with self.subTest(path=path.name):
                original = path.read_bytes()
                image = self.image()
                path.write_bytes(original+b'changed')
                with self.assertRaises(ValueError):
                    proof.verify_bytes(str(self.root), image)
                path.write_bytes(original)

    def test_include_inventory_and_line_endings(self):
        image = self.image()
        path = self.root/'native/law.inc'
        path.write_bytes(b'original input\r\n')
        self.assertTrue(proof.verify_bytes(str(self.root), image))
        (self.root/'native/new.inc').write_bytes(b'new law\n')
        with self.assertRaises(ValueError):
            proof.verify_bytes(str(self.root), image)

    def test_generated_header_and_duplicate_stamps(self):
        output = self.root/'build/identity.h'
        proof.write_header(str(self.root), str(output))
        self.assertIn(proof.source_stamp(str(self.root)), output.read_bytes())
        with self.assertRaises(ValueError):
            proof.verify_bytes(str(self.root), self.image()+proof.source_stamp(str(self.root))+b'\0')
