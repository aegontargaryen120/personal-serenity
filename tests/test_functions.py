"""Tests for Serenity user-defined functions: argument passing, recursion,
control flow inside functions, boolean returns, runtime `let` values produced
by calls in `main`, and the error cases around calls and parameters.

Every behavioural test runs against the interpreter. A second class compiles
the same source with the ARM64 code generator, assembles it with `clang`, runs
the resulting binary, and asserts the compiled output matches the interpreter
exactly. Those compiled tests are skipped when `clang` is unavailable.
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import scanner, parser, evaluator, code_generator


class _Harness:
    """Run Serenity source in interpret or compile mode and capture stdout."""

    @staticmethod
    def interpret(source):
        tokens = scanner.Scanner(source).scan_tokens()
        program = parser.Parser(tokens).parse()
        buffer = io.StringIO()
        stdout = sys.stdout
        sys.stdout = buffer
        try:
            evaluator.Evaluator(program).interpret()
        finally:
            sys.stdout = stdout
        return buffer.getvalue()

    @staticmethod
    def compile(source):
        tokens = scanner.Scanner(source).scan_tokens()
        program = parser.Parser(tokens).parse()
        assembly = code_generator.CodeGen(program).generate()
        with tempfile.TemporaryDirectory() as directory:
            asm_path = os.path.join(directory, 'program.s')
            bin_path = os.path.join(directory, 'program')
            with open(asm_path, 'w') as handle:
                handle.write(assembly)
            linked = subprocess.run(['clang', asm_path, '-o', bin_path],
                                    capture_output=True, text=True)
            if linked.returncode != 0:
                raise AssertionError('clang failed to link:\n' + linked.stderr)
            ran = subprocess.run([bin_path], capture_output=True, text=True, timeout=10)
            if ran.returncode != 0:
                raise AssertionError(f'compiled program exited with {ran.returncode}\n{ran.stderr}')
            return ran.stdout

    @staticmethod
    def assert_interpret_raises(source, message):
        with unittest.TestCase().assertRaisesRegex(evaluator.RuntimeError, message):
            _Harness.interpret(source)

    @staticmethod
    def assert_compile_error(source, message):
        tokens = scanner.Scanner(source).scan_tokens()
        program = parser.Parser(tokens).parse()
        with unittest.TestCase().assertRaisesRegex(code_generator.CompileError, message):
            code_generator.CodeGen(program).generate()

    @staticmethod
    def both_agree(self_class, source, expected):
        interpreted = _Harness.interpret(source)
        self_class.assertEqual(interpreted, expected)
        if shutil.which('clang') is not None:
            self_class.assertEqual(_Harness.compile(source), expected)


def _program(*functions):
    return '\n'.join(functions) + '\n'


def _main(*statements):
    return ('func main() => (\n'
            + '\n'.join('    ' + s for s in statements)
            + '\n)\n')


class BasicFunctionTests(unittest.TestCase):
    def test_arguments_are_used_in_arithmetic(self):
        _Harness.both_agree(self, _program(
            'func add(x, y) => ( x + y * 2; )',
            _main('println(add(3, 4));'),
        ), '11\n')

    def test_multiple_arguments(self):
        _Harness.both_agree(self, _program(
            'func mulAdd(a, b, c) => ( a * b + c; )',
            _main('println(mulAdd(2, 3, 4));'),
        ), '10\n')

    def test_locals_declared_in_function(self):
        _Harness.both_agree(self, _program(
            'func f(x) => ( let y = x + 1; let z = y * 2; z; )',
            _main('println(f(10));'),
        ), '22\n')

    def test_zero_argument_function(self):
        _Harness.both_agree(self, _program(
            'func fortyTwo() => ( 42; )',
            _main('println(fortyTwo());'),
        ), '42\n')

    def test_main_constant_passed_as_argument(self):
        _Harness.both_agree(self, _program(
            'func sq(x) => ( x * x; )',
            _main('let base = 7;', 'println(sq(base));'),
        ), '49\n')

    def test_param_increment_then_return(self):
        _Harness.both_agree(self, _program(
            'func incTo(n) => ( n++; n; )',
            _main('println(incTo(3));'),
        ), '4\n')

    def test_nested_user_function_calls(self):
        _Harness.both_agree(self, _program(
            'func double(x) => ( x * 2; )',
            'func triple(x) => ( x * 3; )',
            _main('println(double(triple(4)));',
                  'println(double(triple(double(2))));'),
        ), '24\n24\n')

    def test_function_can_reference_later_function(self):
        _Harness.both_agree(self, _program(
            'func main() => ( println(sqTest(9)); )',
            'func sqTest(v) => ( v * v; )',
        ), '81\n')


class RecursionTests(unittest.TestCase):
    def test_fibonacci(self):
        _Harness.both_agree(self, _program(
            'func fib(n) => (',
            '    if (n <= 1) => { n; }',
            '    else => { fib(n - 1) + fib(n - 2); }',
            ')',
            _main('println(fib(10));'),
        ), '55\n')

    def test_direct_recursion_single_step(self):
        _Harness.both_agree(self, _program(
            'func countdown(n) => (',
            '    if (n == 0) => { 0; }',
            '    else => { countdown(n - 1) + 1; }',
            ')',
            _main('println(countdown(4));'),
        ), '4\n')


class ControlFlowInFunctionTests(unittest.TestCase):
    def test_for_loop_counter_in_function(self):
        """Regression: counters mutated inside `for` bodies must survive."""
        _Harness.both_agree(self, _program(
            'func countFor(n) => (',
            '    let i = 0;',
            '    for (let j = 0; j < n; j++) => { i++; }',
            '    i;',
            ')',
            _main('println(countFor(5));'),
        ), '5\n')

    def test_while_loop_in_function(self):
        _Harness.both_agree(self, _program(
            'func sumUp(n) => (',
            '    let total = 0;',
            '    let i = 0;',
            '    while (i < n) => { total++; i++; }',
            '    total;',
            ')',
            _main('println(sumUp(4));'),
        ), '4\n')

    def test_if_else_branching_in_function(self):
        _Harness.both_agree(self, _program(
            'func classify(n) => (',
            '    if (n > 10) => { let big = 100; big; }',
            '    else => { let small = 1; small; }',
            ')',
            _main('println(classify(20));', 'println(classify(5));'),
        ), '100\n1\n')

    def test_nested_if_returns_branch_value(self):
        _Harness.both_agree(self, _program(
            'func classify(n) => (',
            '    if (n > 0) => { if (n > 10) => { 100; } else => { 1; } }',
            '    else => { -1; }',
            ')',
            _main('println(classify(20));',
                  'println(classify(5));',
                  'println(classify(-7));'),
        ), '100\n1\n-1\n')


class BooleanFunctionTests(unittest.TestCase):
    def test_bool_function_prints_true_false(self):
        _Harness.both_agree(self, _program(
            'func isEven(n) => ( n % 2 == 0; )',
            _main('println(isEven(4));', 'println(isEven(5));'),
        ), 'true\nfalse\n')

    def test_comparison_using_function_results(self):
        _Harness.both_agree(self, _program(
            'func triple(x) => ( x * 3; )',
            _main('println(triple(7) > triple(6));',
                  'println(triple(2) == triple(2));'),
        ), 'true\ntrue\n')

    def test_logical_operators_with_function_calls(self):
        _Harness.both_agree(self, _program(
            'func gt(a, b) => ( a > b; )',
            _main('println(gt(3, 2) && gt(1, 0));',
                  'println(gt(1, 2) || gt(3, 2));'),
        ), 'true\ntrue\n')


class RuntimeValueTests(unittest.TestCase):
    def test_runtime_let_from_function_call(self):
        _Harness.both_agree(self, _program(
            'func incBy(x, y) => ( x + y; )',
            _main('let a = incBy(1, 2);',
                  'println(a);',
                  'let b = incBy(10, 20);',
                  'println(a + b);'),
        ), '3\n33\n')

    def test_call_result_nested_in_arguments(self):
        _Harness.both_agree(self, _program(
            'func sq(x) => ( x * x; )',
            _main('println(sq(sq(2)) + sq(3));'),
        ), '25\n')

    def test_conditional_expression_with_call(self):
        _Harness.both_agree(self, _program(
            'func get(n) => ( n; )',
            _main('let r = get(1) > 0 ? 10 : 20;', 'println(r);'),
        ), '10\n')

    def test_unary_negation_with_call(self):
        _Harness.both_agree(self, _program(
            'func val(x) => ( x; )',
            _main('println(-val(5));'),
        ), '-5\n')

    def test_print_without_newline_uses_function(self):
        _Harness.both_agree(self, _program(
            'func add(a, b) => ( a + b; )',
            _main('print(add(1, 2));', 'println(add(3, 4));'),
        ), '37\n')

    def test_runtime_bool_let_prints_true_false(self):
        """Runtime `let` bound to a bool-returning call must print true/false."""
        _Harness.both_agree(self, _program(
            'func isEven(n) => ( n % 2 == 0; )',
            _main('let b = isEven(4);',
                  'println(b);',
                  'let c = isEven(5);',
                  'println(c);'),
        ), 'true\nfalse\n')

    def test_runtime_let_from_bool_comparison(self):
        _Harness.both_agree(self, _program(
            'func both(a, b) => ( a < b; )',
            _main('let c = both(1, 2);',
                  'println(c);'),
        ), 'true\n')


class FunctionErrorTests(unittest.TestCase):
    def test_undefined_function(self):
        _Harness.assert_interpret_raises(
            _main('println(nope(1));'),
            "undefined function 'nope'")
        _Harness.assert_compile_error(
            _main('println(nope(1));'),
            "unsupported call 'nope' in compiled expression")

    def test_undefined_function_in_runtime_let(self):
        _Harness.assert_interpret_raises(
            _main('let x = nope(1);', 'println(x);'),
            "undefined function 'nope'")
        _Harness.assert_compile_error(
            _main('let x = nope(1);', 'println(x);'),
            "unsupported call 'nope' in compiled expression")

    def test_wrong_arity(self):
        source = _program('func add(a, b) => ( a + b; )',
                          _main('println(add(1));'))
        _Harness.assert_interpret_raises(source, 'add expects 2 arguments, got 1')
        _Harness.assert_compile_error(source, 'add expects 2 arguments, got 1')

    def test_too_many_arguments(self):
        source = _program('func f(a, b) => ( a + b; )',
                          _main('println(f(1, 2, 3));'))
        _Harness.assert_interpret_raises(source, 'f expects 2 arguments, got 3')
        _Harness.assert_compile_error(source, 'f expects 2 arguments, got 3')

    def test_undefined_variable_in_function_body(self):
        source = _program('func f(x) => ( missing; )',
                          _main('println(f(1));'))
        _Harness.assert_interpret_raises(source, "undefined variable 'missing'")
        _Harness.assert_compile_error(source, "undefined variable 'missing'")


class ReturnStatementTests(unittest.TestCase):
    def test_explicit_return_value(self):
        _Harness.both_agree(self, _program(
            'func add(x, y) => ( return x + y; )',
            _main('println(add(3, 4));'),
        ), '7\n')

    def test_early_return_from_conditionals(self):
        _Harness.both_agree(self, _program(
            'func classify(n) => (',
            '    if (n > 10) => { return 100; }',
            '    else => { return 1; }',
            ')',
            _main('println(classify(20));', 'println(classify(5));'),
        ), '100\n1\n')

    def test_return_stops_execution(self):
        _Harness.both_agree(self, _program(
            'func f() => ( return 42; println(99); 0; )',
            _main('println(f());'),
        ), '42\n')

    def test_return_from_while_loop(self):
        _Harness.both_agree(self, _program(
            'func find(n) => (',
            '    let i = 0;',
            '    while (i < n) => { if (i == 3) => { return 42; } i++; }',
            '    return -1;',
            ')',
            _main('println(find(10));', 'println(find(2));'),
        ), '42\n-1\n')

    def test_return_from_for_loop(self):
        _Harness.both_agree(self, _program(
            'func findIn(n) => (',
            '    for (let j = 0; j < n; j++) => { if (j == 2) => { return 7; } }',
            '    return -1;',
            ')',
            _main('println(findIn(5));', 'println(findIn(1));'),
        ), '7\n-1\n')

    def test_recursion_with_return(self):
        _Harness.both_agree(self, _program(
            'func countdown(n) => (',
            '    if (n == 0) => { return 0; }',
            '    return countdown(n - 1) + 1;',
            ')',
            _main('println(countdown(4));'),
        ), '4\n')

    def test_bool_return_prints_true_false(self):
        _Harness.both_agree(self, _program(
            'func isEven(n) => ( return n % 2 == 0; )',
            _main('println(isEven(4));', 'println(isEven(5));'),
        ), 'true\nfalse\n')

    def test_bool_return_in_branches(self):
        _Harness.both_agree(self, _program(
            'func isPositive(n) => (',
            '    if (n > 0) => { return true; }',
            '    else => { return false; }',
            ')',
            _main('println(isPositive(1));', 'println(isPositive(-1));'),
        ), 'true\nfalse\n')

    def test_return_of_user_function_call(self):
        _Harness.both_agree(self, _program(
            'func double(x) => ( return x * 2; )',
            'func quad(x) => ( return double(double(x)); )',
            _main('println(quad(5));'),
        ), '20\n')

    def test_return_null(self):
        self.assertEqual(_Harness.interpret(_program(
            'func nothing() => ( return null; )',
            _main('println(nothing());'),
        )), 'null\n')


if __name__ == '__main__':
    unittest.main()