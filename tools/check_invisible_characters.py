"""Refuse invisible characters in new commits, changed text and release notes.

A UTF-8 byte order mark, zero-width characters and bidirectional controls
render as nothing yet change the bytes of a commit message, a source file or
published release notes. This check covers the commit messages in BASE..HEAD,
the text files changed in that range and every release note at HEAD. Vendored
third-party files keep their upstream bytes and are not checked.

Without a usable BASE (a manual run or a branch's first push) the range is
HEAD's own commit against its first parent.
"""
import argparse
import subprocess
import sys

# Written as code points so this file itself contains none of them.
INVISIBLE = {
    chr(0xFEFF): 'BYTE ORDER MARK',
    chr(0x200B): 'ZERO WIDTH SPACE',
    chr(0x200C): 'ZERO WIDTH NON-JOINER',
    chr(0x200D): 'ZERO WIDTH JOINER',
    chr(0x2060): 'WORD JOINER',
    chr(0x202A): 'LEFT-TO-RIGHT EMBEDDING',
    chr(0x202B): 'RIGHT-TO-LEFT EMBEDDING',
    chr(0x202C): 'POP DIRECTIONAL FORMATTING',
    chr(0x202D): 'LEFT-TO-RIGHT OVERRIDE',
    chr(0x202E): 'RIGHT-TO-LEFT OVERRIDE',
    chr(0x2066): 'LEFT-TO-RIGHT ISOLATE',
    chr(0x2067): 'RIGHT-TO-LEFT ISOLATE',
    chr(0x2068): 'FIRST STRONG ISOLATE',
    chr(0x2069): 'POP DIRECTIONAL ISOLATE',
}
EXCLUDED_PREFIXES = ('tools/vendor/',)
RELEASE_NOTES_PREFIX = 'docs/releases/'


def findings(label, data):
    """Return one message per invisible character in UTF-8 text bytes."""
    if b'\0' in data[:8192]:
        return []  # binary content
    text = data.decode('utf-8', 'replace')
    found = []
    for number, line in enumerate(text.split('\n'), 1):
        for column, character in enumerate(line, 1):
            name = INVISIBLE.get(character)
            if name is not None:
                found.append('%s:%d:%d: %s (U+%04X)' % (
                    label, number, column, name, ord(character)))
    return found


def checked_path(path):
    return not path.startswith(EXCLUDED_PREFIXES)


class Repository(object):
    def __init__(self, git='git', directory=None):
        self.command = [git] if directory is None else [git, '-C', directory]

    def run(self, *args):
        return subprocess.run(self.command + list(args), check=True,
                              stdout=subprocess.PIPE).stdout

    def resolve(self, revision):
        try:
            return self.run('rev-parse', '--verify', '--quiet',
                            revision + '^{commit}').decode('ascii').strip()
        except subprocess.CalledProcessError:
            return None

    def first_parent(self, head):
        return self.resolve(head + '^1')

    def commits(self, base, head):
        revisions = ('%s..%s' % (base, head),) if base else (head, '-1')
        output = self.run('log', '--format=%H%x00%B%x00', *revisions)
        fields = output.split(b'\0')
        return [(fields[index].strip().decode('ascii'), fields[index + 1])
                for index in range(0, len(fields) - 1, 2)]

    def changed_paths(self, base, head):
        if base:
            output = self.run('diff', '--name-only', '--diff-filter=ACMR',
                              '-z', base, head)
        else:
            output = self.run('diff-tree', '--root', '--no-commit-id', '-r',
                              '--name-only', '--diff-filter=ACMR', '-z', head)
        return [path.decode('utf-8') for path in output.split(b'\0') if path]

    def release_notes(self, head):
        output = self.run('ls-tree', '-r', '--name-only', '-z', head,
                          '--', RELEASE_NOTES_PREFIX)
        return [path.decode('utf-8') for path in output.split(b'\0') if path]

    def blob(self, head, path):
        return self.run('cat-file', 'blob', '%s:%s' % (head, path))


def check(repository, base, head):
    head_commit = repository.resolve(head)
    if head_commit is None:
        raise ValueError('HEAD revision is unavailable: %s' % head)
    base_commit = repository.resolve(base) if base and set(base) != {'0'} else None
    if base_commit is None:
        base_commit = repository.first_parent(head_commit)
    problems = []
    for sha, message in repository.commits(base_commit, head_commit):
        problems.extend(findings('commit %s message' % sha[:12], message))
    paths = set(repository.changed_paths(base_commit, head_commit))
    paths.update(repository.release_notes(head_commit))
    for path in sorted(paths):
        if checked_path(path):
            problems.extend(findings(path, repository.blob(head_commit, path)))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--base', default='')
    parser.add_argument('--head', default='HEAD')
    parser.add_argument('--git', default='git')
    args = parser.parse_args(argv)
    problems = check(Repository(args.git), args.base, args.head)
    for problem in problems:
        print(problem)
    if problems:
        print('Remove the invisible characters above; use UTF-8 without a BOM.')
        return 1
    print('No invisible characters in new commits, changed text or release notes.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
