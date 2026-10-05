"""The 7 human-written baseline tests, translated to executable pytest.

Source: spec/human_baseline_tests.json.
Each test keeps the original id, steps and expected result; only the UI steps
are replaced with the matching API calls.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

TODAY = date(2026, 1, 1)


def test_fp_001_full_payment_with_early_bird_bonus(fc):
    """FP-001: pay the full 50,000 ten days early -> 500 + 500 + 200 = 1200 points."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=50000, minimum_due=2500, due_date=TODAY + timedelta(days=10))

    r = fc.pay(card, 50000, method="UPI")

    assert r.status_code == 201
    assert r.json()["status"] == "SUCCESS"
    assert fc.rewards()["points"] == 1200


def test_pp_001_partial_minimum_payment(fc):
    """PP-001: pay 100 against a 25,000 bill -> 1 point and no bonuses."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=25000, minimum_due=1250, due_date=TODAY + timedelta(days=2))

    r = fc.pay(card, 100, method="Net Banking")

    assert r.status_code == 201
    assert fc.rewards()["points"] == 1


@pytest.mark.skip(reason="AP-001 tests an Auto-Pay bonus that the FinClusive spec does not define")
def test_ap_001_monthly_auto_pay_bonus(fc):
    """AP-001: the spec has no Auto-Pay feature, so this human test cannot be executed."""


def test_reg_001_registration_and_card_addition(fc):
    """REG-001: register with mobile + OTP + password + PIN, add a valid card, see it listed."""
    fc.register(mobile="9876543210")
    r = fc.post("/cards", json={"number": "4111111111111111", "name": "Asha Rao", "expiry": "12/30", "cvv": "123"})

    assert r.status_code == 201
    assert r.json()["verified"] is True
    cards = fc.get("/cards").json()["cards"]
    assert [c["last4"] for c in cards] == ["1111"]


def test_sec_001_otp_required_for_high_value_payment(fc):
    """SEC-001: a 15,000 payment must ask for an OTP before it completes."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=30000, minimum_due=1500, due_date=TODAY + timedelta(days=2))

    r = fc.pay(card, 15000, with_otp=False)

    assert r.status_code == 403
    assert r.json()["detail"] == "otp_required"


def test_rew_001_redeem_minimum_points(fc):
    """REW-001: redeeming 500 points deducts 500 and credits 5 rupees."""
    fc.register()
    fc.set_points(800)

    r = fc.post("/rewards/redeem", json={"points": 500})

    assert r.status_code == 200
    rewards = fc.rewards()
    assert rewards["points"] == 300
    assert Decimal(str(rewards["wallet_balance"])) == Decimal("5")


def test_val_001_payment_below_minimum_rejected(fc):
    """VAL-001: a payment of 99 is rejected with 'Minimum payment amount is 100'."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=5000, minimum_due=250, due_date=TODAY + timedelta(days=2))

    r = fc.pay(card, 99)

    assert r.status_code == 422
    assert r.json()["detail"] == "Minimum payment amount is 100"
