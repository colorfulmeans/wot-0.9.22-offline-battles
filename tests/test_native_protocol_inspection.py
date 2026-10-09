"""Pinned registration decoder tests, not native protocol acceptance tests."""

import contextlib
import io
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import inspect_native_protocol_0922 as inspection


ADDRESS = 0x401000
NAME_ADDRESS = 0x402000
CLIENT_INTERFACE = 0x1A13CD4


def push(value):
    if -128 <= value <= 127:
        return b"\x6a" + struct.pack("<b", value)
    return b"\x68" + struct.pack("<I", value)


def call(target, offset):
    return b"\xe8" + struct.pack("<i", target - ADDRESS - offset - 5)


def registration(style=0, length=4, handler=0x503000,
                 interface=CLIENT_INTERFACE, target=inspection.ADD_ENTRY):
    code = b"".join(push(value) for value in (handler, length, style, NAME_ADDRESS))
    code += b"\xb9" + struct.pack("<I", interface)
    code += call(target, len(code))
    return code.ljust(48, b"\xcc")


def range_registration(remaining=2, interface=CLIENT_INTERFACE,
                       target=inspection.EXPAND_RANGE):
    code = b"\xa1" + struct.pack("<I", 0x503000)
    code += b"\xb9" + struct.pack("<I", interface)
    code += b"\x53\x6a" + bytes([remaining]) + b"\x50\x8a\x18"
    return (code + call(target, len(code))).ljust(48, b"\xcc")


class Constructor:
    def __init__(self, code):
        self.code = code

    def read(self, address, count):
        assert address == ADDRESS and count == 48
        return self.code

    def string(self, address):
        assert address == NAME_ADDRESS
        return "message"


def pe_payload(machine=0x14C, magic=0x10B):
    payload = bytearray(0x240)
    payload[:2] = b"MZ"
    struct.pack_into("<I", payload, 0x3C, 0x80)
    payload[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", payload, 0x84, machine, 1)
    struct.pack_into("<H", payload, 0x94, 0xE0)
    struct.pack_into("<H", payload, 0x98, magic)
    struct.pack_into("<I", payload, 0xB4, 0x400000)
    struct.pack_into("<IIII", payload, 0x180, 0x80, 0x1000, 0x40, 0x200)
    payload[0x200:0x240] = b"x" * 0x40
    return payload


class NativeProtocolInspectionTests(unittest.TestCase):
    def executable(self, payload):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "fixture.exe"
        path.write_bytes(payload)
        return inspection.Executable(path)

    def test_pe_mapping_uses_backed_raw_section_not_virtual_size(self):
        executable = self.executable(pe_payload())
        self.assertEqual(0x200, executable.offset(ADDRESS))
        self.assertEqual(b"xxxx", executable.read(ADDRESS, 4))
        for address in (0x400000, ADDRESS + 0x40):
            with self.subTest(address=address):
                with self.assertRaisesRegex(ValueError, "file-backed"):
                    executable.offset(address)

    def test_pe_rejects_signatures_and_wrong_architecture(self):
        bad_dos = pe_payload()
        bad_dos[:2] = b"??"
        bad_pe = pe_payload()
        bad_pe[0x80:0x84] = b"????"
        for payload, message in ((bad_dos, "DOS"), (bad_pe, "PE signature"),
                                 (pe_payload(machine=0x8664), "x86 PE32"),
                                 (pe_payload(magic=0x20B), "x86 PE32")):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.executable(payload)

    def test_pe_rejects_truncated_data_and_unbounded_names(self):
        executable = self.executable(pe_payload())
        with self.assertRaisesRegex(ValueError, "truncated"):
            executable.read(ADDRESS + 0x3F, 2)
        with self.assertRaisesRegex(ValueError, "unbounded"):
            executable.string(ADDRESS)
        payload = pe_payload()
        payload[0x200:0x208] = b"message\0"
        self.assertEqual("message", self.executable(payload).string(ADDRESS))

    def test_pe_reads_and_names_do_not_cross_raw_section_boundary(self):
        payload = pe_payload() + b"UNMAPPED\0"
        executable = self.executable(payload)
        self.assertEqual(b"x", executable.read(ADDRESS + 0x3F, 1))
        with self.assertRaisesRegex(ValueError, "truncated"):
            executable.read(ADDRESS + 0x3F, 4)
        with self.assertRaisesRegex(ValueError, "unbounded"):
            executable.string(ADDRESS + 0x3F)
        payload[0x23F] = 0
        self.assertEqual("x" * 0x3F, self.executable(payload).string(ADDRESS))

    def test_push_and_call_decode_signed_immediate_and_relative_target(self):
        self.assertEqual((-1, 2), inspection._push(b"\x6a\xff", 0))
        self.assertEqual((0xDEADBEEF, 5), inspection._push(push(0xDEADBEEF), 0))
        self.assertEqual(ADDRESS - 100, inspection._call_target(
            call(ADDRESS - 100, 0), 0, ADDRESS))
        with self.assertRaisesRegex(ValueError, "PUSH"):
            inspection._push(b"\x90", 0)
        with self.assertRaisesRegex(ValueError, "CALL"):
            inspection._call_target(b"\x90", 0, ADDRESS)

    def test_registration_decodes_all_length_styles(self):
        for style, label in inspection.LENGTH_STYLES.items():
            with self.subTest(style=style):
                interface, row = inspection._registration(Constructor(
                    registration(style=style, length=-1, handler=0)), ADDRESS)
                self.assertEqual(CLIENT_INTERFACE, interface)
                self.assertEqual({"name": "message", "lengthStyle": label,
                                  "lengthParameter": -1,
                                  "constructorVA": "0x401000",
                                  "handlerObjectVA": None}, row)
        row = inspection._registration(Constructor(registration()), ADDRESS)[1]
        self.assertEqual("0x503000", row["handlerObjectVA"])

    def test_unrelated_constructors_are_ignored(self):
        for code in (b"\x90" * 48, b"\x6a\x00" + b"\x90" * 46,
                     registration(interface=0x123456),
                     registration().replace(b"\xb9", b"\x90", 1)):
            with self.subTest(code=code.hex()):
                self.assertIsNone(inspection._registration(Constructor(code), ADDRESS))

    def test_known_registration_rejects_changed_helper_or_framing(self):
        for code, message in ((registration(target=inspection.ADD_ENTRY + 1), "target"),
                              (registration(style=3), "framing")):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    inspection._registration(Constructor(code), ADDRESS)

    def test_range_registration_decodes_remaining_ranges(self):
        for remaining in (1, 2):
            with self.subTest(remaining=remaining):
                self.assertEqual((CLIENT_INTERFACE, remaining), inspection._range(
                    Constructor(range_registration(remaining=remaining)), ADDRESS))
        self.assertIsNone(inspection._range(Constructor(registration()), ADDRESS))
        self.assertIsNone(inspection._range(Constructor(
            range_registration(interface=0x123456)), ADDRESS))

    def test_known_range_rejects_changed_body_or_helper(self):
        bad_body = bytearray(range_registration())
        bad_body[13] = 0x90
        for code, message in ((bad_body, "range registration"),
                              (range_registration(target=inspection.EXPAND_RANGE + 1),
                               "helper target")):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    inspection._range(Constructor(code), ADDRESS)

    def test_audit_rejects_changed_id_allocator_before_decoding_tables(self):
        with mock.patch.object(inspection, "inspect_client", return_value={}), \
                mock.patch.object(inspection, "Executable") as executable:
            executable.return_value.read.return_value = b"\0" * 8
            with self.assertRaisesRegex(ValueError, "next-ID implementation"):
                inspection.inspect_native_protocol("unused")
            executable.return_value.read.side_effect = [
                bytes.fromhex("8b46042b06c1f804"), b"\0" * 16]
            with self.assertRaisesRegex(ValueError, "range-allocation"):
                inspection.inspect_native_protocol("unused")

    def test_cli_reports_expected_inspection_failures_without_traceback(self):
        for error in (OSError("missing executable"), ValueError("wrong build"),
                      struct.error("truncated header")):
            with self.subTest(error=error), \
                    mock.patch.object(inspection, "inspect_native_protocol", side_effect=error), \
                    contextlib.redirect_stderr(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as caught:
                    inspection.main(["unused"])
                self.assertEqual(2, caught.exception.code)
                self.assertIn(str(error), output.getvalue())
                self.assertNotIn("Traceback", output.getvalue())

    @unittest.skipUnless(os.environ.get("WOT_0922_CLIENT"), "exact client not configured")
    def test_exact_client_registration_counts_and_ranges(self):
        report = inspection.inspect_native_protocol(os.environ["WOT_0922_CLIENT"])
        tables = report["interfaces"]
        self.assertEqual({"ClientInterface": 70, "BaseAppExtInterface": 16,
                          "LoginInterface": 4},
                         {name: len(rows) for name, rows in tables.items()})
        self.assertEqual("authenticate", tables["ClientInterface"][0]["name"])
        self.assertEqual("baseAppLogin", tables["BaseAppExtInterface"][0]["name"])
        self.assertEqual("login", tables["LoginInterface"][0]["name"])
        self.assertEqual(254, tables["ClientInterface"][-1]["lastId"])
        self.assertEqual(254, tables["BaseAppExtInterface"][-1]["lastId"])


if __name__ == "__main__":
    unittest.main()
