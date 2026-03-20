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
]


def _build_code_pattern(code: str) -> str:
    """Build regex for A-code allowing optional spaces and phone-glued cases.

    Examples for code "A1":
      - "A1 170"       → matches (followed by space)
      - "A 1"          → matches (space between A and 1)
      - "A10972643331" → matches (followed by phone 0ddd...)
      - "A11", "A10"   → no match (followed by digit, not phone-length)
      - "BA1"          → no match (preceded by word char)
    """
    chars = [re.escape(c) for c in code]
    code_pat = r"\s*".join(chars)
    return rf"(?<!\w){code_pat}(?=\s|[^a-zA-Z0-9]|0\d{{8,}}|$)"


def extract_note_prices(
    text: str,
    price_code_mapping: dict[str, int | None] | None = None,
) -> list[int]:
    """Extract price tokens (in thousands) from note text.

    Args:
        text: The order note text.
        price_code_mapping: Optional mapping of A1-A9 codes to prices (in thousands).

    Returns:
        List of unique price values in thousands (e.g. 185 means 185,000 VND).
    """
    if not text:
        return []

    working_text = text

    # Step 1: Replace A1-A9 codes with their mapped price values
    # Pad replacement with spaces to avoid digit concatenation (e.g. "A10972..." → " 170 0972...")
    if price_code_mapping:
        for code, price in price_code_mapping.items():
            if price is not None:
                pattern = _build_code_pattern(code)
                working_text = re.sub(
                    pattern,
                    f" {price} ",
                    working_text,
                    flags=re.IGNORECASE,
                )

    # Step 2: Remove phone numbers before extraction
    for phone_re in _PHONE_PATTERNS:
        working_text = phone_re.sub("", working_text)

    # Step 3: Extract price tokens (deduplicated, order-preserving)
    tokens: list[int] = []
    seen: set[int] = set()
    for match in _PRICE_TOKEN_RE.finditer(working_text):
        raw_digits = match.group(1)
        value = int(raw_digits)
        # Normalize: if value >= 1000 (e.g. "185000" from "185.000"), divide
        if value >= 1000:
            value = value // 1000
        if value > 0 and value not in seen:
            tokens.append(value)
            seen.add(value)

    return tokens
