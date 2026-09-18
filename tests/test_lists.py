"""Tests for Serenity's immutable list type: literals, the collection builtins,
list equality and concatenation, truthiness, and the list standard-library
module (stdlib/list.srn).

The list builtins and literals are first-class in the interpreter and are
folds to constants by the ARM64 code generator, so straightforward list
programs run identically in both modes. User-defined functions that build or
return lists only work at runtime and therefore run in the interpreter;
compiling them raises a clear CompileError.
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

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STDLIB_DIR = os.path.join(PROJECT_ROOT, 'stdlib')


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


def _program(*statements):
    return 'func main() => (\n' + '\n'.join('    ' + s for s in statements) + '\n)\n'


def _stdlib(*modules):
    parts = []
    for module in modules:
        with open(os.path.join(STDLIB_DIR, module + '.srn')) as handle:
            parts.append(handle.read())
    return '\n'.join(parts)


def _run(*modules, statements):
    source = _stdlib(*modules) + (
        'func main() => (\n'
        + '\n'.join('    ' + s for s in statements)
        + '\n)\n')
    return _Harness.interpret(source)


class ListLiteralTests(unittest.TestCase):
    def test_print_list_literal(self):
        _Harness.both_agree(self, _program('println([1, 2, 3]);'), '[1, 2, 3]\n')

    def test_empty_list(self):
        _Harness.both_agree(self, _program('println([]);'), '[]\n')

    def test_nested_lists(self):
        _Harness.both_agree(self, _program('println([[1, 2], [3], []]);'), '[[1, 2], [3], []]\n')

    def test_mixed_element_types(self):
        _Harness.both_agree(self, _program('println([1, "a", true, null]);'), '[1, a, true, null]\n')

    def test_list_of_expressions(self):
        _Harness.both_agree(self, _program(
            'println([1 + 2, "x" + "y", 3 > 1]);',
        ), '[3, xy, true]\n')

    def test_truthiness_empty_list_is_false(self):
        _Harness.both_agree(self, _program(
            'if ([]) => { println("truthy"); } else => { println("falsy"); }',
            'if ([0]) => { println("truthy"); } else => { println("falsy"); }',
        ), 'falsy\ntruthy\n')


class ListBuiltinTests(unittest.TestCase):
    def test_length(self):
        _Harness.both_agree(self, _program(
            'println(length([]));',
            'println(length([7, 8, 9]));',
            'println(length("abc"));',
        ), '0\n3\n3\n')

    def test_at(self):
        _Harness.both_agree(self, _program(
            'println(at([10, 20, 30], 0));',
            'println(at([10, 20, 30], 2));',
            'println(at(["a", "b"], 1));',
        ), '10\n30\nb\n')

    def test_head_and_tail(self):
        _Harness.both_agree(self, _program(
            'println(head([5, 6, 7]));',
            'println(tail([5, 6, 7]));',
        ), '5\n[6, 7]\n')

    def test_append_and_prepend(self):
        _Harness.both_agree(self, _program(
            'println(append([1, 2], 3));',
            'println(prepend([2, 3], 1));',
            'println(append([], 1));',
        ), '[1, 2, 3]\n[1, 2, 3]\n[1]\n')

    def test_reverse_string_and_list(self):
        _Harness.both_agree(self, _program(
            'println(reverse([1, 2, 3]));',
            'println(reverse([]));',
            'println(reverse("hello"));',
        ), '[3, 2, 1]\n[]\nolleh\n')

    def test_concat_and_plus(self):
        _Harness.both_agree(self, _program(
            'println(concat([1], [2, 3]));',
            'println([1] + [2, 3]);',
            'println([] + [1]);',
        ), '[1, 2, 3]\n[1, 2, 3]\n[1]\n')

    def test_contains_and_index_of(self):
        _Harness.both_agree(self, _program(
            'println(contains([1, 2, 3], 2));',
            'println(contains([1, 2, 3], 9));',
            'println(indexOf([1, 2, 3], 3));',
            'println(indexOf([1, 2, 3], 9));',
            'println(contains("hello", "ell"));',
            'println(indexOf("hello", "o"));',
        ), 'true\nfalse\n2\n-1\ntrue\n4\n')

    def test_join(self):
        _Harness.both_agree(self, _program(
            'println(join(["a", "b", "c"], "-"));',
            'println(join([], ","));',
            'println(join(["x"], ""));',
        ), 'a-b-c\n\nx\n')

    def test_to_string(self):
        _Harness.both_agree(self, _program(
            'println(toString(42));',
            'println(toString(true));',
            'println(toString(null));',
            'println(toString("abc"));',
            'println(toString([1, 2]));',
            'println(toString("n" + toString(7)));',
        ), '42\ntrue\nnull\nabc\n[1, 2]\nn7\n')

    def test_equality(self):
        _Harness.both_agree(self, _program(
            'println([1, 2] == [1, 2]);',
            'println([1, 2] == [1, 3]);',
            'println([1, 2] != [3]);',
            'println([] == []);',
            'println([1] == 1);',
        ), 'true\nfalse\ntrue\ntrue\nfalse\n')


class ListVariableTests(unittest.TestCase):
    def test_list_bound_to_variable(self):
        _Harness.both_agree(self, _program(
            'let items = [1, 2, 3];',
            'println(length(items));',
            'println(at(items, 0));',
            'println(items);',
        ), '3\n1\n[1, 2, 3]\n')

    def test_list_built_between_variables(self):
        _Harness.both_agree(self, _program(
            'let base = [1];',
            'let grown = base + [2] + [3];',
            'println(grown);',
            'println(length(grown));',
        ), '[1, 2, 3]\n3\n')

    def test_loop_over_compile_time_list(self):
        _Harness.both_agree(self, _program(
            'let items = [10, 20, 30];',
            'let i = 0;',
            'let sum = 0;',
            'while (i < length(items)) => { sum = sum + at(items, i); i++; }',
            'println(sum);',
        ), '60\n')

    def test_strings_in_list_variable(self):
        _Harness.both_agree(self, _program(
            'let words = ["a", "b", "c"];',
            'println(join(words, ""));',
            'println(reverse(words));',
        ), 'abc\n[c, b, a]\n')


class ListErrorTests(unittest.TestCase):
    def _expect_both(self, statement, message):
        source = _program(f'println({statement});')
        _Harness.assert_interpret_raises(source, message)
        _Harness.assert_compile_error(source, message)

    def test_at_out_of_bounds(self):
        self._expect_both('at([1, 2], 5)', 'out of bounds')

    def test_at_negative_index(self):
        self._expect_both('at([1, 2], -1)', 'out of bounds')

    def test_head_empty_list(self):
        self._expect_both('head([])', 'head of an empty list')

    def test_tail_empty_list(self):
        self._expect_both('tail([])', 'tail of an empty list')

    def test_list_ops_require_lists(self):
        for statement in ('append(5, 1)', 'prepend("a", 1)', 'head(1)',
                          'tail("abc")', 'at(1, 0)', 'concat(1, [2])'):
            self._expect_both(statement, 'expects a list argument')

    def test_cannot_order_lists(self):
        self._expect_both('[1] < [2]', 'cannot compare lists')

    def test_cannot_arithmetic_on_lists(self):
        self._expect_both('[1] - 2', "cannot use '-' on lists")
        self._expect_both('[1] * 2', r"cannot use '\*' on lists")

    def test_cannot_concatenate_list_with_non_list(self):
        self._expect_both('[1] + 2', 'cannot concatenate a list with a non-list')
        self._expect_both('2 + [1]', 'cannot concatenate a list with a non-list')

    def test_cannot_concatenate_string_with_list(self):
        self._expect_both('"a" + [1]', 'cannot concatenate a string with a non-string')
        self._expect_both('[1] + "a"', 'cannot concatenate a string with a non-string')

    def test_join_requires_string_elements(self):
        self._expect_both('join([1, 2], "-")', 'join expects a list of strings')

    def test_join_requires_string_separator(self):
        self._expect_both('join(["a"], 1)', 'join expects a string separator')

    def test_list_ops_wrong_arity(self):
        _Harness.assert_interpret_raises(_program('println(at([1], 0, 1));'), 'at expects 2 argument')
        _Harness.assert_compile_error(_program('println(at([1], 0, 1));'), 'at expects 2 argument')


class RuntimeListTests(unittest.TestCase):
    """Lists produced or consumed by user functions run in the interpreter only;
    the ARM64 backend reports a clear limitation instead of compiling them."""

    def test_function_returns_list_literal(self):
        source = 'func build() => ( return [1, 2, 3]; )\n' + _program('println(build());')
        self.assertEqual(_Harness.interpret(source), '[1, 2, 3]\n')
        _Harness.assert_compile_error(source, 'lists are only supported at compile time')

    def test_list_built_by_function_call(self):
        source = 'func f() => ( return [1]; )\n' + _program(
            'let a = f();',
            'let b = append(a, 2);',
            'println(b);')
        self.assertEqual(_Harness.interpret(source), '[1, 2]\n')
        _Harness.assert_compile_error(source, 'not yet supported at runtime')

    def test_list_passed_to_function(self):
        source = 'func total(xs) => ( return sumList(xs); )\n' + _stdlib('list') + _program(
            'println(total([1, 2, 3]));')
        self.assertEqual(_Harness.interpret(source), '6\n')

    def test_compile_rejects_list_argument(self):
        source = 'func sq(x) => ( return x * x; )\n' + _program('println(sq([1]));')
        _Harness.assert_compile_error(source, 'cannot pass a list to compiled function')


class ListStdlibTests(unittest.TestCase):
    def test_range(self):
        self.assertEqual(_run('list', statements=[
            'println(range(1, 6));',
            'println(range(3, 3));',
            'println(range(5, 2));',
            'println(range(0, 0));',
        ]), '[1, 2, 3, 4, 5]\n[]\n[]\n[]\n')

    def test_take_and_drop(self):
        self.assertEqual(_run('list', statements=[
            'println(take([1, 2, 3, 4], 2));',
            'println(take([1, 2], 5));',
            'println(take([1, 2], 0));',
            'println(drop([1, 2, 3, 4], 2));',
            'println(drop([1, 2], 5));',
            'println(drop([], 1));',
        ]), '[1, 2]\n[1, 2]\n[]\n[3, 4]\n[]\n[]\n')

    def test_sum_and_product(self):
        self.assertEqual(_run('list', statements=[
            'println(sumList([1, 2, 3, 4]));',
            'println(sumList([]));',
            'println(productList([2, 3, 4]));',
            'println(productList([]));',
        ]), '10\n0\n24\n1\n')

    def test_min_and_max(self):
        self.assertEqual(_run('list', statements=[
            'println(minList([4, 2, 9, 1]));',
            'println(maxList([4, 2, 9, 1]));',
            'println(minList([5]));',
            'println(maxList([5]));',
            'println(minList([]));',
        ]), '1\n9\n5\n5\n0\n')

    def test_count_item(self):
        self.assertEqual(_run('list', statements=[
            'println(countItem([1, 2, 1, 3, 1], 1));',
            'println(countItem([1, 2], 9));',
            'println(countItem(["a", "b", "a"], "a"));',
            'println(countItem([], 0));',
        ]), '3\n0\n2\n0\n')

    def test_remove_item(self):
        self.assertEqual(_run('list', statements=[
            'println(removeItem([1, 2, 1, 3], 1));',
            'println(removeItem([1, 2], 9));',
            'println(removeAll([1, 2, 1, 3, 1], 1));',
            'println(removeAll([], 1));',
        ]), '[2, 1, 3]\n[1, 2]\n[2, 3]\n[]\n')

    def test_zip_lists(self):
        self.assertEqual(_run('list', statements=[
            'println(zipLists([1, 2, 3], ["a", "b", "c"]));',
            'println(zipLists([1, 2], [1]));',
            'println(zipLists([], [1, 2]));',
        ]), '[[1, a], [2, b], [3, c]]\n[[1, 1]]\n[]\n')

    def test_flatten(self):
        self.assertEqual(_run('list', statements=[
            'println(flatten([[1, 2], [3], [4, 5]]));',
            'println(flatten([[[]], []]));',
            'println(flatten([]));',
        ]), '[1, 2, 3, 4, 5]\n[[]]\n[]\n')

    def test_filter_not_null(self):
        self.assertEqual(_run('list', statements=[
            'println(filterNotNull([1, null, 2, null, 3]));',
            'println(filterNotNull([null]));',
            'println(filterNotNull([]));',
        ]), '[1, 2, 3]\n[]\n[]\n')


if __name__ == '__main__':
    unittest.main()