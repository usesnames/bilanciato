"""Italian financial number parsing.

Italian accounting documents format numbers as ``1.234.567,89`` where ``.`` is the
thousands separator and ``,`` is the decimal separator. Negative values may appear
as ``-1.234,00`` or wrapped in parentheses ``(1.234,00)``.

No financial value is ever altered here: parsing only changes the *representation*
(string -> Decimal), never the magnitude.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Matches an Italian-formatted monetary amount, optionally signed/parenthesised.
# Examples: 1.234.567,89 | -2.983.581,00 | (1.000,00) | 0,00 | 31.001.183,11
_EURO_RE = re.compile(
    r"""
    ^\s*
    (?P<paren>\()?            # optional opening parenthesis (negative)
    \s*
    (?P<sign>[-+])?           # optional explicit sign
    \s*
    (?P<int>\d{1,3}(?:\.\d{3})*|\d+)   # integer part with dot thousands separators
    (?:,(?P<dec>\d+))?        # optional comma decimals
    \s*
    \)?                        # optional closing parenthesis
    \s*$
    """,
    re.VERBOSE,
)


def is_euro(text: str | None) -> bool:
    """True if ``text`` looks like a parseable Italian monetary amount."""
    if text is None:
        return False
    return _EURO_RE.match(text.strip()) is not None


def parse_euro(text: str | None) -> Decimal | None:
    """Parse an Italian-formatted monetary string to :class:`Decimal`.

    Returns ``None`` for empty/non-numeric input so callers can distinguish a
    blank cell from a genuine ``0,00``.
    """
    if text is None:
        return None
    raw = text.strip()
    if not raw:
        return None

    m = _EURO_RE.match(raw)
    if not m:
        return None

    integer = m.group("int").replace(".", "")
    decimals = m.group("dec") or "0"
    negative = bool(m.group("paren")) or m.group("sign") == "-"

    try:
        value = Decimal(f"{integer}.{decimals}")
    except InvalidOperation:
        return None

    return -value if negative else value
