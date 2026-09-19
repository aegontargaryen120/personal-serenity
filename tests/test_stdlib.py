"""Tests for the Serenity standard-library modules (math, string, util).

The standard library is written as ordinary Serenity functions and exercised
through the interpreter, the same path a program takes via `serenity prog`.
"""
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import scanner, parser, evaluator

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STDLIB_DIR = os.path.join(PROJECT_ROOT, 'stdlib')


def _stdlib(*modules):
    """Inline the sources of the named stdlib modules, as %import would."""
    parts = []
    for module in modules:
        with open(os.path.join(STDLIB_DIR, module + '.srn')) as handle:
            parts.append(handle.read())
    return '\n'.join(parts)


class _Harness:
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
    def run(*modules, statements):
        source = _stdlib(*modules) + (
            'func main() => (\n'
            + '\n'.join('    ' + s for s in statements)
            + '\n)\n')
        return _Harness.interpret(source)


class MathStdlibTests(unittest.TestCase):
    def test_basic_arithmetic_helpers(self):
        self.assertEqual(_Harness.run('math', statements=[
            'println(mult(3, 4));',
            'println(div(7, 2));',
            'println(abs(-7));',
            'println(sqr(6));',
            'println(cube(3));',
        ]), '12\n3\n7\n36\n27\n')

    def test_division_by_zero_reports_and_returns_zero(self):
        self.assertEqual(_Harness.run('math', statements=[
            'println(div(1, 0));',
        ]), 'ERROR: Division by zero is not allowed!\n0\n')

    def test_min_and_max_families(self):
        self.assertEqual(_Harness.run('math', statements=[
            'println(min(3, -4));',
            'println(max(3, -4));',
            'println(min3(9, 2, 5));',
            'println(max3(9, 2, 5));',
            'println(clamp(15, 0, 10));',
            'println(clamp(-2, 0, 10));',
            'println(clamp(5, 0, 10));',
        ]), '-4\n3\n2\n9\n10\n0\n5\n')

    def test_sign(self):
        self.assertEqual(_Harness.run('math', statements=[
            'println(sign(-3));',
            'println(sign(0));',
            'println(sign(9));',
        ]), '-1\n0\n1\n')

    def test_powers_and_modulo(self):
        self.assertEqual(_Harness.run('math', statements=[
            'println(pow(2, 5));',
            'println(sqr(12));',
            'println(mod(17, 5));',
        ]), '32\n144\n2\n')

    def test_pow_negative_exponent_reports_error(self):
        self.assertEqual(_Harness.run('math', statements=[
            'println(pow(2, -1));',
        ]), 'ERROR: pow does not support negative exponents\n0\n')

    def test_mod_by_zero_reports_error(self):
        self.assertEqual(_Harness.run('math', statements=[
            'println(mod(5, 0));',
        ]), 'ERROR: mod by zero\n0\n')

    def test_even_and_odd(self):
        self.assertEqual(_Harness.run('math', statements=[
            'println(even(4));',
            'println(even(5));',
            'println(odd(4));',
            'println(odd(5));',
        ]), 'true\nfalse\nfalse\ntrue\n')

    def test_gcd_and_lcm(self):
        self.assertEqual(_Harness.run('math', statements=[
            'println(gcd(48, 36));',
            'println(gcd(17, 5));',
            'println(gcd(0, 7));',
            'println(lcm(4, 6));',
            'println(lcm(0, 6));',
        ]), '12\n1\n7\n12\n0\n')

    def test_factorial(self):
        self.assertEqual(_Harness.run('math', statements=[
            'println(fact(0));',
            'println(fact(1));',
            'println(fact(5));',
        ]), '1\n1\n120\n')

    def test_factorial_of_negative_reports_error(self):
        self.assertEqual(_Harness.run('math', statements=[
            'println(fact(-3));',
        ]), 'ERROR: factorial of a negative number is undefined\n0\n')

    def test_prime_detection(self):
        self.assertEqual(_Harness.run('math', statements=[
            'println(isPrime(1));',
            'println(isPrime(2));',
            'println(isPrime(3));',
            'println(isPrime(4));',
            'println(isPrime(17));',
            'println(isPrime(49));',
            'println(isPrime(97));',
        ]), 'false\ntrue\ntrue\nfalse\ntrue\nfalse\ntrue\n')

    def test_range_and_divisibility(self):
        self.assertEqual(_Harness.run('math', statements=[
            'println(isBetween(5, 1, 10));',
            'println(isBetween(0, 1, 10));',
            'println(divisibleBy(12, 3));',
            'println(divisibleBy(12, 5));',
            'println(divisibleBy(4, 0));',
        ]), 'true\nfalse\ntrue\nfalse\nfalse\n')

    def test_fibonacci(self):
        self.assertEqual(_Harness.run('math', statements=[
            'println(fib(0));',
            'println(fib(1));',
            'println(fib(2));',
            'println(fib(10));',
            'println(fib(15));',
        ]), '0\n1\n1\n55\n610\n')

    def test_digit_sum_and_triangle(self):
        self.assertEqual(_Harness.run('math', statements=[
            'println(digitSum(0));',
            'println(digitSum(1234));',
            'println(digitSum(-123));',
            'println(triangle(0));',
            'println(triangle(5));',
            'println(triangle(-2));',
        ]), '0\n10\n6\n0\n15\n0\n')

    def test_negative_inputs_to_abs_based_helpers(self):
        self.assertEqual(_Harness.run('math', statements=[
            'println(gcd(-48, 36));',
            'println(lcm(-4, 6));',
            'println(digitSum(-1234));',
        ]), '12\n12\n10\n')


class StringStdlibTests(unittest.TestCase):
    def test_empty_and_length(self):
        self.assertEqual(_Harness.run('string', statements=[
            'println(isEmpty(""));',
            'println(isEmpty("x"));',
        ]), 'true\nfalse\n')

    def test_reverse(self):
        self.assertEqual(_Harness.run('string', statements=[
            'println(reverse("hello"));',
            'println(reverse(""));',
            'println(reverse("a"));',
        ]), 'olleh\n\na\n')

    def test_prefix_and_suffix(self):
        self.assertEqual(_Harness.run('string', statements=[
            'println(startsWith("hello", "he"));',
            'println(startsWith("hello", "lo"));',
            'println(startsWith("hi", "hello"));',
            'println(endsWith("hello", "lo"));',
            'println(endsWith("hello", "he"));',
            'println(endsWith("hi", "hello"));',
        ]), 'true\nfalse\nfalse\ntrue\nfalse\nfalse\n')

    def test_repeat(self):
        self.assertEqual(_Harness.run('string', statements=[
            'println(repeat("ab", 3));',
            'println(repeat("ab", 0));',
            'println(repeat("ab", -2));',
        ]), 'ababab\n\n\n')

    def test_capitalize_and_title_case(self):
        self.assertEqual(_Harness.run('string', statements=[
            'println(capitalize("hello"));',
            'println(capitalize(""));',
            'println(titleCase("the quick brown fox"));',
            'println(titleCase("already Mixed"));',
        ]), 'Hello\n\nThe Quick Brown Fox\nAlready Mixed\n')

    def test_replace(self):
        self.assertEqual(_Harness.run('string', statements=[
            'println(replace("banana", "na", "X"));',
            'println(replace("hello", "l", ""));',
            'println(replace("abc", "z", "q"));',
            'println(replace("abc", "", "-"));',
        ]), 'baXX\nheo\nabc\nabc\n')

    def test_count_occurrences(self):
        self.assertEqual(_Harness.run('string', statements=[
            'println(countOccurrences("banana", "an"));',
            'println(countOccurrences("aaaa", "aa"));',
            'println(countOccurrences("hello", "z"));',
            'println(countOccurrences("abc", ""));',
        ]), '2\n2\n0\n4\n')

    def test_left_and_right_trim(self):
        self.assertEqual(_Harness.run('string', statements=[
            'println(ltrim("  spaced"));',
            'println(rtrim("spaced  "));',
            'println(ltrim("no-space"));',
        ]), 'spaced\nspaced\nno-space\n')

    def test_padding_and_truncation(self):
        self.assertEqual(_Harness.run('string', statements=[
            'println(padLeft("7", 4, "0"));',
            'println(padRight("ab", 5, "-"));',
            'println(padLeft("long", 3, "0"));',
            'println(truncate("abcdef", 3));',
            'println(truncate("abc", 9));',
        ]), '0007\nab---\nlong\nabc\nabc\n')

    def test_word_count(self):
        self.assertEqual(_Harness.run('string', statements=[
            'println(wordCount(""));',
            'println(wordCount("   "));',
            'println(wordCount("one"));',
            'println(wordCount("one two"));',
            'println(wordCount(" one two  three "));',
        ]), '0\n0\n1\n2\n3\n')


class UtilStdlibTests(unittest.TestCase):
    def test_logic_helpers(self):
        self.assertEqual(_Harness.run('util', statements=[
            'println(identity(42));',
            'println(not(0));',
            'println(not(1));',
            'println(bool(0));',
            'println(bool(5));',
            'println(bool(""));',
        ]), '42\ntrue\nfalse\nfalse\ntrue\nfalse\n')

    def test_null_and_type_checks(self):
        self.assertEqual(_Harness.run('util', statements=[
            'println(isNull(null));',
            'println(isNull(0));',
            'println(notNull(null));',
            'println(notNull(""));',
            'println(isZero(0));',
            'println(isZero(1));',
            'println(nonZero(0));',
            'println(nonZero(7));',
            'println(isEmptyText(""));',
            'println(isEmptyText(" "));',
        ]), 'true\nfalse\nfalse\ntrue\ntrue\nfalse\nfalse\ntrue\ntrue\nfalse\n')

    def test_first_and_second_of(self):
        self.assertEqual(_Harness.run('util', statements=[
            'println(firstOf(null, "a"));',
            'println(firstOf("x", null));',
            'println(secondOf(null, "a"));',
            'println(secondOf("x", null));',
            'println(secondOf("x", "y"));',
        ]), 'a\nx\na\nx\ny\n')

    def test_equality_toggles_and_ranges(self):
        self.assertEqual(_Harness.run('util', statements=[
            'println(isEqual("a", "a"));',
            'println(isEqual(1, 2));',
            'println(isNotEqual(1, 2));',
            'println(toggle(0));',
            'println(toggle(1));',
            'println(countRange(3, 7));',
            'println(countRange(7, 3));',
        ]), 'true\nfalse\ntrue\n1\n0\n5\n0\n')


class StdlibCombinationTests(unittest.TestCase):
    def test_all_modules_import_together(self):
        self.assertEqual(_Harness.run('math', 'string', 'util', statements=[
            'let s = reverse("01");',
            'let s2 = repeat(s, 2);',
            'println(s2);',
            'println(padLeft(s2, 8, "0"));',
            'println(toInt(s2));',
            'println(isEqual(s2, "1010"));',
            'println(gcd(length(s2), 2));',
            'println(firstOf(null, toUpper(substring(s2, 0, 2))));',
        ]), '1010\n00001010\n1010\ntrue\n2\n10\n')


class SystemBuiltinTests(unittest.TestCase):
    """`shellex` and the `file` metaprogramming builtins are host-backed: they
    are available to any program (no %import required), like print and eval."""

    def test_shellex_runs_and_returns_exit_code(self):
        self.assertEqual(_Harness.run(statements=[
            'let code = shellex("echo hi");',
            'println(code);',
        ]), 'hi\n0\n')

    def test_shellex_reports_failing_exit_code(self):
        self.assertEqual(_Harness.run(statements=[
            'let code = shellex("exit 3");',
            'println(code);',
        ]), '3\n')

    def test_shellex_requires_a_string(self):
        with self.assertRaisesRegex(evaluator.RuntimeError, 'shellex expects a string command'):
            _Harness.run(statements=[
                'shellex(42);',
            ])

    def test_file_write_close_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'notes.txt')
            self.assertEqual(_Harness.run(statements=[
                f'let f = "{path}";',
                'file(f);',
                'f.write("hello world");',
                'f.write(42);',
                'f.close();',
            ]), '')
            with open(path) as handle:
                self.assertEqual(handle.read(), 'hello world\n42\n')

    def test_file_creates_missing_parent_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'build', 'out', 'notes.txt')
            _Harness.run(statements=[
                f'let f = "{path}";',
                'file(f);',
                'f.write("x");',
                'f.close();',
            ])
            with open(path) as handle:
                self.assertEqual(handle.read(), 'x\n')

    def test_file_with_returned_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'gen.srn')
            _Harness.run(statements=[
                f'let f = file("{path}");',
                'f.write("func main() => ( println(42); )");',
                'f.close();',
            ])
            with open(path) as handle:
                self.assertEqual(handle.read(), 'func main() => ( println(42); )\n')

    def test_write_requires_a_file_handle(self):
        with self.assertRaisesRegex(evaluator.RuntimeError, "'s.write' is only supported on file handles"):
            _Harness.run(statements=[
                'let s = "abc";',
                's.write("x");',
            ])

    def test_method_on_undefined_variable(self):
        with self.assertRaisesRegex(evaluator.RuntimeError, "undefined variable 'missing'"):
            _Harness.run(statements=[
                'missing.close();',
            ])

    def test_file_requires_a_string_path(self):
        with self.assertRaisesRegex(evaluator.RuntimeError, 'file expects a string path'):
            _Harness.run(statements=[
                'file(42);',
            ])


if __name__ == '__main__':
    unittest.main()