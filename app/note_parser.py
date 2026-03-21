"""Extract price tokens from order note text.

Handles various Vietnamese ecommerce note patterns:
- Plain numbers: "185", "133"
- With 'k' suffix: "185k"
- With trailing text: "185da"
- Mixed with phone numbers: "185 0968796393" (phone excluded)
- With separators: "185/0968796393", "185+0379549302"
- With A1-A9 product code aliases mapped to prices
- Dotted/spaced phone numbers: "0918.677.633", "0947 729 097"
- Time patterns excluded: "7h30" not treated as prices
- Weight patterns excluded: "49kg" not treated as prices
- A-code priority: A-code on same line as explicit price → A-code wins
- Two-price ambiguity: 2+ prices on one line (no A-code) → extract nothing
"""
from __future__ import annotations

import re

# Match a price-like token in note text.
# Captures a 2-4 digit number, excludes time (7h30) and weight (49kg) patterns.
_PRICE_TOKEN_RE = re.compile(
    r"(?<![hH\d])"       # not preceded by digit or 'h' (excludes time like 7h30)
    r"(\d{2,4})"          # 2-4 digit number (the price in thousands)
    r"(?![kK][gG])"       # not followed by 'kg' (excludes weight)
    r"(?:[.,]\d{3})*"    # optional .000 or ,000 groups (e.g. 185.000)
    r"[kK]?"              # optional 'k' suffix
    r"(?!\d)"             # not followed by digit
)

# Phone patterns to remove before price extraction
_PHONE_PATTERNS = [
    re.compile(r"(?<![.\d])0\d{9,}"),                          # standard: 0968796393
    re.compile(r"(?<![.\d])0\d{2,3}[.\-]\d{3}[.\-]\d{3,4}"),  # dotted:   0918.677.633
    re.compile(r"(?<![.\d])0\d{2,3}\s+\d{3}\s+\d{3}"),        # spaced:   0947 729 097
    re.compile(r"\.\s*0\d{9,}"),                               # after-dot: 185.0328019689
]


def _build_code_pattern(code: str) -> str:
    """Build regex for A-code allowing optional spaces and various suffixes.

    Examples for code "A1":
      - "A1 170"       → matches (followed by space)
      - "A 1"          → matches (space between A and 1)
      - "A10972643331" → matches (followed by phone 0ddd...)
      - "A185"         → matches (followed by 2+ digit price)
      - "A117"         → matches (followed by 2+ digit price)
      - "A11", "A10"   → no match (followed by single digit, not valid)
      - "BA1"          → no match (preceded by word char)
    """
    chars = [re.escape(c) for c in code]
    code_pat = r"\s*".join(chars)
    return rf"(?<!\w){code_pat}(?=\s|[^a-zA-Z0-9]|0\d{{8,}}|[1-9]\d{{1,3}}(?!\d)|$)"


def _find_a_code_price(line: str, mapping: dict[str, int | None] | None) -> int | None:
    """Check if line contains an A-code and return its mapped price.

    When an A-code is detected on a line, its mapped price takes priority
    over any explicit prices on the same line.
    """
    if not mapping:
        return None
    for code, price in mapping.items():
        if price is None:
            continue
        pattern = _build_code_pattern(code)
        if re.search(pattern, line, re.IGNORECASE):
            return price
    return None


def extract_note_prices(
    text: str,
    price_code_mapping: dict[str, int | None] | None = None,
) -> list[int]:
    """Extract one price per line from note text (1 line = 1 product).

    Rules:
    - If a line contains an A-code, use the A-code's mapped price (ignore other prices)
    - If a line has exactly 1 price (no A-code), extract that price
    - If a line has 0 or 2+ prices (no A-code), extract nothing (ambiguous)

    Args:
        text: The order note text.
        price_code_mapping: Optional mapping of A1-A9 codes to prices (in thousands).

    Returns:
        List of price values in thousands (e.g. 185 means 185,000 VND).
        One price per line — each line represents one product checkout.
    """
    if not text:
        return []

    tokens: list[int] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Step 1: Check for A-code — A-code wins over any explicit prices
        a_code_price = _find_a_code_price(line, price_code_mapping)
        if a_code_price is not None:
            tokens.append(a_code_price)
            continue

        # Step 2: Remove phone numbers from the line
        clean_line = line
        for phone_re in _PHONE_PATTERNS:
            clean_line = phone_re.sub("", clean_line)

        # Step 3: Find all price tokens on this line
        matches = list(_PRICE_TOKEN_RE.finditer(clean_line))
        if len(matches) == 1:
            raw_digits = matches[0].group(1)
            value = int(raw_digits)
            if value > 0:
                tokens.append(value)
        # If 0 or 2+ matches → skip line (ambiguous or no price)

    return tokens
