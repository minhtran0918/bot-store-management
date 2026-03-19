from __future__ import annotations

# Tag labels (displayed on the web UI)
TAG_1 = "1"          # Have address + 1-3 products matched
TAG_1_1 = "1.1"      # Have address + 4+ products matched
TAG_1_2 = "1.2"      # Have address + 0 matched product (manual review)
TAG_2 = "2"          # No address + 1-3 products matched
TAG_2_1 = "2.1"      # No address + 4+ products matched
TAG_2_2 = "2.2"      # No address + 0 matched product (manual review)
ERR = "ERR"          # Error during processing

# Internal status names (used in code/CSV)
HAVE_ADDR_LOW_SP = "HAVE_ADDR_LOW_SP"    # Have address + ≤3 matched -> TAG 1
HAVE_ADDR_HIGH_SP = "HAVE_ADDR_HIGH_SP"  # Have address + 4+ matched -> TAG 1.1
HAVE_ADDR_NO_SP = "HAVE_ADDR_NO_SP"      # Have address + 0 matched -> TAG 1.2
NO_ADDR_LOW_SP = "NO_ADDR_LOW_SP"        # No address + ≤3 matched -> TAG 2
NO_ADDR_HIGH_SP = "NO_ADDR_HIGH_SP"      # No address + 4+ matched -> TAG 2.1
NO_ADDR_NO_SP = "NO_ADDR_NO_SP"          # No address + 0 matched -> TAG 2.2

# Mapping: internal status -> web tag label
STATUS_TO_TAG = {
    HAVE_ADDR_LOW_SP: TAG_1,
    HAVE_ADDR_HIGH_SP: TAG_1_1,
    HAVE_ADDR_NO_SP: TAG_1_2,
    NO_ADDR_LOW_SP: TAG_2,
    NO_ADDR_HIGH_SP: TAG_2_1,
    NO_ADDR_NO_SP: TAG_2_2,
}

# Tags that indicate "manual review needed" — orders with these tags get re-checked on next run
RECHECK_TAGS = {TAG_1_2, TAG_2_2}

# All valid tag values
ORDER_TAG_VALUES = (TAG_1, TAG_1_1, TAG_1_2, TAG_2, TAG_2_1, TAG_2_2, ERR)
