"""Billing endpoint tests with the Stripe SDK stubbed out."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import stripe
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from genpicks.api.main import app, get_session
from genpicks.config import get_settings
from genpicks.db.models import Base, User

INTERNAL_KEY = "test-internal-key"
INTERNAL = {"X-Internal-Key": INTERNAL_KEY}
CHECKOUT_BODY = {
    "user_id": 1,
    "success_url": "http://site/matches/1?sub=ok",
    "cancel_url": "http://site/matches/1",
}


@pytest.fixture()
def client_and_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add_all(
            [
                User(id=1, github_id="100", email="a@x.com", name="Fresh User",
                     created_at=now),
                User(id=2, github_id="200", created_at=now,
                     stripe_customer_id="cus_existing",
                     subscription_status="active"),
            ]
        )
        session.commit()

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    settings = get_settings()
    saved = (settings.internal_api_key, settings.stripe_secret_key,
             settings.stripe_webhook_secret, settings.stripe_price_id)
    settings.internal_api_key = INTERNAL_KEY
    settings.stripe_secret_key = "sk_test_x"
    settings.stripe_webhook_secret = "whsec_x"
    settings.stripe_price_id = "price_x"
    yield TestClient(app), factory
    (settings.internal_api_key, settings.stripe_secret_key,
     settings.stripe_webhook_secret, settings.stripe_price_id) = saved
    app.dependency_overrides.clear()


def user_row(factory, user_id):
    with factory() as session:
        user = session.get(User, user_id)
        return (user.stripe_customer_id, user.subscription_status)


def test_checkout_creates_customer_once_and_returns_url(client_and_db, monkeypatch):
    client, factory = client_and_db
    created = []
    checkouts = []
    monkeypatch.setattr(
        stripe.Customer, "create",
        lambda **kw: created.append(kw) or SimpleNamespace(id="cus_new"),
    )
    monkeypatch.setattr(
        stripe.checkout.Session, "create",
        lambda **kw: checkouts.append(kw)
        or SimpleNamespace(url="https://checkout.stripe.test/sess"),
    )

    body = client.post("/internal/billing/checkout", json=CHECKOUT_BODY,
                       headers=INTERNAL).json()
    assert body == {"url": "https://checkout.stripe.test/sess"}
    assert created[0]["email"] == "a@x.com"
    assert user_row(factory, 1) == ("cus_new", None)  # not active until webhook
    assert checkouts[0]["mode"] == "subscription"
    assert checkouts[0]["client_reference_id"] == "1"

    # second checkout reuses the saved customer
    client.post("/internal/billing/checkout", json=CHECKOUT_BODY, headers=INTERNAL)
    assert len(created) == 1 and len(checkouts) == 2
    assert checkouts[1]["customer"] == "cus_new"


def test_checkout_guards(client_and_db):
    client, _ = client_and_db
    assert client.post("/internal/billing/checkout", json=CHECKOUT_BODY,
                       headers={"X-Internal-Key": "wrong"}).status_code == 401
    assert client.post("/internal/billing/checkout",
                       json={**CHECKOUT_BODY, "user_id": 999},
                       headers=INTERNAL).status_code == 404
    # a live key must be refused: the checkout is a demo by construction
    get_settings().stripe_secret_key = "sk_live_forbidden"
    assert client.post("/internal/billing/checkout", json=CHECKOUT_BODY,
                       headers=INTERNAL).status_code == 503
    get_settings().stripe_secret_key = "sk_test_x"
    get_settings().stripe_price_id = None
    assert client.post("/internal/billing/checkout", json=CHECKOUT_BODY,
                       headers=INTERNAL).status_code == 503


def webhook(client, monkeypatch, event_type, obj):
    monkeypatch.setattr(
        stripe.Webhook, "construct_event",
        lambda payload, sig, secret: {"type": event_type,
                                      "data": {"object": obj}},
    )
    return client.post("/webhooks/stripe", content=b"{}",
                       headers={"Stripe-Signature": "sig"})


def test_webhook_checkout_completed_activates(client_and_db, monkeypatch):
    client, factory = client_and_db
    res = webhook(client, monkeypatch, "checkout.session.completed",
                  {"client_reference_id": "1", "customer": "cus_new"})
    assert res.status_code == 200
    assert user_row(factory, 1) == ("cus_new", "active")


def test_webhook_subscription_lifecycle(client_and_db, monkeypatch):
    client, factory = client_and_db
    webhook(client, monkeypatch, "customer.subscription.updated",
            {"customer": "cus_existing", "status": "past_due"})
    assert user_row(factory, 2) == ("cus_existing", "past_due")
    webhook(client, monkeypatch, "customer.subscription.deleted",
            {"customer": "cus_existing", "status": "canceled"})
    assert user_row(factory, 2) == ("cus_existing", "canceled")
    # unknown customer and unhandled event types are acknowledged, not errors
    assert webhook(client, monkeypatch, "customer.subscription.updated",
                   {"customer": "cus_ghost", "status": "active"}).status_code == 200
    assert webhook(client, monkeypatch, "invoice.paid", {}).status_code == 200


def test_webhook_rejects_bad_signature(client_and_db, monkeypatch):
    client, _ = client_and_db

    def raise_bad(payload, sig, secret):
        raise stripe.SignatureVerificationError("bad", sig)

    monkeypatch.setattr(stripe.Webhook, "construct_event", raise_bad)
    res = client.post("/webhooks/stripe", content=b"{}",
                      headers={"Stripe-Signature": "forged"})
    assert res.status_code == 400
