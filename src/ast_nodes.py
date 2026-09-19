from dataclasses import dataclass


@dataclass
class Program:
    functions: list


@dataclass
class Function:
    name: str
    params: list
    body: list


@dataclass
class ExprStmt:
    expression: object


@dataclass
class LetStmt:
    name: str
    initializer: object


@dataclass
class AssignStmt:
    name: str
    value: object


@dataclass
class IfStmt:
    condition: object
    then_branch: list
    else_branch: object  # None, a list of statements, or another IfStmt


@dataclass
class WhileStmt:
    condition: object
    body: list


@dataclass
class ForStmt:
    initializer: LetStmt
    condition: object
    increment: object
    body: list


@dataclass
class IncrementStmt:
    name: str


@dataclass
class ReturnStmt:
    expression: object


@dataclass
class IntLiteral:
    value: int


@dataclass
class StringLiteral:
    value: str


@dataclass
class BoolLiteral:
    value: bool


@dataclass
class NullLiteral:
    pass


@dataclass
class Identifier:
    name: str


@dataclass
class Binary:
    left: object
    operator: str
    right: object


@dataclass
class Unary:
    operator: str
    operand: object


@dataclass
class Conditional:
    condition: object
    if_true: object
    if_false: object


@dataclass
class Call:
    callee: str
    arguments: list


@dataclass
class MethodCall:
    receiver: str
    method: str
    arguments: list


@dataclass
class ListLiteral:
    elements: list
