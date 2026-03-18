from __future__ import annotations

# Shared status/tag constants used for CSV export and order processing decisions.
NEW = "NEW"
COC = "4+ SP"                  # Have address + 4+ products matched
CHECK = "≤3 SP"                # Have address + 1-3 products matched
NO_ADDR = "OK SP (NO_ADDR)"   # No address + ≥1 product matched -> send ask address msg
TODO_ADDR = "? SP"             # Have address + 0 matched -> manual review
TODO_NO_ADDR = "? SP (NO_ADDR)"  # No address + 0 matched -> manual review
ERR = "ERR"                    # Error during processing

ORDER_STATUS_VALUES = (NEW, COC, CHECK, NO_ADDR, TODO_ADDR, TODO_NO_ADDR, ERR)
