"""Pinned #1513 style ownership: isRent decides, rentCount is a quantity."""


def is_rental(style):
    return style is not None and bool(getattr(style, 'isRent', False))


def rental_battles(style):
    # Raw StyleItem defaults to isRent=False, rentCount=1. The GUI Style
    # wrapper masks that quantity for permanent styles; garage/cache owners
    # read the raw descriptor and must apply the same classification.
    if not is_rental(style):
        return 0
    return max(0, int(getattr(style, 'rentCount', 0) or 0))


def report_style(stage, record, snapshot, styles, parser, identity, receipt=None):
    """Read-only evidence for one vehicle; logging must never affect a save."""
    try:
        import hashlib
        import json
        import sys
        from gui.mods.offline_lan_0922.account_rpc.garage import CUSTOMIZATION_ALL_SEASONS
        outfits = record.get('outfits', {})
        rows = []
        style_id = 0
        for season, raw in sorted(outfits.items()):
            descriptor = raw[0]
            encoded = descriptor.encode('utf-8') if isinstance(descriptor, type(u'')) else descriptor
            rows.append({'season': int(season), 'enabled': bool(raw[1]),
                         'bytes': len(encoded), 'sha1': hashlib.sha1(encoded).hexdigest()})
            if int(season) == CUSTOMIZATION_ALL_SEASONS and raw[1]:
                style_id = int(getattr(parser(descriptor), 'styleId', 0))
        style = styles.get(style_id)
        kind, item_id = identity(style.compactDescr) if style is not None else (0, 0)
        bindings = snapshot.get('customizationItems', {}).get(kind, {}).get(item_id, {})
        sys.stdout.write('[Offline LAN 0.9.22] STYLE STATE ' + json.dumps({
            'stage': stage, 'receipt': receipt, 'vehicle': record.get('id'),
            'vehicle_type': record.get('vehicleTypeCompactDescr'),
            'style': style_id, 'descriptor_known': style is not None,
            'is_rent': is_rental(style), 'raw_rent_count': getattr(style, 'rentCount', None),
            'stock': dict(bindings), 'outfits': rows}, separators=(',', ':')) + '\n')
    except Exception:
        # Unsupported/synthetic outfits must not change settlement admission.
        try:
            import sys
            sys.stdout.write('[Offline LAN 0.9.22] STYLE STATE unavailable stage=%s receipt=%s\n' % (stage, receipt))
        except Exception:
            pass
