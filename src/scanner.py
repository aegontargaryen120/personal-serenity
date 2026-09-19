#!/usr/bin/env python3

from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    FUNC = auto()
    LET = auto()
    TRUE = auto()
    FALSE = auto()
    NULL = auto()
    IDENTIFIER = auto()
    INT = auto()
    STRING = auto()
    LPAREN = auto()
    RPAREN = auto()
    COMMA = auto()
    SEMICOLON = auto()
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    PERCENT = auto()
    CARET = auto()
    BANG = auto()
    BANG_EQUAL = auto()
    EQUAL_EQUAL = auto()
    LESS = auto()
    LESS_EQUAL = auto()
    GREATER = auto()
    GREATER_EQUAL = auto()
    AND_AND = auto()
    OR_OR = auto()
    LBRACE = auto()
    RBRACE = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    QUESTION = auto()
    COLON = auto()
    EQUAL = auto()
    IF = auto()
    ELSE = auto()
    WHILE = auto()
    FOR = auto()
    PLUS_PLUS = auto()
    ARROW = auto()
    COLON_EQUAL = auto()
    RETURN = auto()
    EOF = auto()
    DOT = auto()


@dataclass(frozen=True)
class Token:
    type: TokenType
    lexeme: str
    line: int
    column: int


class ScanError(SyntaxError):
    pass


class Scanner:
    """Turn Serenity source text into tokens."""

    _single_character = {
        '(': TokenType.LPAREN, ')': TokenType.RPAREN, ',': TokenType.COMMA,
        ';': TokenType.SEMICOLON, '+': TokenType.PLUS, '-': TokenType.MINUS,
        '*': TokenType.STAR, '/': TokenType.SLASH, '%': TokenType.PERCENT,
        '^': TokenType.CARET, '{': TokenType.LBRACE, '}': TokenType.RBRACE,
        '[': TokenType.LBRACKET, ']': TokenType.RBRACKET,
        '?': TokenType.QUESTION, ':': TokenType.COLON, '=': TokenType.EQUAL,
        '.': TokenType.DOT,
    }

    def __init__(self, source, filename='<source>'):
        self.source = source.read() if hasattr(source, 'read') else source
        self.filename = filename
        self.current = 0
        self.line = 1
        self.column = 1
        self.tokens = []

    def _at_end(self):
        return self.current >= len(self.source)

    def _advance(self):
        char = self.source[self.current]
        self.current += 1
        self.column += 1
        return char

    def _peek(self):
        return '\0' if self._at_end() else self.source[self.current]

    def _add(self, token_type, lexeme, line, column):
        self.tokens.append(Token(token_type, lexeme, line, column))

    def _string(self, line, column):
        value = []
        while not self._at_end() and self._peek() != '"':
            char = self._advance()
            if char == '\\':
                if self._at_end():
                    break
                escaped = self._advance()
                value.append({'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}.get(escaped, escaped))
            else:
                if char == '\n':
                    self.line += 1
                    self.column = 1
                value.append(char)
        if self._at_end():
            raise ScanError(f'{self.filename}:{line}:{column}: unterminated string')
        self._advance()  # closing quote
        self._add(TokenType.STRING, ''.join(value), line, column)

    def _number(self, first, line, column):
        value = [first]
        while self._peek().isdigit():
            value.append(self._advance())
        self._add(TokenType.INT, ''.join(value), line, column)

    def _identifier(self, first, line, column):
        value = [first]
        while self._peek().isalnum() or self._peek() == '_':
            value.append(self._advance())
        text = ''.join(value)
        token_type = {
            'func': TokenType.FUNC, 'let': TokenType.LET, 'true': TokenType.TRUE,
            'false': TokenType.FALSE, 'null': TokenType.NULL,
            'if': TokenType.IF, 'else': TokenType.ELSE,
            'while': TokenType.WHILE, 'for': TokenType.FOR,
            'return': TokenType.RETURN,
        }.get(text, TokenType.IDENTIFIER)
        self._add(token_type, text, line, column)

    def scan_tokens(self):
        while not self._at_end():
            line, column = self.line, self.column
            char = self._advance()
            if char in ' \t\r':
                continue
            if char == '\n':
                self.line += 1
                self.column = 1
                continue
            if char == '/' and self._peek() == '/':
                while not self._at_end() and self._peek() != '\n':
                    self._advance()
                continue
            if char == '/' and self._peek() == '*':
                self._advance()
                while not self._at_end() and not (self._peek() == '*' and self.current + 1 < len(self.source) and self.source[self.current + 1] == '/'):
                    if self._advance() == '\n':
                        self.line += 1
                        self.column = 1
                if self._at_end():
                    raise ScanError(f'{self.filename}:{line}:{column}: unterminated block comment')
                self._advance()
                self._advance()
                continue
            if char == '=' and self._peek() == '>':
                self._advance()
                self._add(TokenType.ARROW, '=>', line, column)
            elif char == '+' and self._peek() == '+':
                self._advance()
                self._add(TokenType.PLUS_PLUS, '++', line, column)
            elif char == '=' and self._peek() == '=':
                self._advance()
                self._add(TokenType.EQUAL_EQUAL, '==', line, column)
            elif char == '!' and self._peek() == '=':
                self._advance()
                self._add(TokenType.BANG_EQUAL, '!=', line, column)
            elif char == '<' and self._peek() == '=':
                self._advance()
                self._add(TokenType.LESS_EQUAL, '<=', line, column)
            elif char == '>' and self._peek() == '=':
                self._advance()
                self._add(TokenType.GREATER_EQUAL, '>=', line, column)
            elif char == '&' and self._peek() == '&':
                self._advance()
                self._add(TokenType.AND_AND, '&&', line, column)
            elif char == '|' and self._peek() == '|':
                self._advance()
                self._add(TokenType.OR_OR, '||', line, column)
            elif char == ':' and self._peek() == '=':
                self._advance()
                self._add(TokenType.COLON_EQUAL, ':=', line, column)
            elif char == '"':
                self._string(line, column)
            elif char.isdigit():
                self._number(char, line, column)
            elif char.isalpha() or char == '_':
                self._identifier(char, line, column)
            elif char in self._single_character:
                self._add(self._single_character[char], char, line, column)
            elif char == '!':
                self._add(TokenType.BANG, char, line, column)
            elif char == '<':
                self._add(TokenType.LESS, char, line, column)
            elif char == '>':
                self._add(TokenType.GREATER, char, line, column)
            else:
                raise ScanError(f'{self.filename}:{line}:{column}: unexpected character {char!r}')
        self.tokens.append(Token(TokenType.EOF, '', self.line, self.column))
        return self.tokens
