"""Tests for the self-hosted bootstrap front end (scanner.srn, parser.srn,
evaluator.srn).

The bootstrap scanner is a Serenity reimplementation of src/scanner.py. It
exposes `scan(source)` -> list of `[type, lexeme, line, column]` token values.
Because the language can surface problems only by printing, the self-hosted
scanner prints "SCAN ERROR: ..." and returns an ERROR token (type 0) where the
host scanner raises.

The bootstrap parser is a Serenity reimplementation of src/parser.py. It
exposes `parse(tokens)` -> a tree of nested-list nodes. Where the host parser
raises ParseError, it prints "PARSE ERROR: ..." and fails the whole parse by
returning an empty ["Program", []] program.

The bootstrap evaluator is a Serenity reimplementation of src/evaluator.py. It
exposes `eInterpret(program) -> [value, state]` where the state carries the
environment, print output, status code, error argument and function table.
Where the host evaluator raises an operation error, it prints "RUNTIME ERROR:
..." and returns status 2.

The parity tests run both implementations over the same text and assert
byte-for-byte identical output. The error tests pin down the recovery
behaviour, and the self-host milestone tests run each module over its own
source.
"""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Interpreting the multi-thousand-line bootstrap driver nests interpreter
# frames deep enough to blow the default CPython recursion limit.
sys.setrecursionlimit(100000)

from src import scanner, parser, evaluator, code_generator
from src import ast_nodes as nodes

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOTSTRAP_DIR = os.path.join(PROJECT_ROOT, 'bootstrap')


def _to_string(value):
    """Reimplement Serenity's `toString` builtin so a token dump produced by
    the host scanner can be compared with one produced by scan()."""
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
    if isinstance(value, (tuple, list)):
        return '[' + ', '.join(_to_string(item) for item in value) + ']'
    raise AssertionError(f'cannot stringify {value!r}')


def _serenity_literal(text):
    """Escape a Python string as a Serenity string literal: double backslashes
    and quotes. Newlines and tabs are left raw; the scanner preserves them."""
    out = []
    for char in text:
        if char == '\\':
            out.append('\\\\')
        elif char == '"':
            out.append('\\"')
        else:
            out.append(char)
    return '"' + ''.join(out) + '"'


def _to_tree(node):
    """Convert a host AST node into the nested-list tree that the bootstrap
    parser produces, so the two can be compared byte-for-byte."""
    if isinstance(node, nodes.Program):
        return ['Program', [_to_tree(function) for function in node.functions]]
    if isinstance(node, nodes.Function):
        return ['Function', node.name, list(node.params), [_to_tree(s) for s in node.body]]
    if isinstance(node, nodes.ExprStmt):
        return ['ExprStmt', _to_tree(node.expression)]
    if isinstance(node, nodes.LetStmt):
        return ['LetStmt', node.name, _to_tree(node.initializer)]
    if isinstance(node, nodes.AssignStmt):
        return ['AssignStmt', node.name, _to_tree(node.value)]
    if isinstance(node, nodes.IfStmt):
        branch = node.else_branch
        if isinstance(branch, nodes.IfStmt):
            else_tree = _to_tree(branch)
        elif branch is None:
            else_tree = None
        else:
            else_tree = [_to_tree(s) for s in branch]
        return ['IfStmt', _to_tree(node.condition),
                [_to_tree(s) for s in node.then_branch], else_tree]
    if isinstance(node, nodes.WhileStmt):
        return ['WhileStmt', _to_tree(node.condition), [_to_tree(s) for s in node.body]]
    if isinstance(node, nodes.ForStmt):
        return ['ForStmt', _to_tree(node.initializer), _to_tree(node.condition),
                _to_tree(node.increment), [_to_tree(s) for s in node.body]]
    if isinstance(node, nodes.IncrementStmt):
        return ['IncrementStmt', node.name]
    if isinstance(node, nodes.ReturnStmt):
        return ['ReturnStmt', _to_tree(node.expression)]
    if isinstance(node, nodes.IntLiteral):
        return ['IntLiteral', node.value]
    if isinstance(node, nodes.StringLiteral):
        return ['StringLiteral', node.value]
    if isinstance(node, nodes.BoolLiteral):
        return ['BoolLiteral', node.value]
    if isinstance(node, nodes.NullLiteral):
        return ['NullLiteral']
    if isinstance(node, nodes.Identifier):
        return ['Identifier', node.name]
    if isinstance(node, nodes.Binary):
        return ['Binary', _to_tree(node.left), node.operator, _to_tree(node.right)]
    if isinstance(node, nodes.Unary):
        return ['Unary', node.operator, _to_tree(node.operand)]
    if isinstance(node, nodes.Conditional):
        return ['Conditional', _to_tree(node.condition),
                _to_tree(node.if_true), _to_tree(node.if_false)]
    if isinstance(node, nodes.Call):
        return ['Call', node.callee, [_to_tree(a) for a in node.arguments]]
    if isinstance(node, nodes.MethodCall):
        return ['MethodCall', node.receiver, node.method, [_to_tree(a) for a in node.arguments]]
    if isinstance(node, nodes.ListLiteral):
        return ['ListLiteral', [_to_tree(e) for e in node.elements]]
    raise AssertionError(f'cannot convert {node!r} to a tree')


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
    def selfhost_scan(source_text):
        """Run the bootstrap scanner's `scan` on SOURCE_TEXT and return the
        printed token dump."""
        with open(os.path.join(BOOTSTRAP_DIR, 'scanner.srn')) as handle:
            scanner_source = handle.read()
        driver = (
            scanner_source
            + 'func main() => (\n'
            + f'    println(toString(scan({_serenity_literal(source_text)})));\n'
            + ')\n'
        )
        return _Harness.interpret(driver)

    @staticmethod
    def selfhost_parse(source_text):
        """Run the bootstrap parser's `parse(scan(...))` on SOURCE_TEXT and
        return the printed tree dump."""
        with open(os.path.join(BOOTSTRAP_DIR, 'scanner.srn')) as handle:
            scanner_source = handle.read()
        with open(os.path.join(BOOTSTRAP_DIR, 'parser.srn')) as handle:
            parser_source = handle.read()
        driver = (
            scanner_source
            + parser_source
            + 'func main() => (\n'
            + f'    println(toString(parse(scan({_serenity_literal(source_text)}))));\n'
            + ')\n'
        )
        return _Harness.interpret(driver)

    @staticmethod
    def host_scan_dump(source_text):
        tokens = scanner.Scanner(source_text).scan_tokens()
        return _to_string([[token.type.value, token.lexeme, token.line, token.column]
                           for token in tokens])

    @staticmethod
    def host_parse_dump(source_text):
        tokens = scanner.Scanner(source_text).scan_tokens()
        program = parser.Parser(tokens).parse()
        return _to_string(_to_tree(program))

    @staticmethod
    def selfhost_interpret(source_text):
        """Run the bootstrap interpreter's `eInterpret(parse(scan(...)))` on
        SOURCE_TEXT and return the printed output, followed by the printed
        "RUNTIME ERROR: ..." line when the program fails at runtime."""
        with open(os.path.join(BOOTSTRAP_DIR, 'scanner.srn')) as handle:
            scanner_source = handle.read()
        with open(os.path.join(BOOTSTRAP_DIR, 'parser.srn')) as handle:
            parser_source = handle.read()
        with open(os.path.join(BOOTSTRAP_DIR, 'evaluator.srn')) as handle:
            evaluator_source = handle.read()
        driver = (
            scanner_source
            + parser_source
            + evaluator_source
            + 'func main() => (\n'
            + f'    let r = eInterpret(parse(scan({_serenity_literal(source_text)})));\n'
            + '    let st = eSt(r);\n'
            + '    let out = eOut(st);\n'
            + '    let i = 0;\n'
            + '    while (i < length(out)) => {\n'
            + '        print(at(out, i));\n'
            + '        i = i + 1;\n'
            + '    }\n'
            + '    if (eStatus(st) == 2) => {\n'
            + '        print("RUNTIME ERROR: " + eArg(st) + "\\n");\n'
            + '    }\n'
            + ')\n'
        )
        return _Harness.interpret(driver)

    @staticmethod
    def host_eval(source_text):
        """Evaluate SOURCE_TEXT with the host evaluator directly, matching the
        bootstrap interpreter's convention of reporting runtime failures as a
        printed "RUNTIME ERROR: ..." line."""
        try:
            return _Harness.interpret(source_text)
        except Exception as error:  # noqa: BLE001 - operator errors are data
            return 'RUNTIME ERROR: ' + str(error) + '\n'

    @staticmethod
    def selfhost_compile(source_text):
        """Run the bootstrap compiler's `cgen(parse(scan(...)))` on
        SOURCE_TEXT and return the emitted assembly, or the printed
        "COMPILE ERROR: ..." line followed by nothing when compilation
        fails."""
        with open(os.path.join(BOOTSTRAP_DIR, 'scanner.srn')) as handle:
            scanner_source = handle.read()
        with open(os.path.join(BOOTSTRAP_DIR, 'parser.srn')) as handle:
            parser_source = handle.read()
        with open(os.path.join(BOOTSTRAP_DIR, 'code_generator.srn')) as handle:
            cgen_source = handle.read()
        driver = (
            scanner_source
            + parser_source
            + cgen_source
            + 'func main() => (\n'
            + f'    print(cgen(parse(scan({_serenity_literal(source_text)}))));\n'
            + ')\n'
        )
        return _Harness.interpret(driver)

    @staticmethod
    def host_compile(source_text):
        """Compile SOURCE_TEXT with the host compiler, conventions as for the
        bootstrap compiler: failed programs compile to the text
        "COMPILE ERROR: <message>\\n"."""
        try:
            tokens = scanner.Scanner(source_text).scan_tokens()
            program = parser.Parser(tokens).parse()
            return code_generator.CodeGen(program).generate()
        except code_generator.CompileError as error:
            return 'COMPILE ERROR: ' + str(error) + '\n'


class ScannerParityTests(unittest.TestCase):
    _SOURCES = [
        '',
        '   \n\t ',
        'let x = 42;',
        '// hello world\nlet y = 1;',
        '/* block */ 1',
        '/* multi\nline\ncomment */ x',
        'func f(a, b) => ( return a + b; )',
        '"hi" + 42',
        'true false null',
        'a_b12 _under score2',
        '1 % 2 ^ 3',
        'x == y != z <= w >= v && u || t',
        'a := b',
        'x++; --y;',
        's += 1;',
        '"esc \\n \\t \\r \\" \\\\"',
        '"line1\nline2"',
        '123 45 6789',
        'func pow(b, e) => ( if (e <= 0) => { return 1; }'
        ' else => { return b * pow(b, e - 1); } )',
        'let s = "a" + "b" + toString([1, 2, 3]);',
        '{ } [ ] ( ) , ; ? :',
        'length([1, 2]) >= 2 ? "big" : "small"',
        'for (let i = 0; i < 3; i++) => { println(i); }',
        'f.write("x");',
        'a.b(1, 2);',
        'let f = "out.txt"; file(f); f.write("hi");',
    ]

    def test_all_samples_match_host_scanner(self):
        for source in self._SOURCES:
            with self.subTest(source=source):
                self.assertEqual(
                    _Harness.selfhost_scan(source),
                    _Harness.host_scan_dump(source) + '\n',
                )

    def test_empty_input_produces_single_eof(self):
        self.assertEqual(
            _Harness.selfhost_scan(''),
            '[[43, , 1, 1]]\n',
        )

    def test_scanner_scans_its_own_source(self):
        """The bootstrap scanner tokenises its own source identically to the
        host scanner - the first self-hosting milestone."""
        with open(os.path.join(BOOTSTRAP_DIR, 'scanner.srn')) as handle:
            own_source = handle.read()
        self.assertEqual(
            _Harness.selfhost_scan(own_source),
            _Harness.host_scan_dump(own_source) + '\n',
        )

    def test_keywords_and_identifiers(self):
        self.assertEqual(
            _Harness.selfhost_scan('func let true false null if else while for return x'),
            '[[1, func, 1, 1], [2, let, 1, 6], [3, true, 1, 10], [4, false, 1, 15], '
            '[5, null, 1, 21], [35, if, 1, 26], [36, else, 1, 29], [37, while, 1, 34], '
            '[38, for, 1, 40], [42, return, 1, 44], [6, x, 1, 51], [43, , 1, 52]]\n',
        )


class ScannerErrorTests(unittest.TestCase):
    def test_unexpected_character(self):
        self.assertEqual(
            _Harness.selfhost_scan('let f = 2#5;'),
            "SCAN ERROR: unexpected character '#'\n"
            '[[2, let, 1, 1], [6, f, 1, 5], [34, =, 1, 7], [7, 2, 1, 9], '
            '[0, #, 1, 10], [7, 5, 1, 11], [12, ;, 1, 12], [43, , 1, 13]]\n',
        )

    def test_at_sign_is_an_error_token(self):
        self.assertEqual(
            _Harness.selfhost_scan('@'),
            "SCAN ERROR: unexpected character '@'\n" + '[[0, @, 1, 1], [43, , 1, 2]]\n',
        )

    def test_unterminated_string(self):
        self.assertEqual(
            _Harness.selfhost_scan('"abc'),
            'SCAN ERROR: unterminated string\n'
            '[[0, abc, 1, 1], [43, , 1, 5]]\n',
        )

    def test_unterminated_trailing_escape(self):
        self.assertEqual(
            _Harness.selfhost_scan('"abc\\'),
            'SCAN ERROR: unterminated string\n'
            '[[0, abc, 1, 1], [43, , 1, 5]]\n',
        )

    def test_unterminated_block_comment(self):
        self.assertEqual(
            _Harness.selfhost_scan('/* abc'),
            'SCAN ERROR: unterminated block comment\n'
            '[[43, , 1, 7]]\n',
        )


class ParserParityTests(unittest.TestCase):
    _SOURCES = [
        '',
        'func main() => ( )',
        'func main() => ( 42; )',
        'func f(a, b) => ( return a + b; )',
        'func main() => ( let x = 1; let y = 2; x = y; x++; )',
        'func main() => ( let z := 3; )',
        'func main() => ( let x = 1; if (x) => { let a = 1; } else => { let b = 2; } )',
        'func main() => ( if (a) => { x; } else => { if (b) => { y; } else => { z; } } )',
        'func main() => ( while (i < 10) => { i++; } )',
        'func main() => ( for (let i = 0; i < 3; i++) => { println(i); } )',
        'func main() => ( for (let i = 0; i < 3; i++) => { } )',
        'func main() => ( let r = x > 5 ? f(1, 2, 3) : -g(); )',
        'func main() => ( let xs = [1, 2, 3]; let ys = []; )',
        'func main() => ( let s = "hi" + " there"; )',
        'func main() => ( let b = !a && b || c == d != e <= f >= g < h > i; )',
        'func main() => ( let p = 2 ^ 3 ^ 2; let u = -x; )',
        'func main() => ( f(g(h(x)), [1, [2, [3]]]); )',
        'func main() => ( 1 + 2 * 3 - 4 / 5 % 6; )',
        'func greeting(name) => ( return "Hello, " + name; )\n'
        'func main() => ( println(greeting("World")); )',
        'func fib(n) => ( if (n <= 1) => { return n; }'
        ' else => { return fib(n - 1) + fib(n - 2); } )',
        'func main() => ( let n = 0; while (n < 3) => { println(n); n++; } )',
        'func main() => ( f(); )',
        'func main() => ( g([1], [2]); )',
        'func main() => ( if (flag) => { } )',
        'func main() => ( null; true; false; )',
        'func main() => ( let s = "esc \\n \\t \\r \\" \\\\"; )',
        'func main() => ( let f = "out.txt"; file(f); f.write("a"); f.write(1 + 2); f.close(); )',
        'func main() => ( g.write(); )',
        'func main() => ( order.line("x", y); )',
        '// leading comment\nfunc main() => ( 0; ) // trailing comment',
        '/* block\ncomment */ func main() => ( 1; )',
    ]

    def test_all_samples_match_host_parser(self):
        for source in self._SOURCES:
            with self.subTest(source=source):
                self.assertEqual(
                    _Harness.selfhost_parse(source),
                    _Harness.host_parse_dump(source) + '\n',
                )

    def test_empty_input_parses_to_empty_program(self):
        self.assertEqual(
            _Harness.selfhost_parse(''),
            '[Program, []]\n',
        )

    def test_parser_parses_its_own_source(self):
        """The bootstrap parser parses its own token stream identically to the
        host parser - the second self-hosting milestone."""
        with open(os.path.join(BOOTSTRAP_DIR, 'parser.srn')) as handle:
            own_source = handle.read()
        self.assertEqual(
            _Harness.selfhost_parse(own_source),
            _Harness.host_parse_dump(own_source) + '\n',
        )


class ParserErrorTests(unittest.TestCase):
    """The host parser raises ParseError where the bootstrap parser prints
    "PARSE ERROR: ..." and returns the empty program. Each assertion pins the
    bootstrap's message; the host raises with equivalent text."""

    def test_top_level_let(self):
        self.assertEqual(
            _Harness.selfhost_parse('let x = 5;'),
            "PARSE ERROR: 1:1: expected 'func'; found 'let'\n[Program, []]\n",
        )

    def test_top_level_increment(self):
        self.assertEqual(
            _Harness.selfhost_parse('x++;'),
            "PARSE ERROR: 1:1: expected 'func'; found 'x'\n[Program, []]\n",
        )

    def test_dangling_func_keyword(self):
        self.assertEqual(
            _Harness.selfhost_parse('func '),
            "PARSE ERROR: 1:6: expected function name; found ''\n[Program, []]\n",
        )

    def test_missing_initializer_expression(self):
        self.assertEqual(
            _Harness.selfhost_parse('func main() => ( let x = ; )'),
            "PARSE ERROR: 1:26: expected expression; found ';'\n[Program, []]\n",
        )

    def test_missing_initializer_operator(self):
        self.assertEqual(
            _Harness.selfhost_parse('func main() => ( let x 5; )'),
            "PARSE ERROR: 1:24: expected '=' or ':=' after variable name; found '5'\n"
            '[Program, []]\n',
        )

    def test_missing_semicolon_after_statement(self):
        self.assertEqual(
            _Harness.selfhost_parse('func main() => ( let x = 5 )'),
            "PARSE ERROR: 1:28: expected ';' after statement; found ')'\n"
            '[Program, []]\n',
        )

    def test_unterminated_function_body(self):
        self.assertEqual(
            _Harness.selfhost_parse('func f() => ( let x = 5;'),
            'PARSE ERROR: unexpected end of file in block\n[Program, []]\n',
        )

    def test_missing_paren_after_while(self):
        self.assertEqual(
            _Harness.selfhost_parse('func main() => ( while x ) => { } )'),
            "PARSE ERROR: 1:24: expected '(' after 'while'; found 'x'\n"
            '[Program, []]\n',
        )

    def test_grouped_expression_missing_paren(self):
        self.assertEqual(
            _Harness.selfhost_parse('func main() => ( let x = (1 + 2; )'),
            "PARSE ERROR: 1:32: expected ')' after expression; found ';'\n"
            '[Program, []]\n',
        )

    def test_call_arguments_missing_paren(self):
        self.assertEqual(
            _Harness.selfhost_parse('func main() => ( f(1, 2; )'),
            "PARSE ERROR: 1:24: expected ')' after arguments; found ';'\n"
            '[Program, []]\n',
        )

    def test_list_elements_missing_bracket(self):
        self.assertEqual(
            _Harness.selfhost_parse('func main() => ( [1, 2; )'),
            "PARSE ERROR: 1:23: expected ']' after list elements; found ';'\n"
            '[Program, []]\n',
        )

    def test_missing_else_arrow(self):
        self.assertEqual(
            _Harness.selfhost_parse('func main() => ( if (x) => { } else { } )'),
            "PARSE ERROR: 1:37: expected '=>' after 'else'; found '{'\n"
            '[Program, []]\n',
        )


class EvaluatorParityTests(unittest.TestCase):
    """Run small programs through the bootstrap interpreter
    (`eInterpret(parse(scan(...)))`) and through the host evaluator directly;
    the printed output must be byte-identical."""

    _SOURCES = [
        'func greet(n) => ( return n * 2; )\n'
        'func main() => ( println(greet(21)); )',
        'func main() => ( println("hello"); )',
        'func main() => ( println(1 + 2 * 3); )',
        'func main() => ( println("a" + "b" + "c"); )',
        'func main() => ( println(7 % 3); println(2 ^ 10); )',
        'func main() => ( println(2 ^ 3 ^ 2); )',
        'func main() => ( println(10 % 3 - 2 ^ 2 + 1); )',
        'func main() => ( let x = -5; println(x + 3); println(-x); )',
        'func main() => ( println(true == true); println(3 != 4); '
        'println(3 >= 3); println(3 < 4); println(4 <= 4); println(4 > 3); )',
        'func main() => ( println(!false); println(true && false); '
        'println(false || true); )',
        'func fac(n) => ( if (n <= 1) => { return 1; }'
        ' else => { return n * fac(n - 1); } )\n'
        'func main() => ( println(fac(10)); )',
        'func fib(n) => ( if (n <= 1) => { return n; }'
        ' else => { return fib(n - 1) + fib(n - 2); } )\n'
        'func main() => ( println(fib(10)); )',
        'func main() => ( let x = 1; x = x + 1; println(x); )',
        'func main() => ( let n = 0; while (n < 3) => { println(n); n = n + 1; } )',
        'func main() => ( for (let i = 0; i < 3; i++) => { println(i); } )',
        'func main() => ( let xs = [1, 2, 3]; println(append(xs, 4)); '
        'println(prepend(xs, 0)); println(reverse(xs)); println(concat(xs, [5, 6])); )',
        'func main() => ( println(at([1, 2, 3], 1)); println(length([1, 2, 3])); )',
        'func main() => ( println(toString([1, "a", true, null])); )',
        'func main() => ( println(join(["a", "b", "c"], "-")); '
        'println(toUpper("abc")); println(toLower("ABC")); println(trim("  x  ")); )',
        'func main() => ( println(substring("hello", 1, 3)); '
        'println(charAt("hello", 2)); println(toInt("42")); )',
        'func main() => ( println(contains("hello", "ell")); '
        'println(indexOf("hello", "l")); )',
        'func main() => ( println([[1, 2], [3, [4]]]); )',
        'func main() => ( let x = null; println(x); println(x == null); )',
        'func main() => ( if (1 + 1 == 2) => { println("yes"); }'
        ' else => { println("no"); } )',
        'func main() => ( let a = false; if (a) => { println("a"); }'
        ' else => { if (2 > 1) => { println("b"); } else => { println("c"); } } )',
        'func main() => ( for (let i = 0; i < 2; i++) => { let r = 0; '
        'let n = 0; while (n <= i) => { r = r + n; n = n + 1; } println(r); } )',
        'func main() => ( let m = [["a", 1], ["b", 2]]; let total = 0; '
        'for (let i = 0; i < length(m); i++) => { '
        'total = total + at(at(m, i), 1); } println(total); )',
        'func main() => ( println("total: " + toString(6 * 7)); )',
        'func main() => ( println(2 + 3 * 4); println((2 + 3) * 4); )',
        'func main() => ( let s = "abc"; println(s + s); println(s == "abc"); '
        'println(s != "x"); )',
    ]

    def test_all_samples_match_host_evaluator(self):
        for source in self._SOURCES:
            with self.subTest(source=source):
                self.assertEqual(
                    _Harness.selfhost_interpret(source),
                    _Harness.interpret(source),
                )

    def test_exit_stops_the_program(self):
        """A program calling `exit` halts the whole run: anything printed
        before is kept, anything after is not."""
        self.assertEqual(
            _Harness.selfhost_interpret(
                'func main() => ( println("before"); exit(); println("after"); )'
            ),
            'before\n',
        )


class EvaluatorErrorTests(unittest.TestCase):
    """The bootstrap interpreter reports failed programs as status 2 with the
    printed line "RUNTIME ERROR: ...", and the host raises an equivalent
    OperationError. Only graceful failures are pinned: mixed-type operators the
    host cannot evaluate (e.g. `null + 1`) crash the host with a TypeError, so
    those are out of scope."""

    def assert_runtime_error(self, source, message):
        self.assertEqual(
            _Harness.selfhost_interpret(source),
            'RUNTIME ERROR: ' + message + '\n',
        )

    def test_cannot_concatenate_string(self):
        self.assert_runtime_error(
            'func main() => ( println(1 + "a"); )',
            'cannot concatenate a string with a non-string',
        )

    def test_division_by_zero(self):
        self.assert_runtime_error(
            'func main() => ( println(5 / 0); )',
            'division by zero',
        )

    def test_modulo_by_zero(self):
        self.assert_runtime_error(
            'func main() => ( println(5 % 0); )',
            'division by zero',
        )

    def test_length_of_integer(self):
        self.assert_runtime_error(
            'func main() => ( println(length(5)); )',
            'length expects a string argument or a list, got integer',
        )

    def test_undefined_function_call(self):
        self.assert_runtime_error(
            'func main() => ( println(undefined_fn(1)); )',
            "undefined function 'undefined_fn'",
        )

    def test_at_out_of_bounds(self):
        self.assert_runtime_error(
            'func main() => ( println(at([1], 5)); )',
            'at index 5 out of bounds for list of length 1',
        )

    def test_cannot_compare_integer_with_string(self):
        self.assert_runtime_error(
            'func main() => ( println(1 < "a"); )',
            "cannot compare integer with string using '<'",
        )

    def test_undefined_variable(self):
        self.assert_runtime_error(
            'func main() => ( println(toString(missing)); )',
            "undefined variable 'missing'",
        )

    def test_error_pins_match_host_text(self):
        """The exact RUNTIME ERROR strings above match what the host evaluator
        raises, so the bootstrap output and the host error are interchangeable."""
        for source in (
            'func main() => ( println(1 + "a"); )',
            'func main() => ( println(5 / 0); )',
            'func main() => ( println(length(5)); )',
            'func main() => ( println(undefined_fn(1)); )',
            'func main() => ( println(at([1], 5)); )',
            'func main() => ( println(1 < "a"); )',
            'func main() => ( println(toString(missing)); )',
        ):
            with self.subTest(source=source):
                self.assertEqual(
                    _Harness.selfhost_interpret(source),
                    _Harness.host_eval(source),
                )


class CodegenParityTests(unittest.TestCase):
    """Run small programs through the bootstrap compiler
    (`cgen(parse(scan(...)))`) and through the host compiler directly; the
    emitted assembly must be byte-identical."""

    _SOURCES = [
        'func main() => ( println(42); )',
        'func main() => ( println("hello"); )',
        'func main() => ( println(1 + 2 * 3); )',
        'func main() => ( let x = 1; let y = 2; println(x + y); )',
        'func main() => ( println(true); println(false); println(null); )',
        'func main() => ( println("a" + "b"); println("x" == "x"); '
        'println("x" != "y"); )',
        'func main() => ( let s = "abc"; println(s + s); println(s == "abc"); '
        'println(s != "x"); )',
        'func main() => ( let x = 5; x = x + 1; println(x); )',
        'func main() => ( let x = 5; x = "s"; println(x); )',
        'func main() => ( let x = "a"; x = "b" + x; println(x); )',
        'func main() => ( let x = 5; let y = x; y = 9; println(x); println(y); )',
        'func main() => ( let b = 3 > 2 ? 100 : 200; println(b); )',
        'func main() => ( println(1 < 2 && 2 < 3); println(1 > 2 || 3 > 2); )',
        'func main() => ( println(2 ^ 10); println(7 % 3); println(7 / 2); '
        'println(-5); println(-x + 3); )',
        'func incr(n) => ( return n + 1; )\n'
        'func main() => ( println(incr(incr(41))); )',
        'func empty() => ( return 7; )\nfunc main() => ( println(empty()); )',
        'func f(s) => ( return s + "!"; )\n'
        'func main() => ( println(f("hey")); )',
        'func apply(f, x) => ( return f(x); )\n'
        'func dbl(n) => ( return n * 2; )\n'
        'func main() => ( println(apply(dbl, 21)); )',
        'func main() => ( let n = 0; let s = ""; '
        'while (n < 3) => { s = s + "x"; n = n + 1; } println(s); println(n); )',
        'func main() => ( let i = 100; '
        'for (let i = 0; i < 2; i++) => { println(i); } println(i); )',
        'func main() => ( let r = 0; '
        'for (let i = 0; i < 5; i++) => { '
        'if (i == 3) => { r = 100; } } println(r); )',
        'func main() => ( if ("a" == "a") => { println("eq"); } '
        'else => { println("ne"); } )',
        'func main() => ( println(3 <= 4 ? "y" : "n"); )',
        'func main() => ( println(charAt("hi", 0)); '
        'println(substring("hello", 1, 4)); println(toLower("ABC")); )',
        'func main() => ( println(toUpper(substring("hello world", 0, 5))); )',
        'func main() => ( let s = trim("  hi  "); println(s + charAt(s, 1)); )',
        'func main() => ( println(join(["a", "b"], "-")); '
        'println(toString(42)); println(toInt("17") + 3); )',
        'func main() => ( let y = "hi"; println(y == "hi"); )',
        'func main() => ( let a = "ab"; let b = "cd"; '
        'println(a + b == "abcd"); )',
        'func main() => ( let i = 0; let acc = ""; '
        'while (i < 3) => { acc = acc + toString(i); i = i + 1; } '
        'println(acc); )',
        'func greet(name) => ( return "Hi, " + name; )\n'
        'func main() => ( let total = 0; '
        'for (let i = 0; i < 3; i++) => { total = total + i; } '
        'println(greet("World")); println(total); '
        'println("total: " + toString(6 * 7)); '
        'println(greet("Once") == "Hi, Once"); )',
        'func main() => ( println("before"); exit(); println("after"); )',
    ]

    def test_all_samples_match_host_compiler(self):
        for source in self._SOURCES:
            with self.subTest(source=source):
                self.assertEqual(
                    _Harness.selfhost_compile(source),
                    _Harness.host_compile(source),
                )


class CodegenErrorTests(unittest.TestCase):
    """The host compiler raises CompileError where the bootstrap compiler
    prints "COMPILE ERROR: ..." and yields no assembly. Each assertion pins the
    bootstrap's message; the host raises with equivalent text."""

    def assert_compile_error(self, source, message):
        self.assertEqual(
            _Harness.selfhost_compile(source),
            'COMPILE ERROR: ' + message + '\n',
        )

    def test_no_main_function(self):
        self.assert_compile_error(
            '',
            "program must declare exactly one 'main' function",
        )

    def test_undefined_variable(self):
        self.assert_compile_error(
            'func main() => ( let x = y; )',
            "undefined variable 'y'",
        )

    def test_cannot_concatenate_string(self):
        self.assert_compile_error(
            'func main() => ( println(1 + "a"); )',
            'cannot concatenate a string with a non-string',
        )

    def test_null_in_numeric_expression(self):
        self.assert_compile_error(
            'func main() => ( null; )',
            'null cannot be used in a numeric expression',
        )

    def test_error_pins_match_host_text(self):
        for source in (
            '',
            'func main() => ( let x = y; )',
            'func main() => ( println(1 + "a"); )',
            'func main() => ( null; )',
        ):
            with self.subTest(source=source):
                self.assertEqual(
                    _Harness.selfhost_compile(source),
                    _Harness.host_compile(source),
                )


class SelfHostMilestoneTests(unittest.TestCase):
    def test_evaluator_interprets_its_own_pipeline(self):
        """The bootstrap scanner, parser and evaluator, interpreted by the
        bootstrap interpreter itself, run a target program end to end - the
        full self-hosting milestone."""
        with open(os.path.join(BOOTSTRAP_DIR, 'scanner.srn')) as handle:
            scanner_source = handle.read()
        with open(os.path.join(BOOTSTRAP_DIR, 'parser.srn')) as handle:
            parser_source = handle.read()
        with open(os.path.join(BOOTSTRAP_DIR, 'evaluator.srn')) as handle:
            evaluator_source = handle.read()
        own_source = (
            scanner_source
            + parser_source
            + evaluator_source
            + 'func main() => (\n'
            + '    let r = eInterpret(parse('
            'scan("func main() => ( println(6 * 7); )")));\n'
            + '    let s = eSt(r);\n'
            + '    print("STATUS=" + toString(eStatus(s)) + "\\n");\n'
            + ')\n'
        )
        self.assertEqual(
            _Harness.selfhost_interpret(own_source),
            _Harness.interpret(own_source),
        )

    def test_codegen_compiles_its_own_pipeline(self):
        """The bootstrap scanner, parser and code generator, interpreted by
        the bootstrap interpreter itself, compile a target program end to
        end - the final self-hosting milestone. (This runs the whole
        compiler under the bootstrap interpreter and is therefore slow.)"""
        with open(os.path.join(BOOTSTRAP_DIR, 'scanner.srn')) as handle:
            scanner_source = handle.read()
        with open(os.path.join(BOOTSTRAP_DIR, 'parser.srn')) as handle:
            parser_source = handle.read()
        with open(os.path.join(BOOTSTRAP_DIR, 'code_generator.srn')) as handle:
            cgen_source = handle.read()
        own_source = (
            scanner_source
            + parser_source
            + cgen_source
            + 'func main() => (\n'
            + '    print(cgen(parse('
            'scan("func main() => ( println(6 * 7); )"))));\n'
            + ')\n'
        )
        self.assertEqual(
            _Harness.selfhost_interpret(own_source),
            _Harness.interpret(own_source),
        )


if __name__ == '__main__':
    unittest.main()