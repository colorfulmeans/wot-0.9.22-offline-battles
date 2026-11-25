"""The CI gate finds invisible characters in new commits, changed text and notes."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'check_invisible_characters', ROOT / 'tools/check_invisible_characters.py')
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

# Code points, so this source file contains none of the characters it tests.
BOM = chr(0xFEFF)
ZERO_WIDTH_SPACE = chr(0x200B)
RIGHT_TO_LEFT_OVERRIDE = chr(0x202E)


class FindingTests(unittest.TestCase):
    def test_each_invisible_character_is_reported_with_its_position(self):
        self.assertEqual(
            ['notes.md:1:1: BYTE ORDER MARK (U+FEFF)'],
            gate.findings('notes.md', (BOM + 'Title\n').encode('utf-8')))
        self.assertEqual(
            ['a.py:2:4: ZERO WIDTH SPACE (U+200B)'],
            gate.findings('a.py', ('x = 1\ny =' + ZERO_WIDTH_SPACE + ' 2\n').encode('utf-8')))
        chinese = bytes((0xe4, 0xb8, 0xad, 0xe6, 0x96, 0x87))
        self.assertEqual([], gate.findings('a.py', b'clean ' + chinese + b' text\n'))
        self.assertEqual([], gate.findings('a.bin', b'\0' + BOM.encode('utf-8')))

    def test_vendored_files_keep_their_upstream_bytes(self):
        self.assertFalse(gate.checked_path('tools/vendor/upstream/file.txt'))
        self.assertTrue(gate.checked_path('tools/check_invisible_characters.py'))

    def test_the_gate_sources_contain_no_invisible_characters(self):
        for path in ('tools/check_invisible_characters.py',
                     'tests/test_invisible_characters.py'):
            self.assertEqual([], gate.findings(path, (ROOT / path).read_bytes()))


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        git = shutil.which('git')
        if git is None:
            self.skipTest('git is not installed')
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.repository = gate.Repository(git, self.directory)
        self.git('init', '-q')

    def git(self, *args):
        return subprocess.run(
            [shutil.which('git'), '-C', self.directory,
             '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
             '-c', 'commit.gpgsign=false', '-c', 'core.autocrlf=false'] + list(args),
            check=True, stdout=subprocess.PIPE).stdout.decode('ascii').strip()

    def commit(self, message, files):
        for name, text in files.items():
            path = Path(self.directory) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode('utf-8'))
        message_path = Path(self.directory).parent / (Path(self.directory).name + '.msg')
        self.addCleanup(lambda: message_path.exists() and message_path.unlink())
        message_path.write_bytes(message.encode('utf-8'))
        self.git('add', '-A')
        self.git('commit', '-q', '--cleanup=verbatim', '-F', str(message_path))
        return self.git('rev-parse', 'HEAD')

    def test_new_commit_message_and_changed_file_are_checked(self):
        base = self.commit('Start', {
            'docs/releases/v1.0.0.md': '# v1.0.0\n',
            'tools/vendor/upstream.txt': BOM + 'upstream bytes\n',
            'src/a.py': 'x = 1\n',
        })
        self.assertEqual([], gate.check(self.repository, base, 'HEAD'))
        head = self.commit(BOM + 'Change things', {
            'src/a.py': 'x =' + ZERO_WIDTH_SPACE + ' 2\n',
            'tools/vendor/upstream.txt': BOM + 'new upstream bytes\n',
        })
        problems = gate.check(self.repository, base, head)
        self.assertEqual(2, len(problems), problems)
        self.assertIn('commit %s message:1:1: BYTE ORDER MARK' % head[:12], problems[0])
        self.assertTrue(problems[1].startswith('src/a.py:1:4: ZERO WIDTH SPACE'))

    def test_every_release_note_is_checked_even_when_unchanged(self):
        base = self.commit('Start', {
            'docs/releases/v1.0.0.md': '# v1.0.0 ' + RIGHT_TO_LEFT_OVERRIDE + '\n'})
        head = self.commit('Unrelated', {'src/a.py': 'x = 1\n'})
        self.assertEqual(
            ['docs/releases/v1.0.0.md:1:10: RIGHT-TO-LEFT OVERRIDE (U+202E)'],
            gate.check(self.repository, base, head))

    def test_missing_base_checks_only_the_head_commit(self):
        self.commit(BOM + 'Old history', {'src/a.py': 'x = 1\n'})
        head = self.commit('Clean head', {'src/b.py': 'y = 2\n'})
        self.assertEqual([], gate.check(self.repository, '0' * 40, head))
        self.assertEqual([], gate.check(self.repository, '', head))


if __name__ == '__main__':
    unittest.main()
