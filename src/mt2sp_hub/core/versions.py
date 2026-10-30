"""SemVer 2 precedence and a deliberately small dependency range language."""
from functools import total_ordering
import re

PATTERN = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?')


@total_ordering
class Version:
    def __init__(self, text):
        if not isinstance(text, str) or len(text) > 128:
            raise ValueError('Use a semantic version such as 1.2.3 or 1.2.3-beta.1.')
        match = PATTERN.fullmatch(text)
        if not match:
            raise ValueError('Invalid semantic version: %s' % text)
        self.text = text
        self.core = tuple(int(match[i]) for i in (1, 2, 3))
        self.pre = tuple((match[4] or '').split('.')) if match[4] else ()
        if any(part.isdigit() and len(part) > 1 and part.startswith('0') for part in self.pre):
            raise ValueError('Numeric prerelease identifiers cannot have leading zeroes.')

    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self.core == other.core and self.pre == other.pre

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        if self.core != other.core:
            return self.core < other.core
        if not self.pre or not other.pre:
            return bool(self.pre) and not other.pre
        for left, right in zip(self.pre, other.pre):
            if left == right:
                continue
            if left.isdigit() and right.isdigit():
                return int(left) < int(right)
            if left.isdigit() != right.isdigit():
                return left.isdigit()
            return left < right
        return len(self.pre) < len(other.pre)


def satisfies(version, expression):
    """Whitespace-separated exact/>,>=,<,<= comparators; no npm shorthand."""
    observed = Version(version)
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 256 or len(expression.split()) > 8:
        raise ValueError('Dependency ranges must be a nonempty comparator string.')
    for token in expression.split():
        match = re.fullmatch(r'(>=|<=|>|<|=)?(.+)', token)
        operator, requested = match[1] or '=', Version(match[2])
        if not {'=': observed == requested, '>': observed > requested, '>=': observed >= requested,
                '<': observed < requested, '<=': observed <= requested}[operator]:
            return False
    return True
