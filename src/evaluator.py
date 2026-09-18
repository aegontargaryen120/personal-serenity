from .binary_ops import apply as apply_operator, OperationError
from .string_builtins import (
    length, char_at, substring, to_upper, to_lower, trim, contains, index_of, to_int,
)


class RuntimeError(Exception):
    pass


class _ReturnSignal(Exception):
    """Carry a `return <value>` out of a function body."""

    def __init__(self, value):
        super().__init__(value)
        self.value = value


MAX_LOOP_ITERATIONS = 1000000

STRING_FUNCTIONS = {
    'length': (lambda value: length(value), 1),
    'charAt': (lambda value, index: char_at(value, index), 2),
    'substring': (lambda value, start, end: substring(value, start, end), 3),
    'toUpper': (lambda value: to_upper(value), 1),
    'toLower': (lambda value: to_lower(value), 1),
    'trim': (lambda value: trim(value), 1),
    'contains': (lambda haystack, needle: contains(haystack, needle), 2),
    'indexOf': (lambda haystack, needle: index_of(haystack, needle), 2),
    'toInt': (lambda value: to_int(value), 1),
}


class Evaluator:
    def __init__(self, program):
        self.functions = {function.name: function for function in program.functions}

    def interpret(self):
        if 'main' not in self.functions:
            raise RuntimeError("no 'main' function declared")
        return self._call('main', [])

    def _call(self, name, arguments, caller_environment=None):
        caller_environment = {} if caller_environment is None else caller_environment
        if name == 'print':
            self._require_arity(name, arguments, 1)
            print(self._display(self._evaluate(arguments[0], caller_environment)), end='')
            return None
        if name == 'println':
            self._require_arity(name, arguments, 1)
            print(self._display(self._evaluate(arguments[0], caller_environment)))
            return None
        if name == 'eval':
            self._require_arity(name, arguments, 1)
            return self._evaluate(arguments[0], caller_environment)
        if name == 'exit':
            if len(arguments) == 0:
                raise SystemExit(0)
            self._require_arity(name, arguments, 1)
            code = self._evaluate(arguments[0], caller_environment)
            raise SystemExit(code)
        builtin = STRING_FUNCTIONS.get(name)
        if builtin is not None:
            function, arity = builtin
            self._require_arity(name, arguments, arity)
            try:
                return function(*(self._evaluate(argument, caller_environment) for argument in arguments))
            except OperationError as error:
                raise RuntimeError(str(error)) from None
        function = self.functions.get(name)
        if function is None:
            raise RuntimeError(f"undefined function '{name}'")
        if len(function.params) != len(arguments):
            raise RuntimeError(f"{name} expects {len(function.params)} arguments, got {len(arguments)}")
        environment = dict(zip(function.params, (self._evaluate(arg, caller_environment) for arg in arguments)))
        try:
            return self._execute_statements(function.body, environment)
        except _ReturnSignal as signal:
            return signal.value

    def _execute_statements(self, statements, environment):
        from .ast_nodes import LetStmt, AssignStmt, IfStmt, WhileStmt, ForStmt, IncrementStmt, ReturnStmt
        result = None
        for statement in statements:
            if isinstance(statement, LetStmt):
                if statement.name in environment:
                    raise RuntimeError(f"variable '{statement.name}' is already declared")
                environment[statement.name] = self._evaluate(statement.initializer, environment)
            elif isinstance(statement, AssignStmt):
                if statement.name not in environment:
                    raise RuntimeError(f"undefined variable '{statement.name}'")
                environment[statement.name] = self._evaluate(statement.value, environment)
            elif isinstance(statement, IncrementStmt):
                if statement.name not in environment:
                    raise RuntimeError(f"undefined variable '{statement.name}'")
                if not isinstance(environment[statement.name], int) or isinstance(environment[statement.name], bool):
                    raise RuntimeError(f"cannot increment non-integer variable '{statement.name}'")
                environment[statement.name] += 1
            elif isinstance(statement, IfStmt):
                branch = statement.then_branch if self._truthy(self._evaluate(statement.condition, environment)) else statement.else_branch
                if isinstance(branch, IfStmt):
                    result = self._execute_scoped([branch], environment)
                elif branch is not None:
                    result = self._execute_scoped(branch, environment)
            elif isinstance(statement, WhileStmt):
                iterations = 0
                while self._truthy(self._evaluate(statement.condition, environment)):
                    if iterations >= MAX_LOOP_ITERATIONS:
                        raise RuntimeError('loop exceeded maximum iteration count')
                    result = self._execute_scoped(statement.body, environment)
                    iterations += 1
            elif isinstance(statement, ForStmt):
                loop_environment = environment.copy()
                self._execute_statements([statement.initializer], loop_environment)
                iterations = 0
                while self._truthy(self._evaluate(statement.condition, loop_environment)):
                    if iterations >= MAX_LOOP_ITERATIONS:
                        raise RuntimeError('loop exceeded maximum iteration count')
                    result = self._execute_scoped(statement.body, loop_environment)
                    self._execute_statements([statement.increment], loop_environment)
                    iterations += 1
                for name in environment:
                    if name in loop_environment:
                        environment[name] = loop_environment[name]
            elif isinstance(statement, ReturnStmt):
                raise _ReturnSignal(self._evaluate(statement.expression, environment))
            else:
                result = self._evaluate(statement.expression, environment)
        return result

    def _execute_scoped(self, statements, environment):
        """Run a block without leaking declarations, while preserving mutations."""
        local_environment = environment.copy()
        result = self._execute_statements(statements, local_environment)
        for name in environment:
            if name in local_environment:
                environment[name] = local_environment[name]
        return result

    @staticmethod
    def _require_arity(name, args, count):
        if len(args) != count:
            raise RuntimeError(f'{name} expects {count} argument(s), got {len(args)}')

    @staticmethod
    def _truthy(value):
        return value is not False and value is not None and value != '' and value != 0

    @staticmethod
    def _display(value):
        if value is True:
            return 'true'
        if value is False:
            return 'false'
        if value is None:
            return 'null'
        return value

    def _evaluate(self, expression, environment=None):
        environment = {} if environment is None else environment
        from .ast_nodes import IntLiteral, StringLiteral, BoolLiteral, NullLiteral, Identifier, Binary, Unary, Conditional, Call
        if isinstance(expression, IntLiteral) or isinstance(expression, StringLiteral) or isinstance(expression, BoolLiteral):
            return expression.value
        if isinstance(expression, NullLiteral):
            return None
        if isinstance(expression, Identifier):
            if expression.name not in environment:
                raise RuntimeError(f"undefined variable '{expression.name}'")
            return environment[expression.name]
        if isinstance(expression, Call):
            return self._call(expression.callee, expression.arguments, environment)
        if isinstance(expression, Unary):
            value = self._evaluate(expression.operand, environment)
            if expression.operator == '-':
                return -value
            if expression.operator == '!':
                return not self._truthy(value)
        if isinstance(expression, Conditional):
            if self._truthy(self._evaluate(expression.condition, environment)):
                return self._evaluate(expression.if_true, environment)
            return self._evaluate(expression.if_false, environment)
        if isinstance(expression, Binary):
            left = self._evaluate(expression.left, environment)
            if expression.operator in ('&&', '||'):
                truth = self._truthy(left)
                if expression.operator == '&&':
                    return truth and self._truthy(self._evaluate(expression.right, environment))
                return truth or self._truthy(self._evaluate(expression.right, environment))
            right = self._evaluate(expression.right, environment)
            try:
                return apply_operator(expression.operator, left, right)
            except OperationError as error:
                raise RuntimeError(str(error)) from None
        raise RuntimeError(f'cannot evaluate {expression!r}')
