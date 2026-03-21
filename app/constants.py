from __future__ import annotations

# Tag labels (displayed on the web UI)
TAG_0 = "0"          # Low delivery rate (< 60%) — skip processing
TAG_1 = "1"          # Have address + full match for 1-3 products
TAG_1_1 = "1.1"      # Have address + full match for 4+ products
TAG_1_2 = "1.2"      # Have address + note/product mismatch
TAG_1_3 = "1.3"      # Have address + no products in order list
TAG_1_4 = "1.4"      # Have address + any product has Tồn dự báo <= 0
TAG_2 = "2"          # No address + full match for 1-3 products
TAG_2_1 = "2.1"      # No address + full match for 4+ products
TAG_2_2 = "2.2"      # No address + note/product mismatch
TAG_2_3 = "2.3"      # No address + no products in order list
TAG_2_4 = "2.4"      # No address + any product has Tồn dự báo <= 0
ERR = "ERR"          # Error during processing
LOW_DELIVERY_RATE = "LOW_DELIVERY_RATE"  # Delivery rate < threshold -> TAG 0

# Internal status names (used in code/CSV)
HAVE_ADDR_LOW_SP = "HAVE_ADDR_LOW_SP"    # Have address + full match for ≤3 products -> TAG 1
HAVE_ADDR_HIGH_SP = "HAVE_ADDR_HIGH_SP"  # Have address + full match for 4+ products -> TAG 1.1
HAVE_ADDR_NO_SP = "HAVE_ADDR_NO_SP"      # Have address + note/product mismatch -> TAG 1.2
HAVE_ADDR_NO_PROD = "HAVE_ADDR_NO_PROD"  # Have address + no products in list -> TAG 1.3
HAVE_ADDR_OOS = "HAVE_ADDR_OOS"          # Have address + out of stock -> TAG 1.4
NO_ADDR_LOW_SP = "NO_ADDR_LOW_SP"        # No address + full match for ≤3 products -> TAG 2
NO_ADDR_HIGH_SP = "NO_ADDR_HIGH_SP"      # No address + full match for 4+ products -> TAG 2.1
NO_ADDR_NO_SP = "NO_ADDR_NO_SP"          # No address + note/product mismatch -> TAG 2.2
NO_ADDR_NO_PROD = "NO_ADDR_NO_PROD"      # No address + no products in list -> TAG 2.3
NO_ADDR_OOS = "NO_ADDR_OOS"              # No address + out of stock -> TAG 2.4

# Mapping: internal status -> web tag label
STATUS_TO_TAG = {
    HAVE_ADDR_LOW_SP: TAG_1,
    HAVE_ADDR_HIGH_SP: TAG_1_1,
    HAVE_ADDR_NO_SP: TAG_1_2,
    HAVE_ADDR_NO_PROD: TAG_1_3,
    HAVE_ADDR_OOS: TAG_1_4,
    NO_ADDR_LOW_SP: TAG_2,
    NO_ADDR_HIGH_SP: TAG_2_1,
    NO_ADDR_NO_SP: TAG_2_2,
    NO_ADDR_NO_PROD: TAG_2_3,
    NO_ADDR_OOS: TAG_2_4,
}

# Tags that indicate "manual review needed" — orders with these tags get re-checked on next run
RECHECK_TAGS = {TAG_1_2, TAG_2_2}

# Tags that indicate "tag only, no action" — orders with these tags are skipped for messaging
# NOTE: TAG_2_3 and TAG_2_4 are NOT included here because they still need MESS 1 (ask address)
TAG_ONLY_TAGS = {TAG_1_3, TAG_1_4}

# All valid tag values
ORDER_TAG_VALUES = (TAG_0, TAG_1, TAG_1_1, TAG_1_2, TAG_1_3, TAG_1_4, TAG_2, TAG_2_1, TAG_2_2, TAG_2_3, TAG_2_4, ERR)
