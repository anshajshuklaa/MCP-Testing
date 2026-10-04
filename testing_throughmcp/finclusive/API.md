# FinClusive API contract

This is what a black-box test may rely on. The business rules themselves are in
`src/data/original_requirements/FinClusive_Original_Scenario.md`.

Errors are JSON `{"detail": "<message>"}`. A business-rule violation is **422**.
Authenticated endpoints need `Authorization: Bearer <token>`; without it they return **401**.
Money is sent and returned as decimal strings or numbers (compare with `Decimal(str(x))`).
Today is **2026-01-01 10:00** until a test changes the clock.

## Registration and login
| Call | Success | Errors |
|---|---|---|
| `POST /auth/otp {mobile}` | 200 `{otp_sent: true}` | 422 bad mobile |
| `POST /users {mobile, otp, password, pin}` | 201 `{user_id, token}` | 401 wrong OTP, 409 mobile already registered, 422 bad mobile/password/PIN |
| `POST /auth/login {mobile, pin}` | 200 `{token}` | 401 wrong mobile or PIN |

Mobile: 10 digits starting 6-9, optional `+91` prefix.

## Cards
| Call | Success | Errors |
|---|---|---|
| `POST /cards {number, name, expiry "MM/YY", cvv}` | 201 `{card_id, last4, name, expiry, primary, verified: true}` | 409 same card twice, 422 invalid number/expiry/CVV or 6th card |
| `GET /cards` | 200 `{cards: [...]}` | |
| `DELETE /cards/{id}?confirm=true` | 200 `{deleted}` | 404, 422 without `confirm=true` |
| `POST /cards/{id}/primary` | 200 card | 404 |
| `GET /cards/{id}/bill` | 200 `{total_due, minimum_due, due_date}` | 404 |

The first card added is primary. A card is valid through the end of its expiry month.

## Payments
`POST /payments {card_id, amount, method, otp?}` where `method` is one of `UPI`, `Net Banking`, `Debit Card`, `Wallet`.

- **201** `{transaction_id, card_id, amount, method, status: "SUCCESS", created_at, points_earned, points_breakdown: {base, full_payment_bonus, early_payment_bonus}}`
- **403** `{"detail": "otp_required"}` when the amount needs an OTP and none (or a wrong one) was sent. An OTP is then issued to the user's mobile; resend the same body with `otp`.
- **409** duplicate payment (same amount, same card, within 5 minutes).
- **422** amount rules, more than the total due, daily limit, insufficient wallet balance, unknown method.

A payment reduces the card's `total_due` and `minimum_due`. "Paying the full bill" means paying the whole remaining `total_due`. Every method settles instantly.

`GET /transactions?card_id=&status=` returns 200 `{transactions: [...]}` for the last 30 days.

## Rewards
| Call | Success | Errors |
|---|---|---|
| `GET /rewards` | 200 `{points, tier, wallet_balance}` | |
| `POST /rewards/redeem {points}` | 200 `{points_redeemed, cashback, points, wallet_balance}` | 422 |

## Test support (no auth needed)
| Call | Purpose |
|---|---|
| `PUT /test-support/clock {now: ISO datetime}` | set "now" |
| `GET /test-support/otp?mobile=` | read the last OTP issued to a mobile |
| `PUT /test-support/cards/{id}/bill {total_due, minimum_due, due_date}` | give a card a bill |
| `PUT /test-support/users/{id}/wallet {balance}` | set wallet balance |
| `PUT /test-support/users/{id}/points {points}` | set reward points |

## Test kit
Tests receive a pytest fixture `fc`, a fresh `finclusive.testkit.FinClusive` per test:

```python
fc.register(mobile=None, password="Secure@123", pin="1234")  # new user, logged in; sets fc.user_id, fc.mobile
fc.add_card(number="4111111111111111", name="Test User", expiry="12/30", cvv="123") -> card_id
fc.set_bill(card_id, total_due, minimum_due, due_date: date)
fc.set_today(date_or_datetime)
fc.set_points(points); fc.set_wallet(balance)
fc.pay(card_id, amount, method="UPI", with_otp=True) -> response  # answers the OTP prompt when with_otp
fc.rewards() -> {points, tier, wallet_balance}
fc.otp_for(mobile) -> str
fc.get/post/put/delete(path, json=..., params=...) -> httpx response, token attached
```
`finclusive.testkit.VALID_CARDS` holds six distinct Luhn-valid card numbers.
