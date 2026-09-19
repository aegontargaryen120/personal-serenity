from .binary_ops import apply as apply_operator, OperationError
from .ast_nodes import Identifier
from .string_builtins import (
    char_at, substring, to_upper, to_lower, trim, to_int,
)
from .list_builtins import (
    length, contains, index_of, at, append, prepend, head, tail, reverse,
    concat, join, to_string,
)
from .system_builtins import (
    SerenityFile, shell_exec, open_file, write_line, close_file,
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
    'charAt': (lambda value, index: char_at(value, index), 2),
    'substring': (lambda value, start, end: substring(value, start, end), 3),
    'toUpper': (lambda value: to_upper(value), 1),
    'toLower': (lambda value: to_lower(value), 1),
    'trim': (lambda value: trim(value), 1),
    'toInt': (lambda value: to_int(value), 1),
}

LIST_FUNCTIONS = {
    'length': (lambda value: length(value), 1),
    'contains': (lambda haystack, needle: contains(haystack, needle), 2),
    'indexOf': (lambda haystack, needle: index_of(haystack, needle), 2),
    'at': (lambda value, index: at(value, index), 2),
    'append': (lambda value, item: append(value, item), 2),
    'prepend': (lambda value, item: prepend(value, item), 2),
    'head': (lambda value: head(value), 1),
    'tail': (lambda value: tail(value), 1),
    'reverse': (lambda value: reverse(value), 1),
    'concat': (lambda left, right: concat(left, right), 2),
    'join': (lambda values, separator: join(values, separator), 2),
    'toString': (lambda value: to_string(value), 1),
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
        if name == 'shellex':
            self._require_arity(name, arguments, 1)
            command = self._evaluate(arguments[0], caller_environment)
            if not isinstance(command, str):
                raise RuntimeError(f"shellex expects a string command, got {self._value_kind(command)}")
            return shell_exec(command)
        if name == 'file':
            self._require_arity(name, arguments, 1)
            argument = arguments[0]
            path = self._evaluate(argument, caller_environment)
            if not isinstance(path, str):
                raise RuntimeError(f"file expects a string path, got {self._value_kind(path)}")
            handle = open_file(path)
            if isinstance(argument, Identifier) and argument.name in caller_environment:
                caller_environment[argument.name] = handle
            return handle
        function = self.functions.get(name)
        if function is not None:
            if len(function.params) != len(arguments):
                raise RuntimeError(f"{name} expects {len(function.params)} arguments, got {len(arguments)}")
            environment = dict(zip(function.params, (self._evaluate(arg, caller_environment) for arg in arguments)))
            try:
                return self._execute_statements(function.body, environment)
            except _ReturnSignal as signal:
                return signal.value
        builtin = STRING_FUNCTIONS.get(name)
        if builtin is None:
            builtin = LIST_FUNCTIONS.get(name)
        if builtin is not None:
            function, arity = builtin
            self._require_arity(name, arguments, arity)
            try:
                return function(*(self._evaluate(argument, caller_environment) for argument in arguments))
            except OperationError as error:
                raise RuntimeError(str(error)) from None
        raise RuntimeError(f"undefined function '{name}'")

    def _call_method(self, receiver, method, arguments, caller_environment):
        if receiver not in caller_environment:
            raise RuntimeError(f"undefined variable '{receiver}'")
        value = caller_environment[receiver]
        if not isinstance(value, SerenityFile):
            raise RuntimeError(f"'{receiver}.{method}' is only supported on file handles returned by 'file'")
        if method == 'write':
            self._require_arity(f'{receiver}.write', arguments, 1)
            text = self._evaluate(arguments[0], caller_environment)
            write_line(value, str(self._display(text)))
            return None
        if method == 'close':
            self._require_arity(f'{receiver}.close', arguments, 0)
            close_file(value)
            return None
        raise RuntimeError(f"undefined method '{receiver}.{method}'")

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
        return value is not False and value is not None and value != '' and value != 0 and value != ()

    @staticmethod
    def _display(value):
        if value is True:
            return 'true'
        if value is False:
            return 'false'
        if value is None:
            return 'null'
        if isinstance(value, tuple):
            return to_string(value)
        if isinstance(value, SerenityFile):
            return f'<file: {value.path}>'
        return value

    @staticmethod
    def _value_kind(value):
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
        if isinstance(value, SerenityFile):
            return 'file'
        return type(value).__name__

    def _evaluate(self, expression, environment=None):
        environment = {} if environment is None else environment
        from .ast_nodes import IntLiteral, StringLiteral, BoolLiteral, NullLiteral, Identifier, Binary, Unary, Conditional, Call, MethodCall, ListLiteral
        if isinstance(expression, IntLiteral) or isinstance(expression, StringLiteral) or isinstance(expression, BoolLiteral):
            return expression.value
        if isinstance(expression, NullLiteral):
            return None
        if isinstance(expression, ListLiteral):
            return tuple(self._evaluate(element, environment) for element in expression.elements)
        if isinstance(expression, Identifier):
            if expression.name not in environment:
                raise RuntimeError(f"undefined variable '{expression.name}'")
            return environment[expression.name]
        if isinstance(expression, Call):
            return self._call(expression.callee, expression.arguments, environment)
        if isinstance(expression, MethodCall):
            return self._call_method(expression.receiver, expression.method, expression.arguments, environment)
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
