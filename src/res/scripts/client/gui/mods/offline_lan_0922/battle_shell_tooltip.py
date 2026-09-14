# -*- coding: utf-8 -*-
"""Append the hovered shell's installed-gun muzzle velocity to #1513 text."""
import math
import re


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
    label = u'\u70ae\u5f39\u901f\u5ea6 (\u7c73/\u79d2)'
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


def append_speed(tooltip, shell, vehicle, number_format=None):
    gun = getattr(vehicle, 'gun', None)
    shell_cd = getattr(shell, 'compactDescr', None)
    speed = None
    for shot in getattr(gun, 'shots', ()):
        candidate = _shot_field(shot, 'shell')
        if (candidate is shell or (shell_cd is not None and
                getattr(candidate, 'compactDescr', None) == shell_cd)):
            speed = float(_shot_field(shot, 'speed', 0.0))
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
        text = text[:end] + _speed_line(text[begin:end], value) + text[end:]
    else:
        text += u'\n/{BODY}' + _speed_line(u'', value).lstrip('\n') + '{/BODY}'
    return text.encode('utf-8') if was_bytes else text
