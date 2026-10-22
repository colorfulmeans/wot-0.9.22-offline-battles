"""Verify reviewed opt-in entries across Git checkout line endings."""
from pathlib import Path

ENTRIES = ('START_SPIKE_PROFILE.bat', 'START_ROOF_CRUSH_TEST.bat',
           'START_ROOF_SHOT_DROP_TEST.bat', 'START_DIAGNOSTIC_TEST.bat')


def verify_archive(archive, source_dir=None):
    source_dir = Path(source_dir) if source_dir is not None else Path(__file__).resolve().parent
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
