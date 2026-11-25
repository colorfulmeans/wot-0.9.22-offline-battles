# -*- coding: utf-8 -*-
"""Format installed shell data in the reference client's tooltip layout."""
import math
import re

from gui.mods.offline_lan_0922.ui_i18n import tr


def _shot_field(shot, name, default=None):
    # #1513 GunShot inherits NoLegacyStuff in the client: get(), indexing
    # and every other dict-like operation deliberately raise AssertionError.
    # Its supported API is shell/speed attributes. Plain dictionaries are
    # retained for serialized descriptors and test fixtures only.
    if isinstance(shot, dict):
        return shot.get(name, default)
    return getattr(shot, name, default)


def _speed_line(body, value):
    """Reuse the stock parameter row's label/value font spans and separator."""
    label = tr('Shell velocity') + tr(' (m/s)')
    separator = re.search(r'<br\s*/?>|\n', body, re.I)
    separator = separator.group(0) if separator is not None else u'\n'
    for row in re.split(r'<br\s*/?>|\n', body, flags=re.I):
        # Exclude markup before looking for numbers: font colors contain
        # digits too. The first ordinary parameter is damage in stock #1513.
        parts = re.split(r'(<[^>]*>)', row)
        for index in range(0, len(parts), 2):
            number = re.search(u'\\d[\\d\\s,.\u00a0]*', parts[index])
            if number is None:
                continue
            before = parts[index][:number.start()]
            after = parts[index][number.end():]
            labels = [i for i in range(0, index + 1, 2)
                      if (before if i == index else parts[i]).strip()]
            if not labels:
                continue
            first = labels[0]
            old_label = before if first == index else parts[first]
            punctuation = re.search(u'([:\uff1a]\\s*|\\s+)$', old_label)
            ending = punctuation.group(0) if punctuation else u' '
            for label_index in labels:
                if label_index != index:
                    parts[label_index] = u''
            replacement_label = label + ending
            if first == index:
                parts[index] = replacement_label + value + after
            else:
                parts[first] = replacement_label
                parts[index] = before + value + after
            return separator + u''.join(parts)
    return separator + label + u': ' + value


_SHELL_TITLES = {
    'ARMOR_PIERCING': 'Armor-piercing shell',
    'ARMOR_PIERCING_CR': 'Armor-piercing composite rigid shell',
    'HOLLOW_CHARGE': 'High-explosive anti-tank shell',
    'HIGH_EXPLOSIVE': 'High-explosive shell',
}


def _plain_number(value, decimals=0):
    value = float(value)
    if math.isnan(value) or math.isinf(value) or value < 0.0:
        raise ValueError('shell parameter is not a finite non-negative value')
    if not decimals:
        return u'{0:,}'.format(int(round(value)))
    return (u'%.*f' % (decimals, value)).rstrip('0').rstrip('.')


def _reference_body(body, shot, shell):
    """Use the installed GunShot endpoints; retain stock extra rows (stun)."""
    kind = _shot_field(shell, 'kind')
    if kind not in _SHELL_TITLES:
        return None
    try:
        damage = _plain_number(_shot_field(shell, 'damage')[0])
        piercing = _shot_field(shot, 'piercingPower')
        near, far = _plain_number(piercing[0]), _plain_number(piercing[1])
        speed = _plain_number(_shot_field(shot, 'speed'))
        radius = None
        if kind == 'HIGH_EXPLOSIVE':
            radius = _shot_field(shell, 'explosionRadius')
            if radius is None:
                radius = _shot_field(_shot_field(shell, 'type'), 'explosionRadius')
            radius = _plain_number(radius, 2)
    except (TypeError, ValueError, IndexError, KeyError, OverflowError):
        return None
    separator = re.search(r'<br\s*/?>|\n', body, re.I)
    separator = separator.group(0) if separator is not None else u'\n'
    rows = re.split(r'<br\s*/?>|\n', body, flags=re.I)
    parameter_rows = [index for index, row in enumerate(rows)
                      if re.search(r'\d', re.sub(r'<[^>]*>', '', row))]
    # Native #1513's first two parameters are damage and penetration. Preserve
    # any following stock parameters, including HE stun duration.
    template = rows[parameter_rows[0]] if parameter_rows else u''
    fonts = re.findall(r'<font\b[^>]*>', template, re.I)
    label_font = fonts[0] if fonts else u''
    value_font = fonts[-1] if fonts else u''

    def row(label, value):
        if fonts:
            return (label_font + label + u': </font>' +
                    value_font + value + u'</font>')
        return label + u': ' + value

    affected = kind in ('ARMOR_PIERCING', 'ARMOR_PIERCING_CR')
    power = near + (u'-' + far if affected else u'')
    result = [
        row(tr('Average damage'), tr('%s points') % damage),
        row(tr('Average penetration'), (tr('%s mm') % power) + u'*'),
        row(tr('Shell velocity'), tr('%s m/s') % speed),
    ]
    if radius is not None:
        result.append(row(tr('Damage radius'), tr('%s m') % radius))
    if len(parameter_rows) >= 2:
        result.extend(rows[parameter_rows[1] + 1:])
    note = tr('*Affected by distance: 50–500 m' if affected else
              '*This shell type is unaffected by distance')
    result.extend((u'', value_font + note + u'</font>' if fonts else note))
    return separator.join(result), tr(_SHELL_TITLES[kind])


def append_speed(tooltip, shell, vehicle, number_format=None):
    gun = getattr(vehicle, 'gun', None)
    shell_cd = getattr(shell, 'compactDescr', None)
    speed = None
    selected = None
    for shot in getattr(gun, 'shots', ()):
        candidate = _shot_field(shot, 'shell')
        if (candidate is shell or (shell_cd is not None and
                getattr(candidate, 'compactDescr', None) == shell_cd)):
            speed = float(_shot_field(shot, 'speed', 0.0))
            selected = shot
            break
    if speed is None or speed <= 0 or math.isnan(speed) or math.isinf(speed):
        return tooltip
    was_bytes = isinstance(tooltip, bytes)
    text = tooltip.decode('utf-8') if was_bytes else tooltip
    value = (number_format(int(round(speed))) if callable(number_format)
             else u'%.0f' % speed)
    if isinstance(value, bytes):
        value = value.decode('utf-8')
    if '{BODY}' in text and '{/BODY}' in text:
        begin = text.index('{BODY}') + len('{BODY}')
        end = text.index('{/BODY}', begin)
        reference = _reference_body(text[begin:end], selected, shell)
        if reference is not None:
            body, title = reference
            text = text[:begin] + body + text[end:]
            if '{HEADER}' in text and '{/HEADER}' in text:
                start = text.index('{HEADER}') + len('{HEADER}')
                finish = text.index('{/HEADER}', start)
                text = text[:start] + title + text[finish:]
        else:
            text = text[:end] + _speed_line(text[begin:end], value) + text[end:]
    else:
        text += u'\n/{BODY}' + _speed_line(u'', value).lstrip('\n') + '{/BODY}'
    return text.encode('utf-8') if was_bytes else text
