"""macOS ARM64 code generator for the currently supported Serenity subset.

Output references `_write`, which is supplied by macOS's libSystem.dylib at link
time (for example: `clang output.s -o program`).

Strings are first-class compile-time values that survive through `let` and
constant folding, so control flow (conditions, loop bounds) can be decided at
compile time. Values that feed runtime `print`/`println` output, however, are
genuinely computed at runtime: string concatenation and the string library are
emitted as calls to `_serenity_*` subroutines that malloc and build actual byte
buffers when the program runs.
"""
from .ast_nodes import IntLiteral, StringLiteral, BoolLiteral, NullLiteral, Identifier, Binary, Unary, Conditional, Call, LetStmt, IfStmt, WhileStmt, ForStmt, IncrementStmt, ReturnStmt, ExprStmt, Function
from .binary_ops import apply as apply_operator, OperationError
from .string_builtins import (
    length, char_at, substring, to_upper, to_lower, trim, contains, index_of, to_int,
)


class CompileError(Exception):
    pass


MAX_LOOP_ITERATIONS = 1000000

STRING_PRODUCING_FUNCTIONS = {
    'charAt': (char_at, 2),
    'substring': (substring, 3),
    'toUpper': (to_upper, 1),
    'toLower': (to_lower, 1),
    'trim': (trim, 1),
}

NUMERIC_FUNCTIONS = {
    'length': (length, 1),
    'contains': (contains, 2),
    'indexOf': (index_of, 2),
    'toInt': (to_int, 1),
}

ALL_BUILTIN_FUNCTIONS = {**STRING_PRODUCING_FUNCTIONS, **NUMERIC_FUNCTIONS}


class CodeGen:
    def __init__(self, program):
        self.program = program
        self.user_functions = {f.name: f for f in program.functions}
        self.strings = []
        self.label = 0
        self.variables = {}
        self.runtime_var_offsets = {}
        self.runtime_var_types = {}
        self.runtime_next_var = 0
        self.return_label = None

    def generate(self):
        mains = [function for function in self.program.functions if function.name == 'main']
        if len(mains) != 1:
            raise CompileError("program must declare exactly one 'main' function")
        main = mains[0]
        if main.params:
            raise CompileError("'main' cannot take parameters")
        main_return_label = f'L_main_return_{self.label}'
        self.label += 1
        self.return_label = main_return_label
        body = self._compile_statements(main.body)
        self.return_label = None
        main_frame_size = (16 + 8 * self._count_runtime_lets(main.body) + 15) & ~15
        user_function_code = []
        for function in self.program.functions:
            if function.name != 'main':
                user_function_code.extend(self._compile_user_function(function))
                user_function_code.append('')

        bool_false_label, bool_false_size = self._new_string('false')
        bool_true_label, bool_true_size = self._new_string('true')
        data = ['.section __DATA,__data']
        for label, value in self.strings:
            data.extend([f'{label}:', f'    .asciz {self._quoted(value)}'])
        return '\n'.join([
            '.build_version macos, 11, 0 sdk_version 11, 0',
            '.globl _main',
            '.extern _write',
            '.extern _malloc',
            '.extern _exit',
            '.section __TEXT,__text,regular,pure_instructions',
            '_main:',
            f'    stp x29, x30, [sp, #-{main_frame_size}]!',
            '    mov x29, sp',
            *body,
            f'{main_return_label}:',
            '    mov w0, #0',
            f'    ldp x29, x30, [sp], #{main_frame_size}',
            '    ret',
            '',
            *user_function_code,
            # Converts the integer in x0 to decimal and writes it.
            # The compiler's arithmetic expressions currently produce integers.
            '_serenity_print_int:',
            '    stp x29, x30, [sp, #-48]!',
            '    mov x29, sp',
            '    mov x9, x0',
            '    add x1, sp, #47',
            '    mov x10, #10',
            '    mov w13, #0',
            '    cmp x9, #0',
            '    b.ge L_int_nonnegative',
            '    neg x9, x9',
            '    mov w13, #1',
            'L_int_nonnegative:',
            '    cmp x9, #0',
            '    b.ne L_int_loop',
            '    mov w11, #48',
            '    strb w11, [x1, #-1]!',
            '    b L_int_write',
            'L_int_loop:',
            '    udiv x11, x9, x10',
            '    msub x12, x11, x10, x9',
            '    add x12, x12, #48',
            '    strb w12, [x1, #-1]!',
            '    mov x9, x11',
            '    cbnz x9, L_int_loop',
            '    cbz w13, L_int_write',
            '    mov w11, #45',
            '    strb w11, [x1, #-1]!',
            'L_int_write:',
            '    add x2, sp, #47',
            '    sub x2, x2, x1',
            '    mov x0, #1',
            '    bl _write',
            '    ldp x29, x30, [sp], #48',
            '    ret',
            # Writes the boolean in x0 as "true"/"false".
            '_serenity_print_bool:',
            '    stp x29, x30, [sp, #-16]!',
            '    mov x29, sp',
            '    cbnz x0, L_bool_true',
            f'    adrp x1, {bool_false_label}@PAGE',
            f'    add x1, x1, {bool_false_label}@PAGEOFF',
            f'    mov x2, #{bool_false_size}',
            '    b L_bool_write',
            'L_bool_true:',
            f'    adrp x1, {bool_true_label}@PAGE',
            f'    add x1, x1, {bool_true_label}@PAGEOFF',
            f'    mov x2, #{bool_true_size}',
            'L_bool_write:',
            '    mov x0, #1',
            '    bl _write',
            '    ldp x29, x30, [sp], #16',
            '    ret',
            '',
            # Lexicographic string comparison of x0 (right, len x1) vs x2 (left,
            # len x3). Returns -1/0/+1 in x0.
            '_serenity_str_cmp:',
            '    mov x4, x0',
            '    mov x5, x1',
            '    mov x6, x2',
            '    mov x7, x3',
            '    mov x0, #0',
            '    mov x8, #0',
            'L_str_cmp_loop:',
            '    cmp x8, x5',
            '    b.ge L_str_cmp_after_right',
            '    cmp x8, x7',
            '    b.ge L_str_cmp_after_left',
            '    ldrb w9, [x6, x8]',
            '    ldrb w10, [x4, x8]',
            '    cmp x9, x10',
            '    b.lt L_str_cmp_less',
            '    b.gt L_str_cmp_greater',
            '    add x8, x8, #1',
            '    b L_str_cmp_loop',
            'L_str_cmp_after_right:',
            '    cmp x8, x7',
            '    b.lt L_str_cmp_greater',
            '    ret',
            'L_str_cmp_after_left:',
            '    mov x0, #-1',
            '    ret',
            'L_str_cmp_less:',
            '    mov x0, #-1',
            '    ret',
            'L_str_cmp_greater:',
            '    mov x0, #1',
            '    ret',
            '',
            # Concatenates x2 (left, len x3) with x0 (right, len x1), returning a
            # newly allocated string in x0 (ptr) and x1 (len).
            '_serenity_concat:',
            '    stp x29, x30, [sp, #-16]!',
            '    mov x29, sp',
            '    stp x0, x1, [sp, #-16]!',
            '    stp x2, x3, [sp, #-16]!',
            '    add x0, x1, x3',
            '    bl _malloc',
            '    mov x9, x0',
            '    ldp x2, x3, [sp], #16',
            '    ldp x10, x11, [sp], #16',
            '    mov x12, x9',
            '    mov x13, #0',
            'L_concat_copy_left:',
            '    cmp x13, x3',
            '    b.ge L_concat_copy_right',
            '    ldrb w14, [x2, x13]',
            '    strb w14, [x12, x13]',
            '    add x13, x13, #1',
            '    b L_concat_copy_left',
            'L_concat_copy_right:',
            '    mov x13, #0',
            '    add x12, x9, x3',
            'L_concat_copy_right_loop:',
            '    cmp x13, x11',
            '    b.ge L_concat_done',
            '    ldrb w14, [x10, x13]',
            '    strb w14, [x12, x13]',
            '    add x13, x13, #1',
            '    b L_concat_copy_right_loop',
            'L_concat_done:',
            '    mov x0, x9',
            '    add x1, x3, x11',
            '    ldp x29, x30, [sp], #16',
            '    ret',
            '',
            # Copies the range of x0 (src, len x1) from x2 (start) to x3 (end)
            # into a newly allocated string returned in x0/x1.
            '_serenity_substring:',
            '    stp x29, x30, [sp, #-16]!',
            '    mov x29, sp',
            '    stp x0, x1, [sp, #-16]!',
            '    stp x2, x3, [sp, #-16]!',
            '    sub x0, x3, x2',
            '    bl _malloc',
            '    mov x7, x0',
            '    ldp x2, x3, [sp], #16',
            '    ldp x0, x1, [sp], #16',
            '    sub x8, x3, x2',
            '    mov x10, #0',
            '    add x11, x0, x2',
            'L_substring_loop:',
            '    cmp x10, x8',
            '    b.ge L_substring_done',
            '    ldrb w12, [x11, x10]',
            '    strb w12, [x7, x10]',
            '    add x10, x10, #1',
            '    b L_substring_loop',
            'L_substring_done:',
            '    mov x0, x7',
            '    mov x1, x8',
            '    ldp x29, x30, [sp], #16',
            '    ret',
            '',
            # Copies the single character x2 of x0 (src, len x1) into a newly
            # allocated one-character string returned in x0/x1.
            '_serenity_char_at:',
            '    stp x29, x30, [sp, #-16]!',
            '    mov x29, sp',
            '    stp x0, x1, [sp, #-16]!',
            '    stp x2, xzr, [sp, #-16]!',
            '    mov x0, #1',
            '    bl _malloc',
            '    mov x5, x0',
            '    ldp x2, xzr, [sp], #16',
            '    ldp x0, x1, [sp], #16',
            '    ldrb w6, [x0, x2]',
            '    strb w6, [x5]',
            '    mov x0, x5',
            '    mov x1, #1',
            '    ldp x29, x30, [sp], #16',
            '    ret',
            '',
            # Uppercases ASCII a-z in x0 (ptr, len x1), returning new string.
            '_serenity_to_upper:',
            '    stp x29, x30, [sp, #-16]!',
            '    mov x29, sp',
            '    stp x0, x1, [sp, #-16]!',
            '    mov x0, x1',
            '    bl _malloc',
            '    mov x4, x0',
            '    ldp x2, x3, [sp], #16',
            '    mov x5, #0',
            'L_to_upper_loop:',
            '    cmp x5, x3',
            '    b.ge L_to_upper_done',
            '    ldrb w6, [x2, x5]',
            '    cmp w6, #97',
            '    b.lt L_to_upper_store',
            '    cmp w6, #122',
            '    b.gt L_to_upper_store',
            '    sub w6, w6, #32',
            'L_to_upper_store:',
            '    strb w6, [x4, x5]',
            '    add x5, x5, #1',
            '    b L_to_upper_loop',
            'L_to_upper_done:',
            '    mov x0, x4',
            '    mov x1, x3',
            '    ldp x29, x30, [sp], #16',
            '    ret',
            '',
            # Lowercases ASCII A-Z in x0 (ptr, len x1), returning new string.
            '_serenity_to_lower:',
            '    stp x29, x30, [sp, #-16]!',
            '    mov x29, sp',
            '    stp x0, x1, [sp, #-16]!',
            '    mov x0, x1',
            '    bl _malloc',
            '    mov x4, x0',
            '    ldp x2, x3, [sp], #16',
            '    mov x5, #0',
            'L_to_lower_loop:',
            '    cmp x5, x3',
            '    b.ge L_to_lower_done',
            '    ldrb w6, [x2, x5]',
            '    cmp w6, #65',
            '    b.lt L_to_lower_store',
            '    cmp w6, #90',
            '    b.gt L_to_lower_store',
            '    add w6, w6, #32',
            'L_to_lower_store:',
            '    strb w6, [x4, x5]',
            '    add x5, x5, #1',
            '    b L_to_lower_loop',
            'L_to_lower_done:',
            '    mov x0, x4',
            '    mov x1, x3',
            '    ldp x29, x30, [sp], #16',
            '    ret',
            '',
            # Strips ASCII whitespace from both ends of x0 (ptr, len x1),
            # returning a newly allocated string.
            '_serenity_trim:',
            '    stp x29, x30, [sp, #-16]!',
            '    mov x29, sp',
            '    stp x0, x1, [sp, #-16]!',
            '    mov x2, x0',
            '    mov x3, x1',
            '    mov x4, #0',
            'L_trim_skip_start:',
            '    cmp x4, x3',
            '    b.ge L_trim_compute',
            '    ldrb w5, [x2, x4]',
            '    cmp w5, #32',
            '    b.eq L_trim_next_start',
            '    cmp w5, #9',
            '    b.eq L_trim_next_start',
            '    cmp w5, #10',
            '    b.eq L_trim_next_start',
            '    cmp w5, #13',
            '    b.eq L_trim_next_start',
            '    b L_trim_compute',
            'L_trim_next_start:',
            '    add x4, x4, #1',
            '    b L_trim_skip_start',
            'L_trim_compute:',
            '    mov x6, x3',
            'L_trim_skip_end:',
            '    cmp x6, x4',
            '    b.le L_trim_copy',
            '    add x7, x6, #-1',
            '    ldrb w5, [x2, x7]',
            '    cmp w5, #32',
            '    b.eq L_trim_next_end',
            '    cmp w5, #9',
            '    b.eq L_trim_next_end',
            '    cmp w5, #10',
            '    b.eq L_trim_next_end',
            '    cmp w5, #13',
            '    b.eq L_trim_next_end',
            '    b L_trim_copy',
            'L_trim_next_end:',
            '    sub x6, x6, #1',
            '    b L_trim_skip_end',
            'L_trim_copy:',
            '    sub x8, x6, x4',
            '    stp x8, x4, [sp, #-16]!',
            '    mov x0, x8',
            '    bl _malloc',
            '    mov x9, x0',
            '    ldp x8, x4, [sp], #16',
            '    ldp x2, x3, [sp], #16',
            '    mov x10, #0',
            '    add x11, x2, x4',
            'L_trim_copy_loop:',
            '    cmp x10, x8',
            '    b.ge L_trim_done',
            '    ldrb w5, [x11, x10]',
            '    strb w5, [x9, x10]',
            '    add x10, x10, #1',
            '    b L_trim_copy_loop',
            'L_trim_done:',
            '    mov x0, x9',
            '    mov x1, x8',
            '    ldp x29, x30, [sp], #16',
            '    ret',
            '',
            '', *data, ''
        ])

    def _compile_statements(self, statements, scoped=False):
        saved_variables = self.variables.copy() if scoped else None
        body = []
        for statement in statements:
            if isinstance(statement, LetStmt):
                if statement.name in self.variables:
                    raise CompileError(f"variable '{statement.name}' is already declared")
                if statement.name in self.runtime_var_offsets:
                    raise CompileError(f"variable '{statement.name}' is already declared")
                if self._contains_runtime_value(statement.initializer):
                    if scoped:
                        raise CompileError("let with a user-defined function call inside a block is not yet supported")
                    offset = 16 + 8 * self.runtime_next_var
                    self.runtime_var_offsets[statement.name] = offset
                    self.runtime_var_types[statement.name] = self._classify_runtime_type(statement.initializer)
                    self.runtime_next_var += 1
                    body.extend(self._compile_runtime_expression(statement.initializer))
                    body.append(f'    str x0, [x29, #{offset}]')
                else:
                    self._validate_initializer(statement.initializer)
                    self.variables[statement.name] = statement.initializer
            elif isinstance(statement, IfStmt):
                condition = self._constant_value(statement.condition)
                branch = statement.then_branch if self._truthy(condition) else statement.else_branch
                if isinstance(branch, IfStmt):
                    body.extend(self._compile_statements([branch], scoped=True))
                elif branch is not None:
                    body.extend(self._compile_statements(branch, scoped=True))
            elif isinstance(statement, WhileStmt):
                body.extend(self._compile_while(statement))
            elif isinstance(statement, ForStmt):
                body.extend(self._compile_for(statement))
            elif isinstance(statement, IncrementStmt):
                self._apply_increment(statement.name)
            elif isinstance(statement, ReturnStmt):
                if self.return_label is None:
                    raise CompileError("'return' is only allowed inside a function")
                body.extend(self._expression(statement.expression))
                body.append(f'    b {self.return_label}')
            elif isinstance(statement, ExprStmt):
                body.extend(self._statement(statement.expression))
            else:
                raise CompileError(f'cannot compile statement {statement!r}')
        if scoped:
            for name in saved_variables:
                saved_variables[name] = self.variables[name]
            self.variables = saved_variables
        return body

    def _apply_increment(self, name):
        if name not in self.variables:
            raise CompileError(f"undefined variable '{name}'")
        current = self._constant_value(self.variables[name])
        if not isinstance(current, int) or isinstance(current, bool):
            raise CompileError(f"cannot increment non-integer variable '{name}'")
        self.variables[name] = IntLiteral(current + 1)

    def _compile_while(self, statement):
        body = []
        iterations = 0
        while self._truthy(self._constant_value(statement.condition)):
            if iterations >= MAX_LOOP_ITERATIONS:
                raise CompileError('while loop does not terminate at compile time')
            body.extend(self._compile_statements(statement.body, scoped=True))
            iterations += 1
        return body

    def _compile_for(self, statement):
        saved_variables = self.variables.copy()
        body = self._compile_statements([statement.initializer])
        iterations = 0
        while self._truthy(self._constant_value(statement.condition)):
            if iterations >= MAX_LOOP_ITERATIONS:
                raise CompileError('for loop does not terminate at compile time')
            body.extend(self._compile_statements(statement.body, scoped=True))
            self._apply_increment(statement.increment.name)
            iterations += 1
        for name in saved_variables:
            if name in self.variables:
                saved_variables[name] = self.variables[name]
        self.variables = saved_variables
        return body

    def _compile_user_function(self, function):
        """Generate an ARM64 subroutine for a user-defined function.

        Parameters arrive in x0..x7 per the ARM64 calling convention and are
        saved to the function's stack frame so the body can read and write
        them. The body is compiled for true runtime execution; the value left
        in x0 by the final expression is the return value.
        """
        saved_state = (self.runtime_var_offsets, self.runtime_var_types, self.runtime_next_var)
        saved_variables = self.variables
        self.variables = {}
        self.runtime_var_offsets = {}
        self.runtime_var_types = {}
        self.runtime_next_var = len(function.params)
        for index, param in enumerate(function.params):
            self.runtime_var_offsets[param] = 16 + 8 * index

        num_vars = len(function.params) + self._count_let_declarations(function.body)
        frame_size = (16 + 8 * num_vars + 15) & ~15
        exit_label = f'L_function_return_{self.label}'
        self.label += 1
        saved_return_label = self.return_label
        self.return_label = exit_label

        lines = [f'_serenity_{function.name}:']
        lines.append(f'    stp x29, x30, [sp, #-{frame_size}]!')
        lines.append('    mov x29, sp')
        for index, param in enumerate(function.params):
            lines.append(f'    str x{index}, [x29, #{16 + 8 * index}]')
        lines.extend(self._compile_runtime_statements(function.body))
        lines.append(f'{exit_label}:')
        lines.append(f'    ldp x29, x30, [sp], #{frame_size}')
        lines.append('    ret')

        self.runtime_var_offsets, self.runtime_var_types, self.runtime_next_var = saved_state
        self.variables = saved_variables
        self.return_label = saved_return_label
        return lines

    @staticmethod
    def _count_let_declarations(statements):
        count = 0
        for statement in statements:
            if isinstance(statement, LetStmt):
                count += 1
            elif isinstance(statement, IfStmt):
                count += CodeGen._count_let_declarations(statement.then_branch)
                if isinstance(statement.else_branch, IfStmt):
                    count += CodeGen._count_let_declarations([statement.else_branch])
                elif statement.else_branch is not None:
                    count += CodeGen._count_let_declarations(statement.else_branch)
            elif isinstance(statement, WhileStmt):
                count += CodeGen._count_let_declarations(statement.body)
            elif isinstance(statement, ForStmt):
                count += 1
                count += CodeGen._count_let_declarations(statement.body)
        return count

    def _count_runtime_lets(self, statements):
        count = 0
        for statement in statements:
            if isinstance(statement, LetStmt):
                if self._contains_runtime_value(statement.initializer):
                    count += 1
            elif isinstance(statement, IfStmt):
                count += self._count_runtime_lets(statement.then_branch)
                if isinstance(statement.else_branch, IfStmt):
                    count += self._count_runtime_lets([statement.else_branch])
                elif statement.else_branch is not None:
                    count += self._count_runtime_lets(statement.else_branch)
            elif isinstance(statement, WhileStmt):
                count += self._count_runtime_lets(statement.body)
            elif isinstance(statement, ForStmt):
                count += self._count_runtime_lets([statement.initializer])
                count += self._count_runtime_lets(statement.body)
        return count

    def _compile_runtime_statements(self, statements):
        lines = []
        for statement in statements:
            if isinstance(statement, LetStmt):
                offset = 16 + 8 * self.runtime_next_var
                self.runtime_var_offsets[statement.name] = offset
                self.runtime_var_types[statement.name] = self._classify_runtime_type(statement.initializer)
                self.runtime_next_var += 1
                lines.extend(self._compile_runtime_expression(statement.initializer))
                lines.append(f'    str x0, [x29, #{offset}]')
            elif isinstance(statement, IfStmt):
                lines.extend(self._compile_runtime_if(statement))
            elif isinstance(statement, WhileStmt):
                lines.extend(self._compile_runtime_while(statement))
            elif isinstance(statement, ForStmt):
                lines.extend(self._compile_runtime_for(statement))
            elif isinstance(statement, IncrementStmt):
                lines.extend(self._compile_runtime_increment(statement))
            elif isinstance(statement, ReturnStmt):
                if self.return_label is None:
                    raise CompileError("'return' is only allowed inside a function")
                lines.extend(self._compile_runtime_expression(statement.expression))
                lines.append(f'    b {self.return_label}')
            elif isinstance(statement, ExprStmt):
                lines.extend(self._compile_runtime_expression(statement.expression))
            else:
                raise CompileError(f'cannot compile statement {statement!r} in user function')
        return lines

    def _compile_runtime_expression(self, expression):
        if isinstance(expression, IntLiteral):
            return [f'    mov x0, #{expression.value}']
        if isinstance(expression, BoolLiteral):
            return [f'    mov x0, #{1 if expression.value else 0}']
        if isinstance(expression, NullLiteral):
            return ['    mov x0, #0']
        if isinstance(expression, StringLiteral):
            raise CompileError('string values in user-defined functions are not yet supported')
        if isinstance(expression, Identifier):
            if expression.name in self.runtime_var_offsets:
                return [f'    ldr x0, [x29, #{self.runtime_var_offsets[expression.name]}]']
            if expression.name in self.variables:
                return self._compile_runtime_expression(self.variables[expression.name])
            raise CompileError(f"undefined variable '{expression.name}'")
        if isinstance(expression, Unary):
            return self._compile_runtime_unary(expression)
        if isinstance(expression, Binary):
            return self._compile_runtime_binary(expression)
        if isinstance(expression, Conditional):
            return self._compile_runtime_conditional(expression)
        if isinstance(expression, Call):
            return self._compile_runtime_call(expression)
        raise CompileError(f'cannot compile expression {expression!r}')

    def _compile_runtime_unary(self, expression):
        lines = self._compile_runtime_expression(expression.operand)
        if expression.operator == '-':
            return lines + ['    neg x0, x0']
        if expression.operator == '!':
            return lines + ['    cmp x0, #0', '    cset w0, eq']
        raise CompileError(f'unsupported unary operator {expression.operator!r}')

    def _compile_runtime_binary(self, expression):
        lines = self._compile_runtime_expression(expression.left)
        lines.append('    str x0, [sp, #-16]!')
        lines.extend(self._compile_runtime_expression(expression.right))
        lines.append('    ldr x1, [sp], #16')
        operator = expression.operator
        if operator in ('+', '-', '*', '/'):
            instruction = {'+': 'add', '-': 'sub', '*': 'mul', '/': 'sdiv'}[operator]
            return lines + [f'    {instruction} x0, x1, x0']
        if operator == '%':
            return lines + ['    sdiv x2, x1, x0', '    msub x0, x2, x0, x1']
        if operator in ('==', '!=', '<', '<=', '>', '>='):
            condition = {'==': 'eq', '!=': 'ne', '<': 'lt', '<=': 'le', '>': 'gt', '>=': 'ge'}[operator]
            return lines + [f'    cmp x1, x0', f'    cset w0, {condition}']
        if operator == '&&':
            false_label = f'L_and_false_{self.label}'
            end_label = f'L_and_end_{self.label}'
            self.label += 1
            return lines + [
                f'    cmp x1, #0', f'    b.eq {false_label}',
                f'    cmp x0, #0', '    cset w0, ne', f'    b {end_label}',
                f'{false_label}:', '    mov x0, #0',
                f'{end_label}:',
            ]
        if operator == '||':
            true_label = f'L_or_true_{self.label}'
            end_label = f'L_or_end_{self.label}'
            self.label += 1
            return lines + [
                f'    cmp x1, #0', f'    b.ne {true_label}',
                f'    cmp x0, #0', '    cset w0, ne', f'    b {end_label}',
                f'{true_label}:', '    mov x0, #1',
                f'{end_label}:',
            ]
        raise CompileError(f'unsupported operator {operator!r} in runtime expression')

    def _compile_runtime_conditional(self, expression):
        false_label = f'L_cond_false_{self.label}'
        end_label = f'L_cond_end_{self.label}'
        self.label += 1
        lines = self._compile_runtime_expression(expression.condition)
        lines.extend(['    cmp x0, #0', f'    b.eq {false_label}'])
        lines.extend(self._compile_runtime_expression(expression.if_true))
        lines.extend([f'    b {end_label}', f'{false_label}:'])
        lines.extend(self._compile_runtime_expression(expression.if_false))
        lines.append(f'{end_label}:')
        return lines

    def _compile_runtime_if(self, statement):
        false_label = f'L_if_false_{self.label}'
        end_label = f'L_if_end_{self.label}'
        self.label += 1
        lines = self._compile_runtime_expression(statement.condition)
        lines.extend(['    cmp x0, #0', f'    b.eq {false_label}'])
        lines.extend(self._compile_runtime_statements(statement.then_branch))
        lines.append(f'    b {end_label}')
        lines.append(f'{false_label}:')
        if statement.else_branch is not None:
            if isinstance(statement.else_branch, IfStmt):
                lines.extend(self._compile_runtime_if(statement.else_branch))
            else:
                lines.extend(self._compile_runtime_statements(statement.else_branch))
        lines.append(f'{end_label}:')
        return lines

    def _compile_runtime_while(self, statement):
        start_label = f'L_while_start_{self.label}'
        end_label = f'L_while_end_{self.label}'
        self.label += 1
        lines = [f'{start_label}:']
        lines.extend(self._compile_runtime_expression(statement.condition))
        lines.extend(['    cmp x0, #0', f'    b.eq {end_label}'])
        lines.extend(self._compile_runtime_statements(statement.body))
        lines.extend([f'    b {start_label}', f'{end_label}:'])
        return lines

    def _compile_runtime_for(self, statement):
        lines = []
        if isinstance(statement.initializer, LetStmt):
            offset = 16 + 8 * self.runtime_next_var
            self.runtime_var_offsets[statement.initializer.name] = offset
            self.runtime_var_types[statement.initializer.name] = self._classify_runtime_type(statement.initializer.initializer)
            self.runtime_next_var += 1
            lines.extend(self._compile_runtime_expression(statement.initializer.initializer))
            lines.append(f'    str x0, [x29, #{offset}]')
        start_label = f'L_for_start_{self.label}'
        end_label = f'L_for_end_{self.label}'
        self.label += 1
        lines.append(f'{start_label}:')
        lines.extend(self._compile_runtime_expression(statement.condition))
        lines.extend(['    cmp x0, #0', f'    b.eq {end_label}'])
        lines.extend(self._compile_runtime_statements(statement.body))
        if isinstance(statement.increment, IncrementStmt):
            lines.extend(self._compile_runtime_increment(statement.increment))
        lines.extend([f'    b {start_label}', f'{end_label}:'])
        return lines

    def _compile_runtime_increment(self, statement):
        if statement.name not in self.runtime_var_offsets:
            raise CompileError(f"undefined variable '{statement.name}'")
        offset = self.runtime_var_offsets[statement.name]
        return [
            f'    ldr x0, [x29, #{offset}]',
            '    add x0, x0, #1',
            f'    str x0, [x29, #{offset}]',
        ]

    def _compile_runtime_call(self, expression):
        callee = expression.callee
        arguments = expression.arguments
        if callee in ('print', 'println'):
            return self._compile_runtime_print(callee, arguments)
        if callee == 'eval':
            if len(arguments) != 1:
                raise CompileError('eval expects one argument')
            return self._compile_runtime_expression(arguments[0])
        if callee == 'exit':
            if len(arguments) == 0:
                return ['    mov x0, #0', '    bl _exit']
            if len(arguments) != 1:
                raise CompileError('exit expects 0 or 1 argument')
            return [*self._compile_runtime_expression(arguments[0]), '    bl _exit']
        if callee in ALL_BUILTIN_FUNCTIONS:
            try:
                value = self._constant_value(expression)
            except CompileError:
                raise CompileError(f"builtin '{callee}' is not yet supported inside user-defined functions")
            if isinstance(value, bool):
                return [f'    mov x0, #{1 if value else 0}']
            if isinstance(value, int) and not isinstance(value, bool):
                return [f'    mov x0, #{value}']
            raise CompileError(f"call '{callee}' produces a non-numeric value")
        if callee not in self.user_functions:
            raise CompileError(f"undefined function '{callee}'")
        function = self.user_functions[callee]
        if len(arguments) != len(function.params):
            raise CompileError(f'{callee} expects {len(function.params)} arguments, got {len(arguments)}')
        if len(arguments) > 8:
            raise CompileError(f'too many arguments ({len(arguments)}), maximum is 8')
        lines = []
        for argument in reversed(arguments):
            lines.extend(self._compile_runtime_expression(argument))
            lines.append('    str x0, [sp, #-16]!')
        for index in range(len(arguments)):
            lines.append(f'    ldr x{index}, [sp], #16')
        lines.append(f'    bl _serenity_{callee}')
        return lines

    def _compile_runtime_print(self, callee, arguments):
        if len(arguments) != 1:
            raise CompileError(f'{callee} expects one argument')
        lines = self._compile_runtime_expression(arguments[0])
        lines.append('    bl _serenity_print_int')
        if callee == 'println':
            lines.extend(self._write_lines('\n'))
        return lines

    def _validate_initializer(self, expression):
        """Keep compiled `let` scope identical to the interpreter's scope."""
        if isinstance(expression, Identifier):
            if expression.name in self.runtime_var_offsets:
                return
            if expression.name not in self.variables:
                raise CompileError(f"undefined variable '{expression.name}'")
        elif isinstance(expression, Unary):
            self._validate_initializer(expression.operand)
        elif isinstance(expression, Binary):
            self._validate_initializer(expression.left)
            if expression.operator == '&&' and not self._truthy(self._constant_value(expression.left)):
                return
            if expression.operator == '||' and self._truthy(self._constant_value(expression.left)):
                return
            self._validate_initializer(expression.right)
        elif isinstance(expression, Call):
            for argument in expression.arguments:
                self._validate_initializer(argument)
        elif isinstance(expression, Conditional):
            self._validate_initializer(expression.condition)
            if self._truthy(self._constant_value(expression.condition)):
                self._validate_initializer(expression.if_true)
            else:
                self._validate_initializer(expression.if_false)

    @staticmethod
    def _quoted(value):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t') + '"'

    def _new_string(self, value):
        label = f'L_string_{len(self.strings)}'
        self.strings.append((label, value))
        return label, len(value.encode('utf-8'))

    def _statement(self, expression):
        if isinstance(expression, Call) and expression.callee in ('print', 'println'):
            return self._print_statement(expression)
        if isinstance(expression, Call) and expression.callee == 'exit':
            if len(expression.arguments) == 0:
                return ['    mov x0, #0', '    bl _exit']
            if len(expression.arguments) != 1:
                raise CompileError('exit expects 0 or 1 argument')
            return [*self._expression(expression.arguments[0]), '    bl _exit']
        if self._is_string_expression(expression):
            return self._string_expression(expression)
        return self._expression(expression)

    def _contains_runtime_value(self, expression):
        """True when the expression yields a value only known at runtime."""
        if isinstance(expression, Identifier):
            return expression.name in self.runtime_var_offsets
        if isinstance(expression, Call):
            return (expression.callee in self.user_functions
                    or any(self._contains_runtime_value(argument) for argument in expression.arguments))
        if isinstance(expression, Binary):
            return self._contains_runtime_value(expression.left) or self._contains_runtime_value(expression.right)
        if isinstance(expression, Unary):
            return self._contains_runtime_value(expression.operand)
        if isinstance(expression, Conditional):
            return (self._contains_runtime_value(expression.condition)
                    or self._contains_runtime_value(expression.if_true)
                    or self._contains_runtime_value(expression.if_false))
        return False

    def _is_bool_expression(self, expression):
        """Static guess at whether an expression produces only true/false."""
        if isinstance(expression, BoolLiteral):
            return True
        if isinstance(expression, Identifier):
            if expression.name in self.runtime_var_types:
                return self.runtime_var_types[expression.name] == 'bool'
            if expression.name in self.variables:
                return self._is_bool_expression(self.variables[expression.name])
            return False
        if isinstance(expression, Binary) and expression.operator in ('==', '!=', '<', '<=', '>', '>=', '&&', '||'):
            return True
        if isinstance(expression, Unary) and expression.operator == '!':
            return True
        if isinstance(expression, Call) and expression.callee in self.user_functions:
            return self._function_returns_bool(self.user_functions[expression.callee])
        if isinstance(expression, Conditional):
            return self._is_bool_expression(expression.if_true) and self._is_bool_expression(expression.if_false)
        return False

    def _classify_runtime_type(self, expression):
        """Best-effort type of a runtime value: 'bool', 'int', or 'unknown'."""
        if isinstance(expression, BoolLiteral):
            return 'bool'
        if isinstance(expression, IntLiteral):
            return 'int'
        if isinstance(expression, Identifier):
            if expression.name in self.runtime_var_types:
                return self.runtime_var_types[expression.name]
            if expression.name in self.variables:
                return self._classify_runtime_type(self.variables[expression.name])
            return 'unknown'
        if isinstance(expression, Unary):
            if expression.operator == '!':
                return 'bool'
            return self._classify_runtime_type(expression.operand)
        if isinstance(expression, Binary):
            if expression.operator in ('==', '!=', '<', '<=', '>', '>=', '&&', '||'):
                return 'bool'
            return 'int'
        if isinstance(expression, Conditional):
            if_true = self._classify_runtime_type(expression.if_true)
            if_false = self._classify_runtime_type(expression.if_false)
            if if_true == if_false:
                return if_true
            return 'unknown'
        if isinstance(expression, Call) and expression.callee in self.user_functions:
            return 'bool' if self._function_returns_bool(self.user_functions[expression.callee]) else 'unknown'
        return 'unknown'

    def _function_returns_bool(self, function):
        return self._statements_return_bool(function.body)

    def _statements_return_bool(self, statements):
        if not statements:
            return False
        return self._statement_returns_bool(statements[-1])

    def _statement_returns_bool(self, statement):
        if isinstance(statement, ExprStmt):
            return self._is_bool_expression(statement.expression)
        if isinstance(statement, ReturnStmt):
            return self._is_bool_expression(statement.expression)
        if isinstance(statement, IfStmt):
            then_bool = self._statements_return_bool(statement.then_branch)
            if statement.else_branch is None:
                return False
            if isinstance(statement.else_branch, IfStmt):
                else_bool = self._statement_returns_bool(statement.else_branch)
            else:
                else_bool = self._statements_return_bool(statement.else_branch)
            return then_bool and else_bool
        return False

    def _runtime_print(self, callee, argument, suffix):
        helper = '_serenity_print_bool' if self._is_bool_expression(argument) else '_serenity_print_int'
        lines = self._expression(argument)
        lines.append(f'    bl {helper}')
        if suffix:
            lines.extend(self._write_lines(suffix))
        return lines

    def _print_statement(self, expression):
        if len(expression.arguments) != 1:
            raise CompileError(f'{expression.callee} expects one argument')
        argument = expression.arguments[0]
        suffix = '\n' if expression.callee == 'println' else ''
        if self._contains_runtime_value(argument):
            return self._runtime_print(expression.callee, argument, suffix)
        constant = self._constant_value(argument)
        if isinstance(constant, str):
            if self._string_value(argument) is not None:
                return self._write_lines(constant + suffix)
            lines = self._string_expression(argument)
            lines.extend(['    mov x2, x1', '    mov x1, x0', '    mov x0, #1', '    bl _write'])
            if suffix:
                lines.extend(self._write_lines(suffix))
            return lines
        if constant is True or constant is False or constant is None:
            if self._is_runtime_comparison(argument):
                lines = self._runtime_comparison(argument)
                lines.append('    bl _serenity_print_bool')
                if suffix:
                    lines.extend(self._write_lines(suffix))
                return lines
            text = 'true' if constant is True else 'false' if constant is False else 'null'
            return self._write_lines(text + suffix)
        lines = self._expression(argument)
        lines.append('    bl _serenity_print_int')
        if suffix:
            lines.extend(self._write_lines(suffix))
        return lines

    def _write_lines(self, value):
        label, size = self._new_string(value)
        return [f'    adrp x1, {label}@PAGE', f'    add x1, x1, {label}@PAGEOFF', '    mov x0, #1', f'    mov x2, #{size}', '    bl _write']

    def _is_computed_string(self, expression):
        """True when an expression can only produce a string by running code
        (concatenation, string library calls, or non-literal initialisers)."""
        if isinstance(expression, StringLiteral):
            return False
        if isinstance(expression, Identifier):
            return expression.name in self.variables and self._is_computed_string(self.variables[expression.name])
        if isinstance(expression, Binary) and expression.operator == '+':
            return self._is_string_expression(expression.left) or self._is_string_expression(expression.right)
        if isinstance(expression, Call):
            return expression.callee in STRING_PRODUCING_FUNCTIONS
        if isinstance(expression, Conditional):
            return self._is_computed_string(expression.if_true) or self._is_computed_string(expression.if_false)
        return False

    def _is_string_expression(self, expression):
        if isinstance(expression, StringLiteral):
            return True
        if isinstance(expression, Identifier):
            return expression.name in self.variables and self._is_string_expression(self.variables[expression.name])
        if isinstance(expression, Binary) and expression.operator == '+':
            return self._is_string_expression(expression.left) or self._is_string_expression(expression.right)
        if isinstance(expression, Call):
            return expression.callee in STRING_PRODUCING_FUNCTIONS
        if isinstance(expression, Conditional):
            return self._is_string_expression(expression.if_true) or self._is_string_expression(expression.if_false)
        return False

    def _is_runtime_comparison(self, expression):
        return (isinstance(expression, Binary)
                and expression.operator in ('==', '!=', '<', '<=', '>', '>=')
                and (self._is_computed_string(expression.left) or self._is_computed_string(expression.right)))

    def _runtime_comparison(self, expression):
        lines = self._string_expression(expression.left)
        lines.append('    stp x0, x1, [sp, #-16]!')
        lines.extend(self._string_expression(expression.right))
        lines.extend(['    ldp x2, x3, [sp], #16', '    bl _serenity_str_cmp'])
        condition = {'==': 'eq', '!=': 'ne', '<': 'lt', '<=': 'le', '>': 'gt', '>=': 'ge'}[expression.operator]
        lines.extend([f'    cmp x0, #0', f'    cset w0, {condition}'])
        return lines

    def _string_expression(self, expression, validated=False):
        if isinstance(expression, StringLiteral):
            label, size = self._new_string(expression.value)
            return [f'    adrp x0, {label}@PAGE', f'    add x0, x0, {label}@PAGEOFF', f'    mov x1, #{size}']
        if isinstance(expression, Identifier):
            if expression.name not in self.variables:
                raise CompileError(f"undefined variable '{expression.name}'")
            return self._string_expression(self.variables[expression.name], validated=True)
        if isinstance(expression, Conditional):
            branch = expression.if_true if self._truthy(self._constant_value(expression.condition)) else expression.if_false
            return self._string_expression(branch, validated=True)
        if isinstance(expression, Binary) and expression.operator == '+':
            self._constant_value(expression)
            lines = self._string_expression(expression.left, validated=True)
            lines.append('    stp x0, x1, [sp, #-16]!')
            lines.extend(self._string_expression(expression.right, validated=True))
            lines.extend(['    ldp x2, x3, [sp], #16', '    bl _serenity_concat'])
            return lines
        if isinstance(expression, Call) and expression.callee in STRING_PRODUCING_FUNCTIONS:
            function, arity = STRING_PRODUCING_FUNCTIONS[expression.callee]
            if len(expression.arguments) != arity:
                raise CompileError(f'{expression.callee} expects {arity} argument(s), got {len(expression.arguments)}')
            self._constant_value(expression)
            helper = {'charAt': '_serenity_char_at', 'substring': '_serenity_substring',
                      'toUpper': '_serenity_to_upper', 'toLower': '_serenity_to_lower',
                      'trim': '_serenity_trim'}[expression.callee]
            lines = self._string_expression(expression.arguments[0], validated=True)
            if expression.callee == 'charAt':
                lines.append(f'    mov x2, #{self._constant_value(expression.arguments[1])}')
            elif expression.callee == 'substring':
                lines.append(f'    mov x2, #{self._constant_value(expression.arguments[1])}')
                lines.append(f'    mov x3, #{self._constant_value(expression.arguments[2])}')
            lines.append(f'    bl {helper}')
            return lines
        raise CompileError('string expression cannot be compiled at runtime')

    def _string_value(self, expression):
        """Resolve compile-time strings, including values introduced by `let`."""
        if isinstance(expression, StringLiteral):
            return expression.value
        if isinstance(expression, Identifier):
            if expression.name not in self.variables:
                raise CompileError(f"undefined variable '{expression.name}'")
            return self._string_value(self.variables[expression.name])
        return None

    @staticmethod
    def _truthy(value):
        return value is not False and value is not None and value != '' and value != 0

    def _constant_value(self, expression):
        """Evaluate the compile-time subset, used for typed printed values."""
        if isinstance(expression, (IntLiteral, StringLiteral, BoolLiteral)):
            return expression.value
        if isinstance(expression, NullLiteral):
            return None
        if isinstance(expression, Identifier):
            if expression.name in self.runtime_var_offsets:
                raise CompileError(f"variable '{expression.name}' holds a runtime value")
            if expression.name not in self.variables:
                raise CompileError(f"undefined variable '{expression.name}'")
            return self._constant_value(self.variables[expression.name])
        if isinstance(expression, Call):
            if expression.callee == 'eval':
                if len(expression.arguments) != 1:
                    raise CompileError('eval expects one argument')
                return self._constant_value(expression.arguments[0])
            builtin = ALL_BUILTIN_FUNCTIONS.get(expression.callee)
            if builtin is None:
                raise CompileError(f"unsupported call '{expression.callee}' in compiled expression")
            function, arity = builtin
            if len(expression.arguments) != arity:
                raise CompileError(f'{expression.callee} expects {arity} argument(s), got {len(expression.arguments)}')
            try:
                return function(*(self._constant_value(argument) for argument in expression.arguments))
            except OperationError as error:
                raise CompileError(str(error)) from None
        if isinstance(expression, Unary):
            value = self._constant_value(expression.operand)
            return -value if expression.operator == '-' else not self._truthy(value)
        if isinstance(expression, Conditional):
            if self._truthy(self._constant_value(expression.condition)):
                return self._constant_value(expression.if_true)
            return self._constant_value(expression.if_false)
        if isinstance(expression, Binary):
            left = self._constant_value(expression.left)
            if expression.operator == '&&':
                return self._truthy(left) and self._truthy(self._constant_value(expression.right))
            if expression.operator == '||':
                return self._truthy(left) or self._truthy(self._constant_value(expression.right))
            right = self._constant_value(expression.right)
            try:
                return apply_operator(expression.operator, left, right)
            except OperationError as error:
                raise CompileError(str(error)) from None
        raise CompileError('expression is not a compile-time value')

    def _expression(self, expression):
        if self._contains_runtime_value(expression):
            return self._compile_runtime_expression(expression)
        if isinstance(expression, IntLiteral):
            return [f'    mov x0, #{expression.value}']
        if isinstance(expression, BoolLiteral):
            return [f'    mov x0, #{1 if expression.value else 0}']
        if isinstance(expression, NullLiteral):
            raise CompileError('null cannot be used in a numeric expression')
        if isinstance(expression, Identifier):
            if expression.name in self.runtime_var_offsets:
                return [f'    ldr x0, [x29, #{self.runtime_var_offsets[expression.name]}]']
            if expression.name not in self.variables:
                raise CompileError(f"undefined variable '{expression.name}'")
            value = self.variables[expression.name]
            if self._string_value(value) is not None:
                raise CompileError(f"string variable '{expression.name}' cannot be used in a numeric expression")
            return self._expression(value)
        if isinstance(expression, Call):
            value = self._constant_value(expression)
            if isinstance(value, bool):
                return [f'    mov x0, #{1 if value else 0}']
            if isinstance(value, int) and not isinstance(value, bool):
                return [f'    mov x0, #{value}']
            raise CompileError(f"call '{expression.callee}' produces a non-numeric value")
        if isinstance(expression, Unary):
            if expression.operator == '-':
                return [*self._expression(expression.operand), '    neg x0, x0']
            value = self._constant_value(expression)
            return [f'    mov x0, #{1 if value else 0}']
        if isinstance(expression, Conditional):
            value = self._constant_value(expression)
            if isinstance(value, bool):
                return [f'    mov x0, #{1 if value else 0}']
            if value is None or isinstance(value, str):
                raise CompileError('non-numeric conditional cannot be used in a numeric expression')
            return [f'    mov x0, #{value}']
        if isinstance(expression, Binary):
            if expression.operator in ('==', '!=', '<', '<=', '>', '>=', '&&', '||', '^'):
                value = self._constant_value(expression)
                return [f'    mov x0, #{1 if value else 0}'] if isinstance(value, bool) else [f'    mov x0, #{value}']
            lines = self._expression(expression.left)
            lines.extend(['    str x0, [sp, #-16]!', *self._expression(expression.right), '    ldr x1, [sp], #16'])
            instruction = {'+': 'add x0, x1, x0', '-': 'sub x0, x1, x0', '*': 'mul x0, x1, x0', '/': 'sdiv x0, x1, x0'}.get(expression.operator)
            if expression.operator == '%':
                lines.extend(['    sdiv x2, x1, x0', '    msub x0, x2, x0, x1'])
                return lines
            if instruction is None:
                raise CompileError(f'unsupported operator {expression.operator!r}')
            lines.append(f'    {instruction}')
            return lines
        raise CompileError('compiled programs currently support integer eval expressions and string output')
