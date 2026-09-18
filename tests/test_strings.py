"""Tests for Serenity string operations: concatenation, comparison, the string
library, and the type errors that keep strings away from arithmetic.

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


def _program(*statements):
    return 'func main() => (\n' + '\n'.join('    ' + s for s in statements) + '\n)\n'


class StringConcatenationTests(unittest.TestCase):
    def test_literal_concatenation(self):
        _Harness.both_agree(self, _program('println("a" + "b" + "c");'), 'abc\n')

    def test_variable_concatenation(self):
        _Harness.both_agree(self, _program(
            'let a = "hello";',
            'let b = "world";',
            'let c = a + " " + b;',
            'println(c);',
        ), 'hello world\n')

    def test_nested_runtime_concatenation(self):
        _Harness.both_agree(self, _program(
            'let x = "d" + "e";',
            'println(x + x);',
        ), 'dede\n')

    def test_empty_string_participates(self):
        _Harness.both_agree(self, _program(
            'let s = "x" + "";',
            'println(s == "x");',
            'println("" + "" == "");',
        ), 'true\ntrue\n')

    def test_concatenation_is_not_automatic(self):
        _Harness.assert_interpret_raises(
            _program('println("a" + 1);'),
            'cannot concatenate a string with a non-string')
        _Harness.assert_compile_error(
            _program('println("a" + 1);'),
            'cannot concatenate a string with a non-string')

    def test_null_cannot_be_concatenated(self):
        _Harness.assert_interpret_raises(
            _program('println("a" + null);'),
            'cannot concatenate a string with null')
        _Harness.assert_compile_error(
            _program('println("a" + null);'),
            'cannot concatenate a string with null')


class StringComparisonTests(unittest.TestCase):
    def test_equal_and_not_equal(self):
        _Harness.both_agree(self, _program(
            'let a = "ab";',
            'println(a == "ab");',
            'println(a != "ab");',
            'println(a == ("a" + "b"));',
        ), 'true\nfalse\ntrue\n')

    def test_ordering_operators(self):
        _Harness.both_agree(self, _program(
            'println("abc" < "abd");',
            'println("abc" <= "abc");',
            'println("Bb" > "Aa");',
            'println("a" >= "A");',
        ), 'true\ntrue\ntrue\ntrue\n')

    def test_order_is_lexicographic(self):
        _Harness.both_agree(self, _program(
            'println("ab" < "abc");',
            'println("10" < "9");',
        ), 'true\ntrue\n')

    def test_comparison_of_computed_strings_is_runtime(self):
        _Harness.both_agree(self, _program(
            'let a = "he" + "llo";',
            'println(a == "hello");',
            'println(a != "hell");',
            'println(a < "hello!");',
        ), 'true\ntrue\ntrue\n')

    def test_mixed_type_ordering_errors(self):
        _Harness.assert_interpret_raises(
            _program('println("a" < 1);'),
            'cannot compare string with integer')
        _Harness.assert_compile_error(
            _program('println("a" < 1);'),
            'cannot compare string with integer')

    def test_cross_type_equality_is_false(self):
        _Harness.both_agree(self, _program(
            'println("1" == 1);',
            'println(null == "");',
        ), 'false\nfalse\n')

    def test_string_conditions_fold(self):
        _Harness.both_agree(self, _program(
            'if (("ab" + "c") == "abc") => { println("equal"); } else => { println("diff"); }',
            'if ("a" < "b") => { println("lt"); }',
        ), 'equal\nlt\n')


class StringLibraryTests(unittest.TestCase):
    def test_length(self):
        _Harness.both_agree(self, _program(
            'println(length("hello"));',
            'println(length(""));',
        ), '5\n0\n')

    def test_charAt(self):
        _Harness.both_agree(self, _program(
            'println(charAt("abc", 0));',
            'println(charAt("abc", 2));',
        ), 'a\nc\n')

    def test_charAt_out_of_bounds(self):
        _Harness.assert_interpret_raises(
            _program('println(charAt("abc", 3));'),
            'out of bounds')
        _Harness.assert_compile_error(
            _program('println(charAt("abc", 3));'),
            'out of bounds')

    def test_substring(self):
        _Harness.both_agree(self, _program(
            'println(substring("hello", 1, 4));',
            'println(substring("hello", 0, 5));',
            'println(substring("hello", 2, 2));',
        ), 'ell\nhello\n\n')

    def test_substring_out_of_bounds(self):
        _Harness.assert_interpret_raises(
            _program('println(substring("abc", 0, 9));'),
            'out of bounds')
        _Harness.assert_compile_error(
            _program('println(substring("abc", 0, 9));'),
            'out of bounds')

    def test_case_conversions(self):
        _Harness.both_agree(self, _program(
            'println(toUpper("HeLlo World"));',
            'println(toLower("HeLlo World"));',
        ), 'HELLO WORLD\nhello world\n')

    def test_trim(self):
        _Harness.both_agree(self, _program(
            'println(trim("  spaced  "));',
            'println(trim("\\t\\n x \\r") == "x");',
        ), 'spaced\ntrue\n')

    def test_trim_whitespace_only(self):
        _Harness.both_agree(self, _program(
            'println(trim("   ") == "");',
        ), 'true\n')

    def test_contains_and_indexOf(self):
        _Harness.both_agree(self, _program(
            'println(contains("hello", "ell"));',
            'println(contains("hello", "xyz"));',
            'println(indexOf("hello", "o"));',
            'println(indexOf("hello", "z"));',
        ), 'true\nfalse\n4\n-1\n')

    def test_toInt(self):
        _Harness.both_agree(self, _program(
            'println(toInt("42"));',
            'println(toInt("-42"));',
            'println(toInt("  7  "));',
        ), '42\n-42\n7\n')

    def test_toInt_rejects_garbage(self):
        _Harness.assert_interpret_raises(
            _program('println(toInt("12abc"));'),
            'cannot convert')
        _Harness.assert_compile_error(
            _program('println(toInt("12abc"));'),
            'cannot convert')

    def test_wrong_argument_types(self):
        for call in ('trim(5)', 'charAt(1, 0)', 'substring(1, 0, 1)',
                     'toUpper(1)', 'length(1)', 'contains(1, "a")',
                     'indexOf("a", 1)', 'toInt(1)'):
            source = _program(f'println({call});')
            _Harness.assert_interpret_raises(source, 'expects a string argument')
            _Harness.assert_compile_error(source, 'expects a string argument')

    def test_wrong_arity(self):
        _Harness.assert_interpret_raises(
            _program('println(length("a", "b"));'),
            'length expects 1 argument')
        _Harness.assert_compile_error(
            _program('println(length("a", "b"));'),
            'length expects 1 argument')
        _Harness.assert_interpret_raises(
            _program('println(substring("a", 0));'),
            'substring expects 3 argument')
        _Harness.assert_compile_error(
            _program('println(substring("a", 0));'),
            'substring expects 3 argument')

    def test_builtins_compose(self):
        _Harness.both_agree(self, _program(
            'let word = toLower("MiXeD");',
            'println(length(word) + indexOf(word, "x"));',
            'println(toUpper(charAt(word, 2)) + trim("!"));',
            'println(toInt(substring("2024-01-01", 0, 4)));',
        ), '7\nX!\n2024\n')


def _functions(*functions):
    return '\n'.join(functions) + '\n'


class StringFunctionTests(unittest.TestCase):
    def test_function_returns_string_literal(self):
        _Harness.both_agree(self, _functions(
            'func answer() => ( return "yes"; )',
            _program('println(answer());'),
        ), 'yes\n')

    def test_println_inside_function(self):
        _Harness.both_agree(self, _functions(
            'func log() => ( println("inside function"); )',
            _program('log();'),
        ), 'inside function\n')

    def test_concat_string_parameter(self):
        _Harness.both_agree(self, _functions(
            'func greet(name) => ( return "Hello, " + name + "!"; )',
            _program('println(greet("Serenity"));'),
        ), 'Hello, Serenity!\n')

    def test_string_local_variable(self):
        _Harness.both_agree(self, _functions(
            'func shout(s) => ( let loud = toUpper(s); return loud + "!"; )',
            _program('println(shout("hi"));'),
        ), 'HI!\n')

    def test_length_inside_function(self):
        _Harness.both_agree(self, _functions(
            'func slen(s) => ( return length(s); )',
            _program('println(slen("abcd"));'),
        ), '4\n')

    def test_conditional_string_return(self):
        _Harness.both_agree(self, _functions(
            'func pick(n) => ( return n > 0 ? "positive" : "negative"; )',
            _program('println(pick(1));', 'println(pick(-1));'),
        ), 'positive\nnegative\n')

    def test_string_returned_from_loop(self):
        _Harness.both_agree(self, _functions(
            'func repeat(n) => (',
            '    let s = "";',
            '    let i = 0;',
            '    while (i < n) => { s = s + "a"; i++; }',
            '    return s;',
            ')',
            _program('println(repeat(3));'),
        ), 'aaa\n')

    def test_composed_string_builtins(self):
        _Harness.both_agree(self, _functions(
            'func transform(s) => ( return toUpper(substring(s, 0, 2)); )',
            _program('println(transform("hello"));'),
        ), 'HE\n')

    def test_equality_on_string_parameter(self):
        _Harness.both_agree(self, _functions(
            'func isHi(x) => ( return x == "hi"; )',
            _program('println(isHi("hi"));', 'println(isHi("ho"));'),
        ), 'true\nfalse\n')

    def test_trim_result_compared_in_function(self):
        _Harness.both_agree(self, _functions(
            'func isTrimmed(s) => ( return trim(s) == "x"; )',
            _program('println(isTrimmed("  x  "));'),
        ), 'true\n')

    def test_multiple_string_arguments(self):
        _Harness.both_agree(self, _functions(
            'func combine(a, b, c) => ( return a + "|" + b + "|" + c; )',
            _program('println(combine("x", "y", "z"));'),
        ), 'x|y|z\n')

    def test_string_passed_to_ambiguous_parameter(self):
        """`a + b` on two parameters is treated as numeric by the compiler, so
        passing strings is rejected there (a static-typing limitation), while
        the dynamically-typed interpreter concatenates them happily."""
        source = _functions(
            'func join(a, b) => ( return a + b; )',
            _program('println(join("x", "y"));'),
        )
        self.assertEqual(_Harness.interpret(source), 'xy\n')
        _Harness.assert_compile_error(source, 'cannot pass a string to non-string parameter')


class EscapedStringTests(unittest.TestCase):
    def test_escapes_in_strings(self):
        _Harness.both_agree(self, _program(
            'println("line\\nbreak\\ttab");',
            'println(length("a\\nb"));',
        ), 'line\nbreak\ttab\n3\n')

    def test_quote_and_backslash_escapes(self):
        _Harness.both_agree(self, _program(
            'println("say \\"hi\\" \\\\");',
        ), 'say "hi" \\\n')


if __name__ == '__main__':
    unittest.main()