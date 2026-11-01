"""Verify reviewed opt-in entries across Git checkout line endings."""
from pathlib import Path

ENTRIES = ('START_DIAGNOSTIC_TEST.bat',)
NORMAL_ENTRY = 'wot-0.9.22-offline-battles.exe'


def verify_archive(archive, source_dir=None):
    source_dir = Path(source_dir) if source_dir is not None else Path(__file__).resolve().parent
    allowed = set(ENTRIES + (NORMAL_ENTRY,))
    launchers = [name for name in archive.namelist() if '/' not in name and
                 name.lower().endswith(('.exe', '.bat', '.cmd', '.ps1'))]
    if set(launchers) != allowed or len(launchers) != len(allowed):
        raise ValueError('Release must contain only the normal and diagnostic launch entries: %s' % launchers)
    for name in ENTRIES:
        try:
            actual = archive.read(name)
        except KeyError:
            raise ValueError('required launch entry is missing: %s' % name)
        expected = (source_dir / name).read_bytes()
        # Git on Windows uses CRLF; LF and CRLF represent the same batch file.
        # Keep every other byte, including flags, whitespace and encoding.
        if actual.replace(b'\r\n', b'\n') != expected.replace(b'\r\n', b'\n'):
            raise ValueError('launch entry differs from reviewed source: %s' % name)
    return ENTRIES
