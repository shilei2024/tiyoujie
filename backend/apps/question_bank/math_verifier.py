"""Bounded rational arithmetic and one-variable linear equations; never executes input."""

import re
from dataclasses import asdict, dataclass
from fractions import Fraction

VERSION = "rational-linear-v1"
SCOPE = "仅核验结构化算式/一元一次方程及选项，不证明题干、建模或解析正确。"
TOKEN = re.compile(r"\s*([0-9]+(?:\.[0-9]+)?|[x()+*/-])")


class Unsupported(ValueError):
    pass


def bounded(value):
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > 256:
        raise ValueError("number_limit")
    return value


class Parser:
    def __init__(self, text, variable=False):
        if not isinstance(text, str) or not text.strip() or len(text) > 160:
            raise ValueError("expression_limit")
        self.tokens = []
        position = 0
        text = text.strip()
        while position < len(text):
            match = TOKEN.match(text, position)
            if not match:
                raise Unsupported("syntax_not_supported")
            token = match[1]
            if len(token) > 16 or len(self.tokens) >= 64:
                raise ValueError("token_limit")
            self.tokens.append(token)
            position = match.end()
        self.i, self.variable = 0, variable

    def take(self, token):
        if self.i < len(self.tokens) and self.tokens[self.i] == token:
            self.i += 1
            return True
        return False

    def parse(self):
        result = self.expression(0)
        if self.i != len(self.tokens):
            raise Unsupported("syntax_not_supported")
        return result

    def expression(self, depth):
        left = self.term(depth + 1)
        while self.i < len(self.tokens) and self.tokens[self.i] in ("+", "-"):
            sign = 1 if self.take("+") else -1
            if sign == -1:
                self.take("-")
            right = self.term(depth + 1)
            left = tuple(bounded(a + sign * b) for a, b in zip(left, right, strict=True))
        return left

    def term(self, depth):
        left = self.atom(depth + 1)
        while self.i < len(self.tokens) and self.tokens[self.i] in ("*", "/"):
            multiply = self.take("*")
            if not multiply:
                self.take("/")
            right = self.atom(depth + 1)
            a, b = left
            c, d = right
            if multiply:
                if a and c:
                    raise Unsupported("nonlinear")
                left = (bounded(a * d + b * c), bounded(b * d))
            else:
                if c:
                    raise Unsupported("variable_denominator")
                left = (bounded(a / d), bounded(b / d))
        return left

    def atom(self, depth):
        if depth > 16:
            raise ValueError("depth_limit")
        if self.take("+"):
            return self.atom(depth + 1)
        if self.take("-"):
            return tuple(-v for v in self.atom(depth + 1))
        if self.take("("):
            value = self.expression(depth + 1)
            if not self.take(")"):
                raise ValueError("missing_parenthesis")
            return value
        if self.i >= len(self.tokens):
            raise ValueError("missing_operand")
        token = self.tokens[self.i]
        self.i += 1
        if token == "x" and self.variable:
            return Fraction(1), Fraction(0)
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", token):
            raise Unsupported("operand_not_supported")
        return Fraction(0), bounded(Fraction(token))


def number(text):
    return Parser(text).parse()[1]


@dataclass(frozen=True)
class Result:
    result: str
    code: str
    method: str = VERSION
    scope: str = SCOPE

    def payload(self):
        return asdict(self)


def verify(spec, answer):
    try:
        if not isinstance(spec, dict) or not isinstance(answer, str):
            raise ValueError("invalid_spec")
        kind = spec.get("kind")
        expected_fields = {
            "arithmetic": {"kind", "expression"},
            "linear_equation": {"kind", "left", "right"},
            "choice_arithmetic": {"kind", "expression", "options"},
        }
        if kind not in expected_fields:
            return Result("not_supported", "type_not_supported")
        if len(answer) > 160:
            raise ValueError("answer_limit")
        if set(spec) != expected_fields[kind]:
            raise ValueError("invalid_fields")
        if kind == "linear_equation":
            a, b = Parser(spec["left"], variable=True).parse()
            c, d = Parser(spec["right"], variable=True).parse()
            if a == c:
                correct = answer == ("all_real" if b == d else "no_solution")
            else:
                correct = number(answer) == bounded((d - b) / (a - c))
        elif kind == "arithmetic":
            correct = number(spec["expression"]) == number(answer)
        else:
            options = spec["options"]
            if not isinstance(options, list) or not 2 <= len(options) <= 6:
                raise ValueError("invalid_options")
            values = [number(option) for option in options]
            target = number(spec["expression"])
            if len(set(values)) != len(values) or values.count(target) != 1:
                return Result("incorrect", "choice_not_unique")
            correct = answer == "ABCDEF"[values.index(target)]
        return Result(
            "correct" if correct else "incorrect", "exact_match" if correct else "mismatch"
        )
    except Unsupported as exc:
        return Result("not_supported", str(exc))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError, RecursionError):
        return Result("invalid", "invalid_or_out_of_bounds")
