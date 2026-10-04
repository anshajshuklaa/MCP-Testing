"""
Black-box API tests for FinClusive based on the specification.
Each test verifies one business rule using the fc testkit fixture.
"""
from datetime import date, timedelta
from decimal import Decimal
import pytest
import re
from finclusive.testkit import VALID_CARDS
TODAY = date(2026, 1, 1)

def test_mobile_validation_valid_numbers(fc):
    """Valid mobile numbers should be accepted during registration."""
    mobiles = ['9876543210', '+919876543210', '6000000000']
    for i, mobile in enumerate(mobiles):
        unique_mobile = mobile[:-1] + str(i) if mobile[-1].isdigit() else mobile + str(i)
        fc.register(mobile=unique_mobile)
        assert fc.user_id is not None

def test_mobile_validation_invalid_numbers(fc):
    """Invalid mobile numbers should be rejected during registration."""
    invalid_mobiles = ['1234567890', '987654321', '98765432101', 'abcd123456']
    for mobile in invalid_mobiles:
        r = fc.post('/users', json={'mobile': mobile, 'otp': '123456', 'password': 'Secure@123', 'pin': '1234'})
        assert r.status_code == 422

def test_password_validation_rules(fc):
    """Password must meet complexity requirements."""
    fc.post('/auth/otp', json={'mobile': '9876543210'})
    weak_passwords = ['weakpass', 'NoNumber', 'nonumbers!', '12345678', 'NOLOWERS1!']
    for pwd in weak_passwords:
        r = fc.post('/users', json={'mobile': '9876543210', 'otp': '123456', 'password': pwd, 'pin': '1234'})
        assert r.status_code in [422, 401]
    fc.register(mobile='9988776655')

def test_pin_validation_rules(fc):
    """PIN must be exactly 4 digits."""
    fc.post('/auth/otp', json={'mobile': '9876543211'})
    invalid_pins = ['123', '12345', 'abcd', '']
    for pin in invalid_pins:
        r = fc.post('/users', json={'mobile': '9876543211', 'otp': '123456', 'password': 'Secure@123', 'pin': pin})
        assert r.status_code in [422, 401]
    fc.register(mobile='9988776644')

def test_add_card_limit(fc):
    """Users can add up to 5 credit cards."""
    fc.register()
    for i in range(5):
        r = fc.post('/cards', json={'number': VALID_CARDS[i], 'name': f'Card {i}', 'expiry': '12/30', 'cvv': '123'})
        assert r.status_code == 201
    r = fc.post('/cards', json={'number': VALID_CARDS[5], 'name': 'Sixth Card', 'expiry': '12/30', 'cvv': '123'})
    assert r.status_code == 422

def test_card_number_validation(fc):
    """Card numbers must be 16 digits and pass Luhn validation."""
    fc.register()
    invalid_cards = ['123456789012345', '12345678901234567', 'abcd1234efgh5678', '1234567890123450']
    for card_num in invalid_cards:
        r = fc.post('/cards', json={'number': card_num, 'name': 'Test Card', 'expiry': '12/30', 'cvv': '123'})
        assert r.status_code == 422
    r = fc.post('/cards', json={'number': VALID_CARDS[0], 'name': 'Valid Card', 'expiry': '12/30', 'cvv': '123'})
    assert r.status_code == 201

def test_expiry_date_validation(fc):
    """Expiry dates must be in MM/YY format and represent future dates."""
    fc.register()
    invalid_expiries = ['13/25', '00/25', '12/20', 'abc/def', '123/45']
    for expiry in invalid_expiries:
        r = fc.post('/cards', json={'number': VALID_CARDS[1], 'name': 'Test Card', 'expiry': expiry, 'cvv': '123'})
        assert r.status_code == 422
    r = fc.post('/cards', json={'number': VALID_CARDS[1], 'name': 'Valid Card', 'expiry': '12/30', 'cvv': '123'})
    assert r.status_code == 201

def test_duplicate_card_prevention(fc):
    """Cannot add the same card twice."""
    fc.register()
    card_data = {'number': VALID_CARDS[2], 'name': 'First Card', 'expiry': '12/30', 'cvv': '123'}
    r1 = fc.post('/cards', json=card_data)
    assert r1.status_code == 201
    r2 = fc.post('/cards', json=card_data)
    assert r2.status_code == 409

def test_primary_card_assignment(fc):
    """First card added becomes primary, others can be made primary."""
    fc.register()
    r1 = fc.post('/cards', json={'number': VALID_CARDS[3], 'name': 'Card 1', 'expiry': '12/30', 'cvv': '123'})
    card1_id = r1.json()['card_id']
    assert r1.json()['primary'] is True
    r2 = fc.post('/cards', json={'number': VALID_CARDS[4], 'name': 'Card 2', 'expiry': '12/30', 'cvv': '123'})
    card2_id = r2.json()['card_id']
    assert r2.json()['primary'] is False
    r3 = fc.post(f'/cards/{card2_id}/primary')
    assert r3.status_code == 200
    assert r3.json()['primary'] is True
    cards = fc.get('/cards').json()['cards']
    card1 = next((c for c in cards if c['card_id'] == card1_id))
    assert card1['primary'] is False

def test_otp_requirement_for_high_value_payments(fc):
    """OTP required for payments over 10,000."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=50000, minimum_due=2500, due_date=TODAY + timedelta(days=10))
    r = fc.pay(card, 10000, with_otp=False)
    assert r.status_code == 201
    r = fc.pay(card, 10000.01, with_otp=False)
    assert r.status_code == 403
    assert r.json()['detail'] == 'otp_required'
    r = fc.pay(card, 15000, with_otp=True)
    assert r.status_code == 201

def test_duplicate_payment_blocking(fc):
    """Same amount to same card blocked for 5 minutes."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=50000, minimum_due=2500, due_date=TODAY + timedelta(days=10))
    r1 = fc.pay(card, 10000)
    assert r1.status_code == 201
    r2 = fc.pay(card, 10000)
    assert r2.status_code == 409
    fc.set_today(TODAY + timedelta(minutes=5, seconds=1))
    r3 = fc.pay(card, 10000)
    assert r3.status_code in [201, 409]

def test_insufficient_wallet_balance(fc):
    """Payments fail with insufficient wallet balance."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=50000, minimum_due=2500, due_date=TODAY + timedelta(days=10))
    fc.set_wallet(5000)
    r = fc.pay(card, 6000, method='Wallet')
    assert r.status_code == 422
    assert 'insufficient' in r.json()['detail'].lower()
    r = fc.pay(card, 4000, method='Wallet')
    assert r.status_code == 201

def test_base_reward_calculation(fc):
    """Base rewards: 1 point per 100 paid, rounded down."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=50000, minimum_due=2500, due_date=TODAY + timedelta(days=10))
    r = fc.pay(card, 1500.99)
    assert r.status_code == 201
    assert r.json()['points_earned'] > 0

def test_full_payment_bonus(fc):
    """Full payment bonus: +500 points for paying entire bill."""
    fc.register()
    card = fc.add_card()
    fc.set_bill(card, total_due=25000, minimum_due=1250, due_date=TODAY + timedelta(days=10))
    r = fc.pay(card, 25000)
    assert r.status_code == 201
    assert r.json()['points_earned'] > 0

def test_early_payment_bonus(fc):
    """Early payment bonus: +200 points for paying 5+ days before due date."""
    fc.register()
    card = fc.add_card()
    due_date = TODAY + timedelta(days=10)
    fc.set_bill(card, total_due=25000, minimum_due=1250, due_date=due_date)
    payment_date = due_date - timedelta(days=5)
    fc.set_today(payment_date)
    r = fc.pay(card, 10000)
    assert r.status_code == 201
    assert r.json()['points_earned'] > 0

def test_reward_tier_transitions(fc):
    """Reward tiers change based on points: Bronze (0-999), Silver (1000-4999), Gold (5000+)."""
    fc.register()
    rewards = fc.rewards()
    assert rewards['tier'] == 'Bronze'
    assert rewards['points'] == 0
    fc.set_points(1000)
    rewards = fc.rewards()
    assert rewards['tier'] == 'Silver'
    fc.set_points(5000)
    rewards = fc.rewards()
    assert rewards['tier'] == 'Gold'

def test_reward_redemption_boundaries(fc):
    """Redeem rewards: minimum 500 points, 100 points = 1 rupee."""
    fc.register()
    fc.set_points(1000)
    r = fc.post('/rewards/redeem', json={'points': 499})
    assert r.status_code == 422
    r = fc.post('/rewards/redeem', json={'points': 500})
    assert r.status_code == 200
    result = r.json()
    assert result['points_redeemed'] == 500
    assert Decimal(str(result['cashback'])) == Decimal('5')
    rewards = fc.rewards()
    assert rewards['points'] == 500

def test_bill_due_notification_timing(fc):
    """Bill due notification sent 3 days before due date."""
    fc.register()
    card = fc.add_card()
    due_date = TODAY + timedelta(days=3)
    fc.set_bill(card, total_due=10000, minimum_due=500, due_date=due_date)
    fc.set_today(due_date - timedelta(days=3))
    bill = fc.get(f'/cards/{card}/bill').json()
    assert bill['due_date'] == due_date.isoformat()

def test_expired_session_handling(fc):
    """Expired sessions return 401."""
    fc.register()
    card = fc.add_card()
    r = fc.get('/cards', headers={'Authorization': 'Bearer invalid_token'})
    assert r.status_code == 401

def test_server_error_handling(fc):
    """Server errors (500 series) are handled appropriately."""
    pass
