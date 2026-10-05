"""FinClusive: a small, runnable implementation of the FinClusive spec.

This is the system under test. It keeps all state in memory, so every test
gets a fresh app from ``create_app()``.

Endpoints under ``/test-support`` exist only so tests can set up state that a
real app would get from outside (today's date, an issued OTP, a card's bill).

Simplifications (documented so tests don't assume otherwise):
- Every payment method settles instantly with status SUCCESS, except Wallet,
  which fails with 422 when the wallet balance is too low.
- OTPs are random 6-digit codes; tests read them from /test-support/otp.
"""

import os
import random
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import rules
from .bugs import check as check_bug

PAYMENT_METHODS = {"UPI", "Net Banking", "Debit Card", "Wallet"}


@dataclass
class Card:
    id: str
    number: str
    name: str
    expiry: str
    primary: bool = False
    total_due: Decimal = Decimal("0")
    minimum_due: Decimal = Decimal("0")
    due_date: date | None = None


@dataclass
class User:
    id: str
    mobile: str
    password: str
    pin: str
    cards: dict[str, Card] = field(default_factory=dict)
    points: int = 0
    wallet: Decimal = Decimal("0")
    transactions: list[dict] = field(default_factory=list)


@dataclass
class State:
    bug: str | None
    now: datetime = field(default_factory=lambda: datetime(2026, 1, 1, 10, 0, 0))
    users: dict[str, User] = field(default_factory=dict)  # by user id
    tokens: dict[str, str] = field(default_factory=dict)  # token -> user id
    otps: dict[str, str] = field(default_factory=dict)  # mobile -> otp
    counter: int = 0

    def next_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}{self.counter:05d}"

    def user_by_mobile(self, mobile: str) -> User | None:
        return next((u for u in self.users.values() if u.mobile == mobile), None)


class OtpRequest(BaseModel):
    mobile: str


class RegisterRequest(BaseModel):
    mobile: str
    otp: str
    password: str
    pin: str


class LoginRequest(BaseModel):
    mobile: str
    pin: str


class AddCardRequest(BaseModel):
    number: str
    name: str
    expiry: str
    cvv: str


class PaymentRequest(BaseModel):
    card_id: str
    amount: Decimal
    method: str
    otp: str | None = None


class RedeemRequest(BaseModel):
    points: int


class ClockRequest(BaseModel):
    now: datetime


class BillRequest(BaseModel):
    total_due: Decimal
    minimum_due: Decimal
    due_date: date


class WalletRequest(BaseModel):
    balance: Decimal


def create_app(bug: str | None = None) -> FastAPI:
    """Build a fresh app. ``bug`` defaults to the FINCLUSIVE_BUG env var."""
    state = State(bug=check_bug(bug if bug is not None else os.environ.get("FINCLUSIVE_BUG")))
    app = FastAPI(title="FinClusive", version="1.0.0")
    app.state.finclusive = state

    @app.exception_handler(rules.RuleError)
    async def rule_error(_: Request, exc: rules.RuleError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    def current_user(authorization: str = Header(default="")) -> User:
        token = authorization.removeprefix("Bearer ").strip()
        user_id = state.tokens.get(token)
        if not user_id:
            raise HTTPException(401, "Not logged in")
        return state.users[user_id]

    def card_of(user: User, card_id: str) -> Card:
        card = user.cards.get(card_id)
        if not card:
            raise HTTPException(404, "Card not found")
        return card

    def issue_otp(mobile: str) -> None:
        state.otps[mobile] = f"{random.randint(0, 999999):06d}"

    def take_otp(mobile: str, otp: str | None) -> bool:
        if otp and state.otps.get(mobile) == otp:
            del state.otps[mobile]
            return True
        return False

    def login_token(user: User) -> str:
        token = secrets.token_hex(16)
        state.tokens[token] = user.id
        return token

    # --- registration and login ---

    @app.post("/auth/otp")
    def request_otp(body: OtpRequest):
        mobile = rules.validate_mobile(body.mobile)
        issue_otp(mobile)
        return {"otp_sent": True}

    @app.post("/users", status_code=201)
    def register(body: RegisterRequest):
        mobile = rules.validate_mobile(body.mobile)
        if state.user_by_mobile(mobile):
            raise HTTPException(409, "Mobile number already registered")
        if not take_otp(mobile, body.otp):
            raise HTTPException(401, "Invalid OTP")
        rules.validate_password(body.password, state.bug)
        rules.validate_pin(body.pin)
        user = User(id=state.next_id("U"), mobile=mobile, password=body.password, pin=body.pin)
        state.users[user.id] = user
        return {"user_id": user.id, "token": login_token(user)}

    @app.post("/auth/login")
    def login(body: LoginRequest):
        user = state.user_by_mobile(rules.validate_mobile(body.mobile))
        if not user or user.pin != body.pin:
            raise HTTPException(401, "Invalid mobile number or PIN")
        return {"token": login_token(user)}

    # --- cards ---

    def card_json(card: Card) -> dict:
        return {
            "card_id": card.id,
            "last4": card.number[-4:],
            "name": card.name,
            "expiry": card.expiry,
            "primary": card.primary,
        }

    @app.post("/cards", status_code=201)
    def add_card(body: AddCardRequest, user: User = Depends(current_user)):
        limit = rules.MAX_CARDS + 1 if state.bug == "sixth_card_allowed" else rules.MAX_CARDS
        if len(user.cards) >= limit:
            raise rules.RuleError("A user can add at most 5 cards")
        rules.validate_card(body.number, body.expiry, body.cvv, state.now.date(), state.bug)
        if any(c.number == body.number for c in user.cards.values()):
            raise HTTPException(409, "Card already added")
        # The ₹1 verification transaction always succeeds for a valid card.
        card = Card(id=state.next_id("C"), number=body.number, name=body.name, expiry=body.expiry)
        card.primary = not user.cards
        user.cards[card.id] = card
        return {**card_json(card), "verified": True}

    @app.get("/cards")
    def list_cards(user: User = Depends(current_user)):
        return {"cards": [card_json(c) for c in user.cards.values()]}

    @app.delete("/cards/{card_id}")
    def delete_card(card_id: str, confirm: bool = False, user: User = Depends(current_user)):
        card = card_of(user, card_id)
        if not confirm:
            raise rules.RuleError("Deleting a card needs confirm=true")
        del user.cards[card_id]
        if card.primary and user.cards:
            next(iter(user.cards.values())).primary = True
        return {"deleted": card_id}

    @app.post("/cards/{card_id}/primary")
    def set_primary(card_id: str, user: User = Depends(current_user)):
        card = card_of(user, card_id)
        for c in user.cards.values():
            c.primary = c is card
        return card_json(card)

    @app.get("/cards/{card_id}/bill")
    def get_bill(card_id: str, user: User = Depends(current_user)):
        card = card_of(user, card_id)
        return {
            "total_due": card.total_due,
            "minimum_due": card.minimum_due,
            "due_date": card.due_date,
        }

    # --- payments ---

    @app.post("/payments", status_code=201)
    def pay(body: PaymentRequest, user: User = Depends(current_user)):
        card = card_of(user, body.card_id)
        if body.method not in PAYMENT_METHODS:
            raise rules.RuleError(f"Payment method must be one of {sorted(PAYMENT_METHODS)}")
        amount = body.amount
        rules.validate_amount(amount, state.bug)
        if amount > card.total_due:
            raise rules.RuleError("Amount is more than the total due")

        now = state.now
        today_paid = sum(
            Decimal(t["amount"])
            for t in user.transactions
            if t["status"] == "SUCCESS" and datetime.fromisoformat(t["created_at"]).date() == now.date()
        )
        if today_paid + amount > rules.DAILY_LIMIT and state.bug != "daily_limit_unchecked":
            raise rules.RuleError("Daily payment limit of 1000000 exceeded")

        window = timedelta(seconds=rules.DUPLICATE_WINDOW_SECONDS)
        duplicate = any(
            t["card_id"] == card.id
            and Decimal(t["amount"]) == amount
            and t["status"] == "SUCCESS"
            and now - datetime.fromisoformat(t["created_at"]) < window
            for t in user.transactions
        )
        if duplicate and state.bug != "duplicate_not_blocked":
            raise HTTPException(409, "Duplicate payment blocked: same amount to the same card within 5 minutes")

        if rules.otp_required(amount, state.bug) and not take_otp(user.mobile, body.otp):
            issue_otp(user.mobile)
            return JSONResponse(status_code=403, content={"detail": "otp_required"})

        if body.method == "Wallet":
            if user.wallet < amount:
                raise rules.RuleError("Insufficient wallet balance")
            user.wallet -= amount

        breakdown = rules.reward_breakdown(
            amount, card.total_due, card.minimum_due, card.due_date or now.date(), now.date(), state.bug
        )
        points = sum(breakdown.values())
        card.total_due -= amount
        card.minimum_due = max(Decimal("0"), card.minimum_due - amount)
        user.points += points
        txn = {
            "transaction_id": state.next_id("T"),
            "card_id": card.id,
            "amount": str(amount),
            "method": body.method,
            "status": "SUCCESS",
            "created_at": now.isoformat(),
            "points_earned": points,
            "points_breakdown": breakdown,
        }
        user.transactions.append(txn)
        return txn

    @app.get("/transactions")
    def transactions(card_id: str | None = None, status: str | None = None, user: User = Depends(current_user)):
        since = state.now - timedelta(days=30)
        items = [
            t
            for t in user.transactions
            if datetime.fromisoformat(t["created_at"]) >= since
            and (card_id is None or t["card_id"] == card_id)
            and (status is None or t["status"] == status.upper())
        ]
        return {"transactions": items}

    # --- rewards ---

    @app.get("/rewards")
    def rewards(user: User = Depends(current_user)):
        return {"points": user.points, "tier": rules.tier(user.points, state.bug), "wallet_balance": user.wallet}

    @app.post("/rewards/redeem")
    def redeem(body: RedeemRequest, user: User = Depends(current_user)):
        rupees = rules.redemption_value(body.points, user.points, state.bug)
        user.points -= body.points
        user.wallet += rupees
        return {"points_redeemed": body.points, "cashback": rupees, "points": user.points, "wallet_balance": user.wallet}

    # --- test support ---

    @app.put("/test-support/clock")
    def set_clock(body: ClockRequest):
        state.now = body.now.replace(tzinfo=None)
        return {"now": state.now}

    @app.get("/test-support/otp")
    def read_otp(mobile: str):
        otp = state.otps.get(rules.validate_mobile(mobile))
        if not otp:
            raise HTTPException(404, "No OTP issued")
        return {"otp": otp}

    @app.put("/test-support/cards/{card_id}/bill")
    def set_bill(card_id: str, body: BillRequest):
        card = next((u.cards[card_id] for u in state.users.values() if card_id in u.cards), None)
        if not card:
            raise HTTPException(404, "Card not found")
        card.total_due, card.minimum_due, card.due_date = body.total_due, body.minimum_due, body.due_date
        return {"card_id": card_id, **body.model_dump()}

    @app.put("/test-support/users/{user_id}/wallet")
    def set_wallet(user_id: str, body: WalletRequest):
        user = state.users.get(user_id)
        if not user:
            raise HTTPException(404, "User not found")
        user.wallet = body.balance
        return {"wallet_balance": user.wallet}

    @app.put("/test-support/users/{user_id}/points")
    def set_points(user_id: str, body: RedeemRequest):
        user = state.users.get(user_id)
        if not user:
            raise HTTPException(404, "User not found")
        user.points = body.points
        return {"points": user.points}

    return app


app = create_app()
