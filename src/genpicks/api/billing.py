"""Stripe billing: demo subscription checkout for the try-market paywall.

TEST MODE ONLY — this is a portfolio project; the checkout is framed as a
demo and must never carry live keys. All Stripe calls live on the API side
so the secret key never reaches the frontend deployment.

Flow: the Next.js server asks /internal/billing/checkout for a hosted
checkout URL and redirects the browser there; Stripe calls /webhooks/stripe
when the subscription changes state, which flips users.subscription_status —
the single source of truth the markets gating reads.
"""

import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from genpicks.api.deps import get_session, require_internal
from genpicks.config import get_settings
from genpicks.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


class CheckoutPayload(BaseModel):
    user_id: int
    success_url: str
    cancel_url: str


@router.post("/internal/billing/checkout", dependencies=[Depends(require_internal)])
def create_checkout(payload: CheckoutPayload, session: Session = Depends(get_session)):
    settings = get_settings()
    # demo checkout only: a live key would make this a real gambling-adjacent
    # payment flow, which this project must never be — refuse to start
    if (
        not settings.stripe_secret_key
        or not settings.stripe_secret_key.startswith("sk_test_")
        or not settings.stripe_price_id
    ):
        raise HTTPException(503, "billing not configured (test mode only)")
    user = session.get(User, payload.user_id)
    if user is None:
        raise HTTPException(404, "user not found")

    if user.stripe_customer_id is None:
        customer = stripe.Customer.create(
            api_key=settings.stripe_secret_key,
            email=user.email,
            name=user.name,
            metadata={"genpicks_user_id": str(user.id)},
        )
        user.stripe_customer_id = customer.id
        session.commit()

    checkout = stripe.checkout.Session.create(
        api_key=settings.stripe_secret_key,
        mode="subscription",
        customer=user.stripe_customer_id,
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        success_url=payload.success_url,
        cancel_url=payload.cancel_url,
        client_reference_id=str(user.id),
    )
    return {"url": checkout.url}


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, session: Session = Depends(get_session)):
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise HTTPException(503, "billing not configured")
    try:
        event = stripe.Webhook.construct_event(
            await request.body(),
            request.headers.get("stripe-signature", ""),
            settings.stripe_webhook_secret,
        )
    except (stripe.SignatureVerificationError, ValueError):
        raise HTTPException(400, "invalid signature")

    obj = event["data"]["object"]
    if event["type"] == "checkout.session.completed":
        # first activation: the checkout carries our user id back to us
        user = session.get(User, int(obj["client_reference_id"]))
        if user is not None:
            user.stripe_customer_id = obj["customer"]
            user.subscription_status = "active"
            session.commit()
    elif event["type"] in (
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        # later lifecycle changes only carry the customer id
        user = session.scalar(
            select(User).where(User.stripe_customer_id == obj["customer"])
        )
        if user is not None:
            user.subscription_status = (
                "canceled"
                if event["type"] == "customer.subscription.deleted"
                else obj["status"]
            )
            session.commit()
    else:
        logger.info("unhandled stripe event type %s", event["type"])
    return {"received": True}
