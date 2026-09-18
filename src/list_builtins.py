"""Shared semantics for Serenity's list type and its built-in functions.

Lists are immutable values backed internally by tuples. The interpreter calls
these functions directly at runtime and the compile-time constant folder uses
them to fold `length([...])`, `at(...)`, `toString(...)`, etc. into constant
values, so the two execution modes stay in agreement.

`length`, `contains` and `indexOf` are deliberately polymorphic: they accept
either a string or a list so the same names work on both collections.
"""

from .binary_ops import OperationError, _type_name


def _require_list(name, value):
    if not isinstance(value, tuple):
        raise OperationError(f"{name} expects a list argument, got {_type_name(value)}")


def _require_int(name, value):
    if not isinstance(value, int) or isinstance(value, bool):
        raise OperationError(f"{name} expects an integer argument, got {_type_name(value)}")


def _require_string_or_list(name, value):
    if not isinstance(value, (str, tuple)):
        raise OperationError(f"{name} expects a string argument or a list, got {_type_name(value)}")


def _require_string(name, value):
    if not isinstance(value, str):
        raise OperationError(f"{name} expects a string argument or a list, got {_type_name(value)}")


def length(value):
    _require_string_or_list('length', value)
    return len(value)


def contains(haystack, needle):
    _require_string_or_list('contains', haystack)
    if isinstance(haystack, str):
        _require_string('contains', needle)
        return needle in haystack
    return needle in haystack


def index_of(haystack, needle):
    _require_string_or_list('indexOf', haystack)
    if isinstance(haystack, str):
        _require_string('indexOf', needle)
        return haystack.find(needle)
    try:
        return haystack.index(needle)
    except ValueError:
        return -1


def at(value, index):
    _require_list('at', value)
    _require_int('at', index)
    if index < 0 or index >= len(value):
        raise OperationError(f'at index {index} out of bounds for list of length {len(value)}')
    return value[index]


def append(value, item):
    _require_list('append', value)
    return value + (item,)


def prepend(value, item):
    _require_list('prepend', value)
    return (item,) + value


def head(value):
    _require_list('head', value)
    if len(value) == 0:
        raise OperationError('head of an empty list')
    return value[0]


def tail(value):
    _require_list('tail', value)
    if len(value) == 0:
        raise OperationError('tail of an empty list')
    return value[1:]


def reverse(value):
    _require_string_or_list('reverse', value)
    return value[::-1]


def concat(left, right):
    _require_list('concat', left)
    _require_list('concat', right)
    return left + right


def join(values, separator):
    _require_list('join', values)
    if not isinstance(separator, str):
        raise OperationError(f'join expects a string separator, got {_type_name(separator)}')
    parts = []
    for item in values:
        if not isinstance(item, str):
            raise OperationError(f'join expects a list of strings, got {_type_name(item)}')
        parts.append(item)
    return separator.join(parts)


def to_string(value):
    """Canonical text form of any value, used by the `toString` builtin and by
    matrix printing of lists."""
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if value is None:
        return 'null'
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, tuple):
        return '[' + ', '.join(to_string(item) for item in value) + ']'
    raise OperationError(f'cannot convert {_type_name(value)} to a string')