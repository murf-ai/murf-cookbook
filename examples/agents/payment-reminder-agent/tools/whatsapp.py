"""
Post-call WhatsApp confirmations via Twilio.

Sends a summary of the action taken after a call ends, unless the call dropped,
no action was recorded, or the callee was the wrong person.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import config
from outcome_log import OutcomeLog

if TYPE_CHECKING:
    from tools.transcript import CallSession

logger = logging.getLogger(__name__)

ACTIONABLE_OUTCOMES = frozenset({
    "promise_to_pay",
    "payment_dispute",
    "hardship_detected",
    "transferred_to_human",
})

SKIP_OUTCOMES = frozenset({
    "identity_mismatch",
    "call_blocked",
    "unknown",
})


def _user_spoke(session: CallSession) -> bool:
    return any(t.role == "user" and t.text.strip() for t in session.turns)


def _has_recorded_action(outcome_log: OutcomeLog, session: CallSession) -> bool:
    if outcome_log.outcome in ACTIONABLE_OUTCOMES:
        return True
    if outcome_log.payment_link_sent:
        return True
    if outcome_log.ticket_created:
        return True
    if outcome_log.hardship_detected:
        return True
    if outcome_log.human_callback_requested:
        return True
    if session.call_outcome == "transferred_to_human":
        return True
    return False


def should_send_whatsapp(outcome_log: OutcomeLog, session: CallSession) -> bool:
    """Return True when a post-call WhatsApp confirmation should be sent."""
    if outcome_log.outcome in SKIP_OUTCOMES and not _has_recorded_action(outcome_log, session):
        return False

    if outcome_log.outcome == "identity_mismatch":
        return False
    if session.intent == "wrong_person":
        return False
    if outcome_log.outcome == "call_blocked":
        return False

    # Call dropped — borrower never spoke (no answer, immediate hangup, etc.)
    if not _user_spoke(session):
        return False

    if not _has_recorded_action(outcome_log, session):
        return False

    return True


def build_whatsapp_message(outcome_log: OutcomeLog, call_cfg: dict, session: CallSession) -> str:
    """Build the confirmation text for the borrower."""
    company = call_cfg.get("companyName", "NovaFin")
    name = call_cfg.get("customerName") or session.name or "there"
    amount = call_cfg.get("amountDueFormatted", call_cfg.get("amountDue", ""))

    if outcome_log.outcome == "promise_to_pay" or outcome_log.promise_to_pay_date:
        date = outcome_log.promise_to_pay_date or "the agreed date"
        return (
            f"Hi {name}, this is {company}. Following our call today, we've noted your "
            f"commitment to pay {amount} by {date}. Thank you."
        )

    if outcome_log.outcome == "payment_dispute" or outcome_log.ticket_created:
        ref = outcome_log.ticket_id or "your case"
        return (
            f"Hi {name}, this is {company}. We've registered your payment dispute "
            f"(reference {ref}). Our team will follow up with you shortly."
        )

    if outcome_log.outcome == "hardship_detected" or outcome_log.hardship_detected:
        return (
            f"Hi {name}, this is {company}. We've flagged your account for hardship review. "
            "A member of our team will call you back to discuss your options."
        )

    if (
        session.call_outcome == "transferred_to_human"
        or outcome_log.outcome == "transferred_to_human"
        or outcome_log.human_callback_requested
        or outcome_log.human_handoff_required
    ):
        return (
            f"Hi {name}, this is {company}. Following our call, your request has been "
            "escalated to our support team. Someone will be in touch shortly."
        )

    if outcome_log.payment_link_sent:
        return (
            f"Hi {name}, this is {company}. As discussed on our call, here is your "
            f"payment link for the outstanding balance of {amount}: "
            f"{call_cfg.get('paymentLinkUrl', 'please check your registered mobile number for the link')}."
        )

    return (
        f"Hi {name}, this is {company}. Thank you for speaking with us today regarding "
        f"your account. If you have any questions, please contact our support team."
    )


def _normalize_whatsapp_address(phone: str) -> str | None:
    cleaned = re.sub(r"[^\d+]", "", phone.strip())
    if not cleaned or cleaned == "unknown":
        return None
    if cleaned.startswith("whatsapp:"):
        return cleaned
    if not cleaned.startswith("+"):
        cleaned = f"+{cleaned}"
    return f"whatsapp:{cleaned}"


def send_whatsapp_message(phone: str, body: str, *, dry_run: bool = False) -> dict:
    """
    Send a WhatsApp message via Twilio.

    Returns a dict with keys: sent (bool), sid (str|None), reason (str|None), to (str|None).
    """
    to_addr = _normalize_whatsapp_address(phone)
    if not to_addr:
        return {"sent": False, "sid": None, "reason": "invalid_phone", "to": None}

    if dry_run:
        logger.info("WhatsApp dry-run to %s: %s", to_addr, body)
        return {"sent": False, "sid": None, "reason": "dry_run", "to": to_addr}

    if not config.whatsapp_enabled():
        logger.warning("WhatsApp not configured — message not sent to %s", to_addr)
        return {"sent": False, "sid": None, "reason": "not_configured", "to": to_addr}

    from_addr = config.TWILIO_WHATSAPP_FROM  # type: ignore[arg-type]

    try:
        from twilio.rest import Client

        client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
        message = client.messages.create(body=body, from_=from_addr, to=to_addr)
        logger.info("WhatsApp sent to %s (sid=%s)", to_addr, message.sid)
        return {"sent": True, "sid": message.sid, "reason": None, "to": to_addr}
    except Exception as exc:
        logger.error("WhatsApp send failed to %s: %s", to_addr, exc)
        return {"sent": False, "sid": None, "reason": str(exc), "to": to_addr}


async def send_post_call_whatsapp(
    outcome_log: OutcomeLog,
    session: CallSession,
    call_cfg: dict,
    *,
    dry_run: bool = False,
) -> dict | None:
    """
    Decide whether to send a post-call WhatsApp and send it if appropriate.

    Returns the send result dict, or None if skipped.
    """
    if not should_send_whatsapp(outcome_log, session):
        logger.info(
            "Skipping post-call WhatsApp (outcome=%s, intent=%s, user_turns=%d)",
            outcome_log.outcome,
            session.intent,
            sum(1 for t in session.turns if t.role == "user"),
        )
        return None

    body = build_whatsapp_message(outcome_log, call_cfg, session)

    import asyncio

    return await asyncio.to_thread(
        send_whatsapp_message,
        session.phone,
        body,
        dry_run=dry_run,
    )
