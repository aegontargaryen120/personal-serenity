from .ast_nodes import Program, Function, ExprStmt, LetStmt, IfStmt, WhileStmt, ForStmt, IncrementStmt, ReturnStmt, IntLiteral, StringLiteral, BoolLiteral, NullLiteral, Identifier, Binary, Unary, Conditional, Call
from .scanner import TokenType


class ParseError(SyntaxError):
    pass


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.current = 0

    def _peek(self):
        return self.tokens[self.current]

    def _previous(self):
        return self.tokens[self.current - 1]

    def _peek_next(self):
        return self.tokens[min(self.current + 1, len(self.tokens) - 1)]

    def _at_end(self):
        return self._peek().type == TokenType.EOF

    def _advance(self):
        if not self._at_end():
            self.current += 1
        return self._previous()

    def _check(self, *types):
        return self._peek().type in types

    def _match(self, *types):
        if self._check(*types):
            self._advance()
            return True
        return False

    def _consume(self, token_type, message):
        if self._check(token_type):
            return self._advance()
        token = self._peek()
        raise ParseError(f'{token.line}:{token.column}: {message}; found {token.lexeme!r}')

    def parse(self):
        functions = []
        while not self._at_end():
            functions.append(self._function())
        return Program(functions)

    def _function(self):
        self._consume(TokenType.FUNC, "expected 'func'")
        function_name = self._consume(TokenType.IDENTIFIER, 'expected function name').lexeme
        self._consume(TokenType.LPAREN, "expected '(' after function name")
        params = []
        if not self._check(TokenType.RPAREN):
            while True:
                params.append(self._consume(TokenType.IDENTIFIER, 'expected parameter name').lexeme)
                if not self._match(TokenType.COMMA):
                    break
        self._consume(TokenType.RPAREN, "expected ')' after parameters")
        self._consume(TokenType.ARROW, "expected '=>' after function signature")
        self._consume(TokenType.LPAREN, "expected '(' to start function body")
        body = self._statements_until(TokenType.RPAREN)
        self._advance()
        return Function(function_name, params, body)

    def _statements_until(self, terminator):
        body = []
        while not self._check(terminator):
            if self._at_end():
                raise ParseError('unexpected end of file in block')
            statement = self._statement()
            body.append(statement)
            if isinstance(statement, (IfStmt, WhileStmt, ForStmt)):
                self._match(TokenType.SEMICOLON)
            else:
                self._consume(TokenType.SEMICOLON, "expected ';' after statement")
        return body

    def _initializer_operator(self):
        if self._match(TokenType.EQUAL, TokenType.COLON_EQUAL):
            return
        token = self._peek()
        raise ParseError(f"{token.line}:{token.column}: expected '=' or ':=' after variable name; found {token.lexeme!r}")

    def _statement(self):
        if self._match(TokenType.LET):
            variable_name = self._consume(TokenType.IDENTIFIER, "expected variable name after 'let'").lexeme
            self._initializer_operator()
            return LetStmt(variable_name, self._expression())
        if self._match(TokenType.IF):
            return self._if_statement()
        if self._match(TokenType.WHILE):
            return self._while_statement()
        if self._match(TokenType.FOR):
            return self._for_statement()
        if self._check(TokenType.IDENTIFIER) and self._peek_next().type == TokenType.PLUS_PLUS:
            name = self._advance().lexeme
            self._advance()
            return IncrementStmt(name)
        if self._match(TokenType.RETURN):
            return ReturnStmt(self._expression())
        return ExprStmt(self._expression())

    def _block_after_arrow(self, description):
        self._consume(TokenType.ARROW, f"expected '=>' after {description}")
        self._consume(TokenType.LBRACE, "expected '{' to start block")
        body = self._statements_until(TokenType.RBRACE)
        self._advance()
        return body

    def _while_statement(self):
        self._consume(TokenType.LPAREN, "expected '(' after 'while'")
        condition = self._expression()
        self._consume(TokenType.RPAREN, "expected ')' after while condition")
        return WhileStmt(condition, self._block_after_arrow('while condition'))

    def _for_statement(self):
        self._consume(TokenType.LPAREN, "expected '(' after 'for'")
        self._consume(TokenType.LET, "expected 'let' declaration in for initializer")
        name = self._consume(TokenType.IDENTIFIER, "expected loop variable name").lexeme
        self._initializer_operator()
        initializer = LetStmt(name, self._expression())
        self._consume(TokenType.SEMICOLON, "expected ';' after for initializer")
        condition = self._expression()
        self._consume(TokenType.SEMICOLON, "expected ';' after for condition")
        increment_name = self._consume(TokenType.IDENTIFIER, "expected increment variable").lexeme
        self._consume(TokenType.PLUS_PLUS, "expected '++' in for increment")
        self._consume(TokenType.RPAREN, "expected ')' after for clauses")
        return ForStmt(initializer, condition, IncrementStmt(increment_name), self._block_after_arrow('for clauses'))

    def _if_statement(self):
        self._consume(TokenType.LPAREN, "expected '(' after 'if'")
        condition = self._expression()
        self._consume(TokenType.RPAREN, "expected ')' after if condition")
        self._consume(TokenType.ARROW, "expected '=>' after if condition")
        self._consume(TokenType.LBRACE, "expected '{' to start if branch")
        then_branch = self._statements_until(TokenType.RBRACE)
        self._advance()
        else_branch = None
        if self._match(TokenType.ELSE):
            if self._match(TokenType.IF):
                else_branch = self._if_statement()
            else:
                self._consume(TokenType.ARROW, "expected '=>' after 'else'")
                self._consume(TokenType.LBRACE, "expected '{' to start else branch")
                else_branch = self._statements_until(TokenType.RBRACE)
                self._advance()
        return IfStmt(condition, then_branch, else_branch)

    def _expression(self):
        expr = self._or()
        if self._match(TokenType.QUESTION):
            if_true = self._expression()
            self._consume(TokenType.COLON, "expected ':' in conditional expression")
            return Conditional(expr, if_true, self._expression())
        return expr

    def _or(self):
        expr = self._and()
        while self._match(TokenType.OR_OR):
            expr = Binary(expr, self._previous().lexeme, self._and())
        return expr

    def _and(self):
        expr = self._equality()
        while self._match(TokenType.AND_AND):
            expr = Binary(expr, self._previous().lexeme, self._equality())
        return expr

    def _equality(self):
        expr = self._comparison()
        while self._match(TokenType.EQUAL_EQUAL, TokenType.BANG_EQUAL):
            expr = Binary(expr, self._previous().lexeme, self._comparison())
        return expr

    def _comparison(self):
        expr = self._addition()
        while self._match(TokenType.LESS, TokenType.LESS_EQUAL, TokenType.GREATER, TokenType.GREATER_EQUAL):
            expr = Binary(expr, self._previous().lexeme, self._addition())
        return expr

    def _addition(self):
        expr = self._multiplication()
        while self._match(TokenType.PLUS, TokenType.MINUS):
            expr = Binary(expr, self._previous().lexeme, self._multiplication())
        return expr

    def _multiplication(self):
        expr = self._power()
        while self._match(TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            expr = Binary(expr, self._previous().lexeme, self._power())
        return expr

    def _power(self):
        expr = self._unary()
        if self._match(TokenType.CARET):
            expr = Binary(expr, '^', self._power())
        return expr

    def _unary(self):
        if self._match(TokenType.MINUS, TokenType.BANG):
            return Unary(self._previous().lexeme, self._unary())
        return self._primary()

    def _primary(self):
        if self._match(TokenType.INT):
            return IntLiteral(int(self._previous().lexeme))
        if self._match(TokenType.STRING):
            return StringLiteral(self._previous().lexeme)
        if self._match(TokenType.TRUE):
            return BoolLiteral(True)
        if self._match(TokenType.FALSE):
            return BoolLiteral(False)
        if self._match(TokenType.NULL):
            return NullLiteral()
        if self._match(TokenType.IDENTIFIER):
            name = self._previous().lexeme
            if self._match(TokenType.LPAREN):
                args = []
                if not self._check(TokenType.RPAREN):
                    while True:
                        args.append(self._expression())
                        if not self._match(TokenType.COMMA):
                            break
                self._consume(TokenType.RPAREN, "expected ')' after arguments")
                return Call(name, args)
            return Identifier(name)
        if self._match(TokenType.LPAREN):
            expr = self._expression()
            self._consume(TokenType.RPAREN, "expected ')' after expression")
            return expr
        token = self._peek()
        raise ParseError(f'{token.line}:{token.column}: expected expression')
