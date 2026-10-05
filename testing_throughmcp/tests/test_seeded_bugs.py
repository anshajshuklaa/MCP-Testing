"""Each seeded bug must be observable through the API.

For every bug there is one probe: it returns True when FinClusive behaves as the
spec says. The probe must hold on the correct app and break with the bug on;
otherwise "bugs caught" scores would be measuring a bug no test could find.
"""

from datetime import date, timedelta

import pytest

from finclusive.bugs import BUGS
from finclusive.testkit import VALID_CARDS, FinClusive

TODAY = date(2026, 1, 1)


def _card_with_bill(fc, total=50000, minimum=2500, days_to_due=2, number=VALID_CARDS[0]):
    card = fc.add_card(number=number)
    fc.set_bill(card, total, minimum, TODAY + timedelta(days=days_to_due))
    return card


def _points_after(fc, amount, **bill):
    fc.register()
    card = _card_with_bill(fc, **bill)
    assert fc.pay(card, amount).status_code == 201
    return fc.rewards()["points"]


def _add_card_status(fc, **kw):
    fc.register()
    body = {"number": VALID_CARDS[0], "name": "A", "expiry": "12/30", "cvv": "123", **kw}
    return fc.post("/cards", json=body).status_code


def _pay_status(fc, amount, total=50000, with_otp=True):
    fc.register()
    return fc.pay(_card_with_bill(fc, total=total), amount, with_otp=with_otp).status_code


def _redeem(fc, points, balance=1000):
    fc.register()
    fc.set_points(balance)
    return fc.post("/rewards/redeem", json={"points": points})


def _tier_at(fc, points):
    fc.register()
    fc.set_points(points)
    return fc.rewards()["tier"]


PROBES = {
    "points_round_half_up": lambda fc: _points_after(fc, 150) == 1,
    "full_bonus_on_minimum": lambda fc: _points_after(fc, 2500) == 25,
    "early_bonus_strict": lambda fc: _points_after(fc, 1000, days_to_due=5) == 210,
    "otp_threshold_50k": lambda fc: _pay_status(fc, 20000, with_otp=False) == 403,
    "min_payment_99": lambda fc: _pay_status(fc, 99) == 422,
    "max_payment_unchecked": lambda fc: _pay_status(fc, 500001, total=600000) == 422,
    "daily_limit_unchecked": lambda fc: _daily_limit_holds(fc),
    "duplicate_not_blocked": lambda fc: _duplicate_blocked(fc),
    "luhn_unchecked": lambda fc: _add_card_status(fc, number="4111111111111112") == 422,
    "expired_card_accepted": lambda fc: _add_card_status(fc, expiry="12/25") == 422,
    "sixth_card_allowed": lambda fc: _sixth_card_rejected(fc),
    "silver_from_1001": lambda fc: _tier_at(fc, 1000) == "Silver",
    "redeem_below_minimum": lambda fc: _redeem(fc, 499).status_code == 422,
    "redeem_rate_10": lambda fc: float(_redeem(fc, 500).json()["cashback"]) == 5.0,
    "three_decimal_amounts": lambda fc: _pay_status(fc, "100.005") == 422,
    "weak_password_accepted": lambda fc: _weak_password_rejected(fc),
}


def _daily_limit_holds(fc):
    fc.register()
    a = _card_with_bill(fc, total=500000, number=VALID_CARDS[0])
    b = _card_with_bill(fc, total=500000, number=VALID_CARDS[1])
    c = _card_with_bill(fc, total=500000, number=VALID_CARDS[2])
    assert fc.pay(a, 500000).status_code == 201
    assert fc.pay(b, 500000).status_code == 201
    return fc.pay(c, 100).status_code == 422


def _duplicate_blocked(fc):
    fc.register()
    card = _card_with_bill(fc)
    assert fc.pay(card, 1000).status_code == 201
    return fc.pay(card, 1000).status_code == 409


def _sixth_card_rejected(fc):
    fc.register()
    for number in VALID_CARDS[:5]:
        fc.add_card(number=number)
    return fc.post("/cards", json={"number": VALID_CARDS[5], "name": "A", "expiry": "12/30", "cvv": "123"}).status_code == 422


def _weak_password_rejected(fc):
    fc.post("/auth/otp", json={"mobile": "9123456789"})
    body = {"mobile": "9123456789", "otp": fc.otp_for("9123456789"), "password": "Secure1234", "pin": "1234"}
    return fc.post("/users", json=body).status_code == 422


def test_every_bug_has_a_probe():
    assert set(PROBES) == set(BUGS)


@pytest.mark.parametrize("bug", sorted(BUGS))
def test_probe_holds_on_correct_app(bug):
    assert PROBES[bug](FinClusive()) is True


@pytest.mark.parametrize("bug", sorted(BUGS))
def test_probe_breaks_with_bug(bug):
    assert PROBES[bug](FinClusive(bug=bug)) is False


def test_unknown_bug_is_rejected():
    with pytest.raises(ValueError, match="Unknown bug"):
        FinClusive(bug="no_such_bug")
