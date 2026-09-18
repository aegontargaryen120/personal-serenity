"""Shared semantics for Serenity's string built-in functions.

These pure functions define how the string library behaves. The interpreter
calls them directly at runtime and the compile-time constant folder uses them
to fold `substring(...)`, `toUpper(...)`, etc. into constant values, so the two
execution modes stay in agreement.

`length`, `contains` and `indexOf` are polymorphic (string or list) and live in
:mod:`src.list_builtins` alongside the list operations.
"""

from .binary_ops import OperationError


def _require_string(name, value):
    if not isinstance(value, str):
        raise OperationError(f"{name} expects a string argument, got {type(value).__name__}")


def _require_int(name, value):
    if not isinstance(value, int) or isinstance(value, bool):
        raise OperationError(f"{name} expects an integer argument, got {type(value).__name__}")


def length(value):
    _require_string('length', value)
    return len(value)


def char_at(value, index):
    _require_string('charAt', value)
    _require_int('charAt', index)
    if index < 0 or index >= len(value):
        raise OperationError(f'charAt index {index} out of bounds for string of length {len(value)}')
    return value[index]


def substring(value, start, end):
    _require_string('substring', value)
    _require_int('substring', start)
    _require_int('substring', end)
    if start < 0 or end > len(value) or start > end:
        raise OperationError(f'substring range [{start}, {end}) out of bounds for string of length {len(value)}')
    return value[start:end]


def to_upper(value):
    _require_string('toUpper', value)
    return value.upper()


def to_lower(value):
    _require_string('toLower', value)
    return value.lower()


def trim(value):
    _require_string('trim', value)
    return value.strip()


def contains(haystack, needle):
    _require_string('contains', haystack)
    _require_string('contains', needle)
    return needle in haystack


def index_of(haystack, needle):
    _require_string('indexOf', haystack)
    _require_string('indexOf', needle)
    return haystack.find(needle)


def to_int(value):
    _require_string('toInt', value)
    text = value.strip()
    if text == '':
        raise OperationError('toInt cannot convert an empty string')
    sign = 1
    body = text
    if body[0] in '+-':
        if body[0] == '-':
            sign = -1
        body = body[1:]
    if body == '' or not body.isdigit():
        raise OperationError(f"toInt cannot convert {value!r} to an integer")
    return sign * int(body)