"""
SIP call transfer — forwards the live call to a human agent.
Uses LiveKit SIP REFER (cold transfer).
Called when the borrower requests a human or the agent must escalate.
"""

from __future__ import annotations

import logging
from typing import Annotated

from livekit import api, rtc
from livekit.agents import RunContext, function_tool, get_job_context
from pydantic import Field

import config
from outcome_log import OutcomeLog
from tools.transcript import get_call_session

logger = logging.getLogger(__name__)


def _normalize_tel(number: str) -> str:
    """Normalise to E.164 tel: URI."""
    cleaned = number.strip().replace(" ", "").replace("-", "")
    if cleaned.startswith("tel:"):
        cleaned = cleaned[4:]
    if not cleaned.startswith("+"):
        if cleaned.startswith("0"):
            cleaned = f"+91{cleaned[1:]}"
        elif len(cleaned) == 10 and cleaned.isdigit():
            cleaned = f"+91{cleaned}"
        else:
            cleaned = f"+{cleaned}"
    return f"tel:{cleaned}"


def _find_sip_participant_identity(room: rtc.Room) -> str | None:
    for participant in room.remote_participants.values():
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
            return participant.identity
    return None


async def transfer_call(
    room_name: str,
    sip_participant_identity: str,
    reason: str = "borrower request",
) -> bool:
    """
    Transfer the active SIP call to the configured human transfer number.
    Returns True on success, False on any failure. Never raises.
    """
    if not config.handoff_enabled():
        logger.debug("Handoff disabled — HUMAN_TRANSFER_NUMBER or LIVEKIT_SIP_URI not set")
        return False

    transfer_to = _normalize_tel(config.HUMAN_TRANSFER_NUMBER)  # type: ignore[arg-type]

    try:
        async with api.LiveKitAPI(
            url=config.LIVEKIT_URL,
            api_key=config.LIVEKIT_API_KEY,
            api_secret=config.LIVEKIT_API_SECRET,
        ) as lk_api:
            await lk_api.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=room_name,
                    participant_identity=sip_participant_identity,
                    transfer_to=transfer_to,
                    play_dialtone=False,
                )
            )

        logger.info("Call transferred to human agent, reason=%s", reason)
        return True
    except Exception as exc:
        logger.error("SIP transfer failed: %s", exc)
        return False


@function_tool()
async def transfer_to_human(
    reason: Annotated[
        str,
        Field(
            description=(
                "Why the borrower needs a human agent. "
                "e.g. 'borrower requested', 'dispute raised', 'hardship escalation', 'complaint'"
            )
        ),
    ],
    context: RunContext,
) -> str:
    """
    Transfer the call to a human support agent.
    Call this when:
    - The borrower explicitly asks to speak to a human
    - A payment dispute or complaint has been raised
    - A hardship situation requires human review
    - The borrower asks to stop automated calls
    reason: brief description of why the escalation is needed.
    """
    _ = context

    job_ctx = get_job_context(required=False)
    if not job_ctx:
        logger.warning("Transfer requested but no job context")
        return (
            "I wasn't able to complete the transfer right now. "
            "A team member will call you back shortly."
        )

    sip_identity = _find_sip_participant_identity(job_ctx.room)
    if not sip_identity:
        logger.warning("Transfer requested but no SIP participant found in room")
        return (
            "I wasn't able to complete the transfer right now. "
            "A team member will call you back shortly."
        )

    if not config.handoff_enabled():
        logger.info("Handoff disabled — HUMAN_TRANSFER_NUMBER not configured")
        return (
            "I've flagged this for human review. "
            "A team member from our support team will call you back shortly."
        )

    success = await transfer_call(
        room_name=job_ctx.room.name,
        sip_participant_identity=sip_identity,
        reason=reason,
    )

    if success:
        cs = get_call_session(job_ctx.room.name)
        if cs:
            cs.set_outcome(intent=cs.intent, outcome="transferred_to_human")

        outcome_log: OutcomeLog | None = job_ctx.proc.userdata.get("outcome_log")
        if outcome_log is not None:
            outcome_log.human_handoff_required = True
            outcome_log.outcome = "transferred_to_human"

        return "I'm transferring you to a human agent right now. Please hold for a moment."

    return (
        "I wasn't able to complete the transfer right now. "
        "A team member will call you back shortly."
    )
