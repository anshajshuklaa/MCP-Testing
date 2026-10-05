"""
Black-box API tests for FinClusive based on the specification.
Each test verifies one specific business rule or edge case.
"""
from datetime import date, timedelta
from decimal import Decimal
import pytest
import re
from finclusive.testkit import VALID_CARDS
TODAY = date(2026, 1, 1)

def test_mobile_validation_invalid_numbers(fc):
    """Invalid mobile numbers should be rejected during registration."""
    invalid_mobiles = ['1234567890', '987654321', '98765432101', 'abcd123456']
    for mobile in invalid_mobiles:
        r = fc.post('/auth/otp', json={'mobile': mobile})
        assert r.status_code == 422

def test_card_limit_maximum_cards(fc):
    """A user can add a maximum of 5 cards."""
    fc.register()
    for i in range(5):
        fc.add_card(number=VALID_CARDS[i])
    r = fc.post('/cards', json={'number': VALID_CARDS[5], 'name': 'Extra Card', 'expiry': '12/30', 'cvv': '123'})
    assert r.status_code == 422

def test_card_number_validation_luhn(fc):
    """Card numbers must pass Luhn validation."""
    fc.register()
    invalid_card = '1234567890123456'
    r = fc.post('/cards', json={'number': invalid_card, 'name': 'Test User', 'expiry': '12/30', 'cvv': '123'})
    assert r.status_code == 422

def test_card_expiry_validation_future_only(fc):
    """Card expiry must be in the future."""
    fc.register()
    past_expiry = '12/20'
    r = fc.post('/cards', json={'number': VALID_CARDS[0], 'name': 'Test User', 'expiry': past_expiry, 'cvv': '123'})
    assert r.status_code == 422

def test_card_expiry_validation_current_month_valid(fc):
    """Card valid through end of expiry month."""
    fc.register()
    current_month_expiry = '01/26'
    r = fc.post('/cards', json={'number': VALID_CARDS[0], 'name': 'Test User', 'expiry': current_month_expiry, 'cvv': '123'})
    assert r.status_code == 201

def test_duplicate_card_prevention(fc):
    """Adding the same card twice should be prevented."""
    fc.register()
    card_number = VALID_CARDS[0]
    fc.add_card(number=card_number)
    r = fc.post('/cards', json={'number': card_number, 'name': 'Another Name', 'expiry': '12/30', 'cvv': '123'})
    assert r.status_code == 409

def test_payment_minimum_amount_boundary(fc):
    """Payment of exactly ₹100 should be accepted."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=5000, minimum_due=250, due_date=TODAY + timedelta(days=5))
    r = fc.pay(card, 100)
    assert r.status_code == 201

def test_payment_below_minimum_rejected(fc):
    """Payment below ₹100 should be rejected."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=5000, minimum_due=250, due_date=TODAY + timedelta(days=5))
    r = fc.pay(card, 99.99)
    assert r.status_code == 422

def test_payment_maximum_single_amount_boundary(fc):
    """Payment of exactly ₹5,00,000 should be accepted."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=600000, minimum_due=3000, due_date=TODAY + timedelta(days=5))
    r = fc.pay(card, 500000)
    assert r.status_code == 201

def test_payment_above_maximum_single_amount_rejected(fc):
    """Payment above ₹5,00,000 should be rejected."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=600000, minimum_due=3000, due_date=TODAY + timedelta(days=5))
    r = fc.pay(card, 500000.01)
    assert r.status_code == 422

def test_daily_payment_limit_boundary(fc):
    """Total payments of exactly ₹10,00,000 in a day should be accepted."""
    fc.register()
    card1 = fc.add_card(number=VALID_CARDS[0])
    card2 = fc.add_card(number=VALID_CARDS[1])
    fc.set_bill(card1, total_due=600000, minimum_due=3000, due_date=TODAY + timedelta(days=5))
    fc.set_bill(card2, total_due=600000, minimum_due=3000, due_date=TODAY + timedelta(days=5))
    r1 = fc.pay(card1, 500000)
    assert r1.status_code == 201
    r2 = fc.pay(card2, 500000)
    assert r2.status_code == 201

def test_daily_payment_exceeds_limit_rejected(fc):
    """Payments exceeding ₹10,00,000 in a day should be rejected."""
    fc.register()
    card1 = fc.add_card(number=VALID_CARDS[0])
    card2 = fc.add_card(number=VALID_CARDS[1])
    fc.set_bill(card1, total_due=600000, minimum_due=3000, due_date=TODAY + timedelta(days=5))
    fc.set_bill(card2, total_due=600000, minimum_due=3000, due_date=TODAY + timedelta(days=5))
    r1 = fc.pay(card1, 500000)
    assert r1.status_code == 201
    r2 = fc.pay(card2, 500000.01)
    assert r2.status_code == 422

def test_reward_full_payment_bonus(fc):
    """Full payment bonus: +500 points for paying entire bill."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=10000, minimum_due=500, due_date=TODAY + timedelta(days=5))
    r = fc.pay(card, 10000)
    assert r.status_code == 201
    breakdown = r.json()['points_breakdown']
    assert breakdown['full_payment_bonus'] == 500

def test_reward_no_full_payment_bonus_partial_payment(fc):
    """No full payment bonus for partial payments."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=10000, minimum_due=500, due_date=TODAY + timedelta(days=5))
    r = fc.pay(card, 9999.99)
    assert r.status_code == 201
    breakdown = r.json()['points_breakdown']
    assert breakdown['full_payment_bonus'] == 0

def test_reward_early_payment_bonus_boundary(fc):
    """Early payment bonus: +200 points for paying 5+ days before due date."""
    fc.register()
    card = fc.add_card()
    due_in_5_days = TODAY + timedelta(days=5)
    fc.set_bill(card, total_due=5000, minimum_due=250, due_date=due_in_5_days)
    r = fc.pay(card, 1000)
    assert r.status_code == 201
    breakdown = r.json()['points_breakdown']
    assert breakdown['early_payment_bonus'] == 200

def test_reward_no_early_payment_bonus_on_due_date(fc):
    """No early payment bonus if paid on due date."""
    fc.register()
    card = fc.add_card()
    due_today = TODAY
    fc.set_bill(card, total_due=5000, minimum_due=250, due_date=due_today)
    r = fc.pay(card, 1000)
    assert r.status_code == 201
    breakdown = r.json()['points_breakdown']
    assert breakdown['early_payment_bonus'] == 0

def test_reward_tier_bronze(fc):
    """User with 0-999 points is in Bronze tier."""
    fc.register()
    fc.set_points(999)
    rewards = fc.rewards()
    assert rewards['tier'] == 'Bronze'

def test_reward_tier_silver_lower_bound(fc):
    """User with 1000 points enters Silver tier."""
    fc.register()
    fc.set_points(1000)
    rewards = fc.rewards()
    assert rewards['tier'] == 'Silver'

def test_reward_tier_silver_upper_bound(fc):
    """User with 4999 points is still in Silver tier."""
    fc.register()
    fc.set_points(4999)
    rewards = fc.rewards()
    assert rewards['tier'] == 'Silver'

def test_reward_tier_gold(fc):
    """User with 5000+ points enters Gold tier."""
    fc.register()
    fc.set_points(5000)
    rewards = fc.rewards()
    assert rewards['tier'] == 'Gold'

def test_redemption_minimum_points_boundary(fc):
    """Redeeming exactly 500 points should succeed."""
    fc.register()
    fc.set_points(500)
    r = fc.post('/rewards/redeem', json={'points': 500})
    assert r.status_code == 200
    assert r.json()['points_redeemed'] == 500

def test_redemption_below_minimum_rejected(fc):
    """Redeeming less than 500 points should fail."""
    fc.register()
    fc.set_points(499)
    r = fc.post('/rewards/redeem', json={'points': 499})
    assert r.status_code == 422

def test_redemption_insufficient_points_rejected(fc):
    """Redeeming more points than available should fail."""
    fc.register()
    fc.set_points(300)
    r = fc.post('/rewards/redeem', json={'points': 500})
    assert r.status_code == 422

def test_otp_required_for_high_value_payment_boundary(fc):
    """OTP required for payments > ₹10,000."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=20000, minimum_due=1000, due_date=TODAY + timedelta(days=5))
    r = fc.pay(card, 10000.01, with_otp=False)
    assert r.status_code == 403
    assert r.json()['detail'] == 'otp_required'

def test_otp_not_required_for_low_value_payment(fc):
    """OTP not required for payments <= ₹10,000."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=20000, minimum_due=1000, due_date=TODAY + timedelta(days=5))
    r = fc.pay(card, 10000, with_otp=False)
    assert r.status_code == 201

def test_duplicate_payment_blocked_same_amount_same_card(fc):
    """Same amount to same card blocked for 5 minutes."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=20000, minimum_due=1000, due_date=TODAY + timedelta(days=5))
    r1 = fc.pay(card, 5000)
    assert r1.status_code == 201
    r2 = fc.pay(card, 5000)
    assert r2.status_code == 409

def test_different_amount_to_same_card_allowed(fc):
    """Different amount to same card should be allowed."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=20000, minimum_due=1000, due_date=TODAY + timedelta(days=5))
    r1 = fc.pay(card, 5000)
    assert r1.status_code == 201
    r2 = fc.pay(card, 5000.01)
    assert r2.status_code == 201

def test_payment_insufficient_wallet_balance_rejected(fc):
    """Payment fails if wallet balance is insufficient."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=20000, minimum_due=1000, due_date=TODAY + timedelta(days=5))
    fc.set_wallet(Decimal('499.99'))
    r = fc.pay(card, 500, method='Wallet')
    assert r.status_code == 422

def test_payment_sufficient_wallet_balance_accepted(fc):
    """Payment succeeds if wallet balance is sufficient."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=20000, minimum_due=1000, due_date=TODAY + timedelta(days=5))
    fc.set_wallet(Decimal('500'))
    r = fc.pay(card, 500, method='Wallet')
    assert r.status_code == 201
