"""Shared stock railway movement classification; no navigation strategy."""


def railway_vehicle_resource(filename):
    """Match carriage/locomotive families, not tracks or railway furniture."""
    parts = str(filename or '').replace('\\', '/').lower().split('/')
    return any(part in ('rw004_carriage', 'rw005_locomotive') for part in parts)
