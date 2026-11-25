"""Inspect actual archive entries, accepting only Git newline conversion.

verify_archive keeps checking releases up to 1.1.2, which shipped the
diagnostic batch; verify_current_archive checks current releases.
"""
import importlib.util
import io
from pathlib import Path
import unittest
import os
import tempfile
import textwrap
from types import SimpleNamespace
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('launch_entry_verifier', ROOT/'tools/verify_launch_entries.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class LaunchEntryTests(unittest.TestCase):
    def archive(self, newline=b'\n', omit=None, change=None):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr(verifier.NORMAL_ENTRY, b'launcher version checked separately')
            for name in verifier.ENTRIES:
                if name == omit:
                    continue
                data = (ROOT/'tools'/name).read_bytes().replace(b'\r\n', b'\n')
                if name == change:
                    old = b'--diagnostics'
                    self.assertIn(old, data)
                    data = data.replace(old, b'--other-mode')
                archive.writestr(name, data.replace(b'\n', newline))
        stream.seek(0)
        return zipfile.ZipFile(stream)

    def test_lf_entries_match_the_reviewed_scripts(self):
        with self.archive() as archive:
            self.assertEqual(verifier.ENTRIES, verifier.verify_archive(archive))

    def test_windows_crlf_entries_match_the_same_reviewed_scripts(self):
        with self.archive(b'\r\n') as archive:
            self.assertEqual(verifier.ENTRIES, verifier.verify_archive(archive))

    def test_real_test_mode_change_is_rejected_even_with_crlf(self):
        with self.archive(b'\r\n', change='START_DIAGNOSTIC_TEST.bat') as archive:
            with self.assertRaisesRegex(ValueError, 'differs.*START_DIAGNOSTIC_TEST'):
                verifier.verify_archive(archive)

    def test_additional_launch_entry_is_rejected(self):
        for name in ('EXTRA_TEST.bat', 'EXTRA_TEST.cmd', 'EXTRA_TEST.ps1', 'other.exe'):
            with self.subTest(name=name), self.archive() as archive:
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, 'w') as extra:
                    for member in archive.namelist():
                        extra.writestr(member, archive.read(member))
                    extra.writestr(name, b'retired development mode')
                stream.seek(0)
                with zipfile.ZipFile(stream) as extra:
                    with self.assertRaisesRegex(ValueError, 'only the normal and diagnostic'):
                        verifier.verify_archive(extra)

    def test_download_workflow_checks_actual_root_files_including_the_executable(self):
        workflow = (ROOT / '.github/workflows/build-launcher.yml').read_text(encoding='utf-8')
        self.assertIn('verify_current_archive(archive)', workflow)
        start = workflow.index('          payload, fake082, fake0922 = sys.argv[1:4]')
        end = workflow.index('          for port in core.SUPPORTED_PORTS:', start)
        snippet = textwrap.dedent(workflow[start:end])
        for extra in ('START_DIAGNOSTIC_TEST.bat', 'unexpected-test.bat'):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                app = Path(directory)
                (app / '_internal').mkdir()
                (app / verifier.NORMAL_ENTRY).write_bytes(b'validated launcher')
                context = dict(io=io, os=os, zipfile=zipfile,
                               sys=SimpleNamespace(argv=['check', str(app / '_internal'), 'fake082', 'fake0922']),
                               verify_current_archive=verifier.verify_current_archive)
                with mock.patch('builtins.print'):
                    exec(compile(snippet, '<downloaded-root-check>', 'exec'), context)
                    (app / extra).write_bytes(b'development entry')
                    with self.assertRaisesRegex(ValueError, 'only the normal launch entry'):
                        exec(compile(snippet, '<downloaded-root-check>', 'exec'), context)

    def test_current_release_ships_only_the_launcher_executable(self):
        def archive(*names):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as output:
                for name in names:
                    output.writestr(name, b'entry')
            stream.seek(0)
            return zipfile.ZipFile(stream)

        nested = '_internal/tools/helper.exe'
        with archive(verifier.NORMAL_ENTRY, nested, 'README.txt') as current:
            self.assertEqual((verifier.NORMAL_ENTRY,),
                             verifier.verify_current_archive(current))
        for names in ((verifier.NORMAL_ENTRY, 'START_DIAGNOSTIC_TEST.bat'),
                      (verifier.NORMAL_ENTRY, 'EXTRA.cmd'),
                      (verifier.NORMAL_ENTRY, 'EXTRA.ps1'),
                      ('other.exe',), ()):
            with self.subTest(names=names), archive(*names) as release:
                with self.assertRaisesRegex(ValueError, 'only the normal launch entry'):
                    verifier.verify_current_archive(release)

    def test_each_required_entry_is_mandatory(self):
        for name in verifier.ENTRIES:
            with self.subTest(name=name), self.archive(omit=name) as archive:
                with self.assertRaisesRegex(ValueError, 'only the normal and diagnostic'):
                    verifier.verify_archive(archive)
