"""Shared semantics for Serenity binary operators.

Both the interpreter and the compile-time constant folder must agree on
operator behaviour, in particular how strings behave with `+` and with the
comparison operators. This module is the single source of truth for those
rules so the two execution modes cannot drift apart.
"""


class OperationError(Exception):
    pass


def _type_name(value):
    if value is True or value is False:
        return 'bool'
    if value is None:
        return 'null'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, int):
        return 'integer'
    if isinstance(value, tuple):
        return 'list'
    return type(value).__name__


def _numeric(op, left, right):
    try:
        return left + right if op == '+' else \
            left - right if op == '-' else \
            left * right if op == '*' else \
            left // right if op == '/' else \
            left % right if op == '%' else \
            left ** right
    except ZeroDivisionError:
        raise OperationError('division by zero') from None


def _relational(op, left, right):
    if isinstance(left, str) != isinstance(right, str):
        raise OperationError(
            f"cannot compare {_type_name(left)} with {_type_name(right)} using '{op}'")
    if isinstance(left, tuple) or isinstance(right, tuple):
        raise OperationError(f"cannot compare lists using '{op}'")
    try:
        return left < right if op == '<' else \
            left <= right if op == '<=' else \
            left > right if op == '>' else \
            left >= right
    except TypeError:
        raise OperationError(
            f"cannot compare {_type_name(left)} with {_type_name(right)} using '{op}'") from None


def apply(op, left, right):
    """Apply a binary operator to two operand values.

    `+` concatenates two strings and adds two numbers; mixing a string with a
    non-string is an error. Equality and inequality accept any operands (a
    comparison between different types is simply false/true). Ordering
    comparisons (`< <= > >=`) require both operands to be the same kind.
    """
    if op == '+':
        if isinstance(left, str) or isinstance(right, str):
            if isinstance(left, str) and isinstance(right, str):
                return left + right
            if left is None or right is None:
                raise OperationError('cannot concatenate a string with null')
            raise OperationError('cannot concatenate a string with a non-string')
        if isinstance(left, tuple) or isinstance(right, tuple):
            if not (isinstance(left, tuple) and isinstance(right, tuple)):
                raise OperationError('cannot concatenate a list with a non-list')
            return left + right
        return _numeric('+', left, right)
    if op in ('-', '*', '/', '%', '^'):
        if isinstance(left, tuple) or isinstance(right, tuple):
            raise OperationError(f"cannot use '{op}' on lists")
        return _numeric(op, left, right)
    if op == '==':
        return left == right
    if op == '!=':
        return left != right
    return _relational(op, left, right)