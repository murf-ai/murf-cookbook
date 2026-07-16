from __future__ import annotations

import logging
import random
from typing import Annotated

from livekit.agents import RunContext, function_tool, get_job_context
from pydantic import Field

import mock_data
from outcome_log import OutcomeLog

logger = logging.getLogger(__name__)


def _get_outcome_log() -> OutcomeLog | None:
    job_ctx = get_job_context(required=False)
    if job_ctx:
        return job_ctx.proc.userdata.get("outcome_log")
    return None


@function_tool()
async def verify_borrower_identity(
    mobile_last_four: Annotated[
        str,
        Field(description="The last four digits of the borrower's registered mobile number."),
    ],
    account_last_four: Annotated[
        str,
        Field(description="The last four digits of the borrower's account number."),
    ],
    context: RunContext,
) -> str:
    """Verify the borrower's identity using the last four digits of both their registered mobile number and their account number."""
    _ = context
    outcome_log = _get_outcome_log()
    if mock_data.is_identity_match(mobile_last_four, account_last_four):
        if outcome_log is not None:
            outcome_log.identity_verified = True
        logger.info("Identity verification succeeded")
        # Return the real amount + due date here so the model has ground truth the
        # instant it verifies. The prompt rebuild that injects these only fires on the
        # NEXT user turn, so without this the model would invent an amount/date when it
        # continues to the disclosure step in the same turn.
        cfg = mock_data._effective_config()
        return (
            "Thank you, your identity has been confirmed. "
            f"The amount due is {cfg['amountDueFormatted']} and the due date is {cfg['dueDate']}. "
            "State exactly these values — do not change or invent any figures."
        )
    logger.info("Identity verification failed — digits did not match")
    return (
        "I'm sorry, those details don't match what we have on file. "
        "Could you please give me the last four digits of your registered mobile number "
        "and your account number again?"
    )


@function_tool()
async def send_payment_link(
    context: RunContext,
) -> str:
    """Send the official payment link to the borrower's registered mobile number."""
    _ = context
    outcome_log = _get_outcome_log()
    if outcome_log is not None and not outcome_log.identity_verified:
        return "Cannot send link before identity is verified."
    cfg = mock_data._effective_config()
    if not cfg.get("paymentLinkEnabled"):
        return "Payment link sending is not enabled."
    if outcome_log is not None:
        outcome_log.payment_link_sent = True
    logger.info("Payment link sent to registered mobile number")
    return (
        "I've just sent the payment link to the registered mobile number on file. "
        "Please check your messages."
    )


@function_tool()
async def log_promise_to_pay(
    promise_date: Annotated[
        str,
        Field(description="The date the borrower said they will make the payment."),
    ],
    context: RunContext,
) -> str:
    """Record the borrower's commitment to pay by a specific date."""
    _ = context
    outcome_log = _get_outcome_log()
    if outcome_log is not None:
        outcome_log.promise_to_pay_date = promise_date
        outcome_log.outcome = "promise_to_pay"
    logger.info("Promise to pay recorded: %s", promise_date)
    return f"Thank you. I've noted that you plan to make the payment by {promise_date}."


@function_tool()
async def create_dispute_ticket(
    context: RunContext,
) -> str:
    """Create a dispute ticket when the borrower disputes the payment or amount."""
    _ = context
    outcome_log = _get_outcome_log()
    ticket_id = "TKT-" + "".join(str(random.randint(0, 9)) for _ in range(6))
    if outcome_log is not None:
        outcome_log.dispute_detected = True
        outcome_log.payment_reminder_stopped = True
        outcome_log.ticket_created = True
        outcome_log.future_automated_reminders_paused = True
        outcome_log.human_handoff_required = True
        outcome_log.outcome = "payment_dispute"
        outcome_log.ticket_id = ticket_id
    logger.info("Dispute ticket created: %s", ticket_id)
    return (
        f"I've raised a dispute ticket with reference {ticket_id}. "
        "A member of our team will follow up with you shortly to resolve this."
    )


@function_tool()
async def flag_hardship(
    reason: Annotated[
        str,
        Field(description="Brief reason the borrower gave for their hardship."),
    ],
    context: RunContext,
) -> str:
    """Flag the account for hardship and arrange a human callback."""
    _ = context
    outcome_log = _get_outcome_log()
    if outcome_log is not None:
        outcome_log.hardship_detected = True
        outcome_log.payment_reminder_stopped = True
        outcome_log.human_callback_requested = True
        outcome_log.human_handoff_required = True
        outcome_log.outcome = "hardship_detected"
    logger.info("Hardship flagged: %s", reason)
    return (
        "I understand, and I'm truly sorry to hear that. "
        "I've flagged your account and a member of our team will call you back to discuss your options."
    )


@function_tool()
async def end_call_wrong_person(
    context: RunContext,
) -> str:
    """End the call safely when the person is not the intended borrower."""
    _ = context
    outcome_log = _get_outcome_log()
    if outcome_log is not None:
        outcome_log.identity_verified = False
        outcome_log.amount_disclosed = False
        outcome_log.outcome = "identity_mismatch"
    logger.info("Call ended — wrong person or identity mismatch")
    return "I apologise for the interruption. Have a good day."
