"""FinClusive business rules as pure functions.

Every rule here comes from spec/FinClusive_Scenario.md.
``bug`` is the name of the seeded bug that is switched on (see bugs.py), or None.
"""

import re
from datetime import date
from decimal import Decimal

MIN_PAYMENT = Decimal("100")
MAX_PAYMENT = Decimal("500000")
DAILY_LIMIT = Decimal("1000000")
OTP_THRESHOLD = Decimal("10000")
FULL_PAYMENT_BONUS = 500
EARLY_PAYMENT_BONUS = 200
EARLY_PAYMENT_DAYS = 5
MAX_CARDS = 5
MIN_REDEMPTION = 500
POINTS_PER_RUPEE_REDEEMED = 100
DUPLICATE_WINDOW_SECONDS = 5 * 60


class RuleError(ValueError):
    """A business-rule violation, reported to the client as HTTP 422."""


def validate_amount(amount: Decimal, bug: str | None = None) -> None:
    if amount != amount.quantize(Decimal("0.01")) and bug != "three_decimal_amounts":
        raise RuleError("Amount can have at most 2 decimal places")
    minimum = Decimal("99") if bug == "min_payment_99" else MIN_PAYMENT
    if amount < minimum:
        raise RuleError("Minimum payment amount is 100")
    if amount > MAX_PAYMENT and bug != "max_payment_unchecked":
        raise RuleError("Maximum single payment amount is 500000")


def otp_required(amount: Decimal, bug: str | None = None) -> bool:
    threshold = Decimal("50000") if bug == "otp_threshold_50k" else OTP_THRESHOLD
    return amount > threshold


def base_points(amount: Decimal, bug: str | None = None) -> int:
    if bug == "points_round_half_up":
        return int((amount / 100).quantize(Decimal("1"), rounding="ROUND_HALF_UP"))
    return int(amount // 100)


def reward_breakdown(
    amount: Decimal,
    total_due: Decimal,
    minimum_due: Decimal,
    due_date: date,
    paid_on: date,
    bug: str | None = None,
) -> dict[str, int]:
    """Points earned for one successful payment, split by rule."""
    full = amount >= total_due
    if bug == "full_bonus_on_minimum" and amount >= minimum_due:
        full = True
    days_early = (due_date - paid_on).days
    early_days_needed = EARLY_PAYMENT_DAYS + 1 if bug == "early_bonus_strict" else EARLY_PAYMENT_DAYS
    return {
        "base": base_points(amount, bug),
        "full_payment_bonus": FULL_PAYMENT_BONUS if full else 0,
        "early_payment_bonus": EARLY_PAYMENT_BONUS if days_early >= early_days_needed else 0,
    }


def tier(points: int, bug: str | None = None) -> str:
    silver_from = 1001 if bug == "silver_from_1001" else 1000
    if points >= 5000:
        return "Gold"
    if points >= silver_from:
        return "Silver"
    return "Bronze"


def redemption_value(points: int, balance: int, bug: str | None = None) -> Decimal:
    """Rupees credited for redeeming ``points``."""
    if points <= 0:
        raise RuleError("Points to redeem must be positive")
    if points < MIN_REDEMPTION and bug != "redeem_below_minimum":
        raise RuleError("Minimum redemption is 500 points")
    if points > balance:
        raise RuleError("Not enough reward points")
    rate = 10 if bug == "redeem_rate_10" else POINTS_PER_RUPEE_REDEEMED
    return (Decimal(points) / rate).quantize(Decimal("0.01"))


def luhn_valid(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def validate_card(number: str, expiry: str, cvv: str, today: date, bug: str | None = None) -> None:
    if not re.fullmatch(r"\d{16}", number):
        raise RuleError("Card number must be 16 digits")
    if bug != "luhn_unchecked" and not luhn_valid(number):
        raise RuleError("Card number is invalid")
    m = re.fullmatch(r"(0[1-9]|1[0-2])/(\d{2})", expiry)
    if not m:
        raise RuleError("Expiry must be MM/YY")
    month, year = int(m.group(1)), 2000 + int(m.group(2))
    # A card is valid through the last day of its expiry month.
    if (year, month) < (today.year, today.month) and bug != "expired_card_accepted":
        raise RuleError("Card has expired")
    if not re.fullmatch(r"\d{3}", cvv):
        raise RuleError("CVV must be 3 digits")


def validate_mobile(mobile: str) -> str:
    """Accepts 10 digits with an optional +91 prefix; returns the 10 digits."""
    m = re.fullmatch(r"(?:\+91)?([6-9]\d{9})", mobile)
    if not m:
        raise RuleError("Mobile must be an Indian number (+91, 10 digits)")
    return m.group(1)


def validate_password(password: str, bug: str | None = None) -> None:
    ok = (
        len(password) >= 8
        and re.search(r"[A-Z]", password)
        and re.search(r"\d", password)
        and (bug == "weak_password_accepted" or re.search(r"[^A-Za-z0-9]", password))
    )
    if not ok:
        raise RuleError("Password must be 8+ characters with 1 uppercase, 1 number and 1 special character")


def validate_pin(pin: str) -> None:
    if not re.fullmatch(r"\d{4}", pin):
        raise RuleError("PIN must be 4 digits")
