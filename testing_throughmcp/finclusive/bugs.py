"""Seeded bugs for measuring how good a test suite is.

Each bug is a small, realistic mistake in one business rule from
FinClusive_Original_Scenario.md. A bug is switched on with the environment
variable ``FINCLUSIVE_BUG=<name>`` (or ``create_app(bug=...)``). A test suite
"catches" a bug when at least one of its tests fails with that bug on and
passes without it. This works like mutation testing, but with mutants a
person chose to look like real defects.
"""

BUGS: dict[str, str] = {
    "points_round_half_up": "Base points use round() instead of rounding down (₹150 -> 2 points).",
    "full_bonus_on_minimum": "The +500 full-payment bonus is also given when paying only the minimum due.",
    "early_bonus_strict": "Early-payment bonus needs 6+ days before the due date instead of 5+.",
    "otp_threshold_50k": "OTP is only asked for payments above ₹50,000 instead of above ₹10,000.",
    "min_payment_99": "A ₹99 payment is accepted (minimum should be ₹100).",
    "max_payment_unchecked": "The ₹5,00,000 single-payment maximum is not enforced.",
    "daily_limit_unchecked": "The ₹10,00,000 daily limit across all cards is not enforced.",
    "duplicate_not_blocked": "The same amount to the same card within 5 minutes is not blocked.",
    "luhn_unchecked": "Card numbers are not Luhn-checked.",
    "expired_card_accepted": "Cards with an expiry date in the past are accepted.",
    "sixth_card_allowed": "A user can add a 6th card (limit is 5).",
    "silver_from_1001": "Silver tier starts at 1001 points instead of 1000.",
    "redeem_below_minimum": "Fewer than 500 points can be redeemed.",
    "redeem_rate_10": "Redemption pays ₹1 per 10 points instead of per 100.",
    "three_decimal_amounts": "Amounts with 3 decimal places are accepted.",
    "weak_password_accepted": "Passwords without a special character are accepted.",
}


def check(name: str | None) -> str | None:
    if name and name not in BUGS:
        raise ValueError(f"Unknown bug {name!r}. Known bugs: {', '.join(sorted(BUGS))}")
    return name or None
