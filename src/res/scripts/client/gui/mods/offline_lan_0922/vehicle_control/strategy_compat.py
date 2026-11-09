"""Python-2.7 portability for the sole shared strategic implementation.

Server JSON text is Unicode. Native client byte strings use UTF-8. These
aliases are imported only by shared strategy modules; native client laws keep
their Python-2.7 builtins, including the existing rounding behavior.
"""
from __future__ import print_function, division

import io
import math
import sys
import zipfile

try:
    _text_type = unicode
    _integer_types = (int, long)
except NameError:
    _text_type = str
    _integer_types = (int,)


def text(value):
    if isinstance(value, _text_type):
        return value
    if sys.version_info[0] < 3 and isinstance(value, str):
        return value.decode('utf8')
    return _text_type(value)


def round_half_even(value, ndigits=None):
    """CPython-3 float rounding from the exact binary value, also on 2.7."""
    from decimal import Decimal, ROUND_HALF_EVEN, localcontext
    integer = isinstance(value, _integer_types)
    if ndigits is not None and not isinstance(ndigits, _integer_types):
        raise TypeError('ndigits must be an integer')
    number = value if integer else float(value)
    if not integer and (math.isnan(number) or math.isinf(number)):
        if ndigits is not None:
            return number
        if math.isnan(number):
            raise ValueError('cannot convert float NaN to integer')
        raise OverflowError('cannot convert float infinity to integer')
    if ndigits is None:
        exact = Decimal(number) if integer else Decimal.from_float(number)
        return int(exact.to_integral_value(rounding=ROUND_HALF_EVEN))
    if integer and ndigits >= 0:
        return number
    if not integer and ndigits > 323:
        return number
    if not integer and ndigits < -308:
        return math.copysign(0.0, number)
    if integer and -ndigits > len(str(abs(number))) + 1:
        return 0
    with localcontext() as context:
        # Every finite double's exact decimal expansion fits this precision.
        # No intermediate float scaling is allowed: e.g. 2.675 at 2 places
        # must be 2.67, whereas an exact .5 tie must choose the even result.
        context.prec = max(1100, len(str(abs(number))) + abs(ndigits) + 8)
        exact = Decimal(number) if integer else Decimal.from_float(number)
        rounded = exact.quantize(Decimal(1).scaleb(-ndigits),
                                 rounding=ROUND_HALF_EVEN)
        if integer:
            return int(rounded)
        result = float(rounded)
        if math.isinf(result):
            raise OverflowError('rounded value too large to represent')
        return result


def round_py3(value, ndigits=None):
    if sys.version_info[0] >= 3:
        return round(value) if ndigits is None else round(value, ndigits)
    return round_half_even(value, ndigits)


def isfinite(value):
    return not math.isnan(value) and not math.isinf(value)


def open_text(path):
    return io.open(path, mode='r', encoding='utf8')


BadZipFile = getattr(zipfile, 'BadZipFile', None) or zipfile.BadZipfile
