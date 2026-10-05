"""Helpers that human-written and AI-written test suites share.

Tests talk to FinClusive only over HTTP (FastAPI's TestClient), so they are
black-box tests of the API. The helpers cover the setup a test needs before it
can check a business rule: a logged-in user, a card, a bill, today's date.
"""

from datetime import date, datetime

from fastapi.testclient import TestClient

from .app import create_app

VALID_CARD = "4111111111111111"  # Luhn-valid test number
# Six distinct Luhn-valid 16-digit numbers, for tests that need several cards.
VALID_CARDS = [
    "4111111111111111",
    "5555555555554444",
    "4012888888881881",
    "5105105105105100",
    "4000056655665556",
    "6011111111111117",
]
STRONG_PASSWORD = "Secure@123"


class FinClusive:
    """A test client with shortcuts for common setup steps."""

    def __init__(self, bug: str | None = None):
        self.app = create_app(bug)
        self.http = TestClient(self.app)
        self.token: str | None = None
        self.user_id: str | None = None
        self.mobile: str | None = None
        self._next_mobile = 9000000000

    # Raw HTTP, with the logged-in user's token attached.
    def request(self, method: str, path: str, **kwargs):
        headers = kwargs.pop("headers", {})
        if self.token:
            headers.setdefault("Authorization", f"Bearer {self.token}")
        return self.http.request(method, path, headers=headers, **kwargs)

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def put(self, path, **kw):
        return self.request("PUT", path, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

    # Setup shortcuts.
    def set_today(self, day: date | datetime) -> None:
        now = day if isinstance(day, datetime) else datetime(day.year, day.month, day.day, 10, 0)
        self.put("/test-support/clock", json={"now": now.isoformat()}).raise_for_status()

    def otp_for(self, mobile: str) -> str:
        r = self.get("/test-support/otp", params={"mobile": mobile})
        r.raise_for_status()
        return r.json()["otp"]

    def register(self, mobile: str | None = None, password: str = STRONG_PASSWORD, pin: str = "1234") -> dict:
        """Register a new user and log in as them. Returns the /users response."""
        if mobile is None:
            self._next_mobile += 1
            mobile = str(self._next_mobile)
        self.post("/auth/otp", json={"mobile": mobile}).raise_for_status()
        r = self.post("/users", json={"mobile": mobile, "otp": self.otp_for(mobile), "password": password, "pin": pin})
        r.raise_for_status()
        body = r.json()
        self.token, self.user_id, self.mobile = body["token"], body["user_id"], mobile
        return body

    def add_card(self, number: str = VALID_CARD, name: str = "Test User", expiry: str = "12/30", cvv: str = "123") -> str:
        r = self.post("/cards", json={"number": number, "name": name, "expiry": expiry, "cvv": cvv})
        r.raise_for_status()
        return r.json()["card_id"]

    def set_bill(self, card_id: str, total_due, minimum_due, due_date: date) -> None:
        self.put(
            f"/test-support/cards/{card_id}/bill",
            json={"total_due": str(total_due), "minimum_due": str(minimum_due), "due_date": due_date.isoformat()},
        ).raise_for_status()

    def set_points(self, points: int) -> None:
        self.put(f"/test-support/users/{self.user_id}/points", json={"points": points}).raise_for_status()

    def set_wallet(self, balance) -> None:
        self.put(f"/test-support/users/{self.user_id}/wallet", json={"balance": str(balance)}).raise_for_status()

    def pay(self, card_id: str, amount, method: str = "UPI", with_otp: bool = True):
        """POST /payments. If the API asks for an OTP and with_otp is True, answer it."""
        body = {"card_id": card_id, "amount": str(amount), "method": method}
        r = self.post("/payments", json=body)
        if r.status_code == 403 and r.json().get("detail") == "otp_required" and with_otp:
            r = self.post("/payments", json={**body, "otp": self.otp_for(self.mobile)})
        return r

    def rewards(self) -> dict:
        r = self.get("/rewards")
        r.raise_for_status()
        return r.json()
