# Outbound call flow:
#   trigger call → LiveKit create_room + create_dispatch (with phone metadata)
#   → agent entrypoint → session.start() → create_sip_participant via Twilio outbound trunk
#   → user's phone rings → user answers → 200 OK immediately (agent already ready)
#   → AgentSession (STT → LLM → TTS(Murf))
#
# Inbound fallback (no phone_number in metadata):
#   SIP INVITE → inbound trunk → dispatch rule → agent entrypoint → _greet_phone_caller

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
)
from livekit.agents.llm import ChatContext
from livekit.plugins import deepgram, google, openai, silero
from livekit.plugins import murf

import config  # validates required env vars at import time
from guardrails import GuardrailEngine
from mock_data import get_config
from outcome_log import OutcomeLog
from prompts.payment_prompt import build_payment_prompt
from state_machine import CallState, CallStateMachine
from tools.handoff import transfer_to_human
from tools.payment_tools import (
    create_dispute_ticket,
    end_call_wrong_person,
    flag_hardship,
    log_promise_to_pay,
    send_payment_link,
    verify_borrower_identity,
)
from tools.transcript import (
    CallSession,
    infer_intent_from_turns,
    register_call_session,
    save_transcript_local,
    unregister_call_session,
)
from tools.whatsapp import send_post_call_whatsapp
from livekit.agents.voice.events import ConversationItemAddedEvent, UserInputTranscribedEvent

load_dotenv()

cfg = get_config()
# MURF_VOICE_ID in the .env overrides the agentVoice in scenario_config.json.
_VOICE = config.MURF_VOICE_ID or cfg["agentVoice"]
_voice_parts = _VOICE.split("-")
# Murf voice IDs look like "en-US-natalie"; the locale is the first two segments.
_LOCALE = "-".join(_voice_parts[:2])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("payment-agent")
logger.setLevel(logging.INFO)

# Suppress noisy HTTP client debug logging
logging.getLogger("httpx").setLevel(logging.WARNING)


def _sip_caller_phone(participant: rtc.RemoteParticipant) -> str | None:
    if participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
        return None
    return participant.attributes.get("sip.phoneNumber") or participant.identity


async def _resolve_caller_phone(ctx: JobContext, is_phone: bool) -> str | None:
    if not is_phone:
        return None

    # Only check participants already in the room — don't block session startup
    # waiting for the SIP leg.  _greet_phone_caller handles the wait.
    for participant in ctx.room.remote_participants.values():
        phone = _sip_caller_phone(participant)
        if phone:
            return phone

    return None


def _derive_scenario(outcome_log: OutcomeLog, sm: CallStateMachine) -> str:
    """Derive the call scenario from what actually happened in the conversation,
    rather than trusting a pre-set value from the config/metadata."""
    if sm.current_state == CallState.WRONG_PERSON_END:
        return "wrong_person"
    if outcome_log.hardship_detected:
        return "hardship"
    if outcome_log.dispute_detected:
        return "already_paid"
    return "normal_reminder"


def _update_agent_instructions(
    session: AgentSession,
    call_cfg: dict,
    identity_verified: bool,
    sm: CallStateMachine,
) -> None:
    new_prompt = build_payment_prompt(
        call_cfg, identity_verified, sm.current_state.value, sm.allowed_actions
    )
    asyncio.create_task(session.current_agent.update_instructions(new_prompt))


# ── Agent ──────────────────────────────────────────────────────────────────────

class PaymentAgent(Agent):
    def __init__(self, instructions: str, opening_line: str) -> None:
        chat_ctx = ChatContext()
        chat_ctx.add_message(role="assistant", content=opening_line)
        super().__init__(
            instructions=instructions,
            chat_ctx=chat_ctx,
            tools=[
                verify_borrower_identity,
                send_payment_link,
                log_promise_to_pay,
                create_dispute_ticket,
                flag_hardship,
                end_call_wrong_person,
                transfer_to_human,
            ],
        )


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()
    proc.userdata["tts"] = murf.TTS(voice=_VOICE, locale=_LOCALE, streaming=True)


def _is_phone_room(room_name: str) -> bool:
    return room_name.startswith("payment-") and not room_name.startswith("payment-test-")


def _get_job_metadata(ctx: JobContext) -> dict:
    """Parse the full dispatch metadata dict (set by run.py)."""
    metadata = getattr(ctx.job, "metadata", None)
    if not metadata:
        return {}
    try:
        return json.loads(metadata)
    except (json.JSONDecodeError, AttributeError, TypeError):
        return {}


def _get_job_phone(ctx: JobContext) -> str | None:
    return _get_job_metadata(ctx).get("phone_number")


async def _dial_and_greet(
    ctx: JobContext,
    session: AgentSession,
    t0: float,
    opening_line: str,
    phone_number: str,
) -> None:
    """Outbound flow: dial the user, wait until they answer, then greet with zero ringback."""
    from livekit import api as lk_api

    trunk_id = os.environ.get("LIVEKIT_SIP_OUTBOUND_TRUNK_ID", "")
    if not trunk_id:
        logger.error("LIVEKIT_SIP_OUTBOUND_TRUNK_ID not set — cannot dial outbound")
        return

    lk = lk_api.LiveKitAPI(
        url=os.environ["LIVEKIT_URL"],
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )
    try:
        logger.info("Dialing %s (trunk %s)...", phone_number, trunk_id)
        await lk.sip.create_sip_participant(
            lk_api.CreateSIPParticipantRequest(
                sip_trunk_id=trunk_id,
                sip_call_to=phone_number,
                room_name=ctx.room.name,
                participant_identity="phone-user",
                wait_until_answered=True,
            )
        )
        logger.info("User answered at %.1fs", time.monotonic() - t0)
    except Exception:
        logger.exception("Outbound SIP call failed")
        return
    finally:
        await lk.aclose()

    # Participant joins as soon as user answers — find them (may need a brief moment)
    participant: rtc.RemoteParticipant | None = ctx.room.remote_participants.get("phone-user")
    if participant is None:
        try:
            participant = await asyncio.wait_for(ctx.wait_for_participant(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.error("SIP participant didn't appear after answering")
            return

    # Wait for the participant's audio track to be subscribed (RTP media path established).
    # SIP 200 OK fires before the media is flowing, so we must not speak until the track
    # is confirmed subscribed or the first words are dropped.
    track_ready = asyncio.Event()

    def _on_track_subscribed(
        track: rtc.Track,
        _publication: rtc.RemoteTrackPublication,
        remote_participant: rtc.RemoteParticipant,
    ) -> None:
        if remote_participant.identity == participant.identity and track.kind == rtc.TrackKind.KIND_AUDIO:
            track_ready.set()

    ctx.room.on("track_subscribed", _on_track_subscribed)
    for pub in participant.track_publications.values():
        if pub.subscribed and pub.track and pub.track.kind == rtc.TrackKind.KIND_AUDIO:
            track_ready.set()
            break

    try:
        await asyncio.wait_for(track_ready.wait(), timeout=3.0)
        logger.info("MEDIA: caller audio track subscribed at %.1fs", time.monotonic() - t0)
    except asyncio.TimeoutError:
        # Inbound track event didn't fire — the media path may still be coming up.
        # Don't burn another 2s of dead air; greet now after a brief settle.
        logger.warning("MEDIA: caller audio track NOT detected in 3s (proceeding)")
    finally:
        ctx.room.off("track_subscribed", _on_track_subscribed)

    # Short, consistent settle so the SIP RTP path + LiveKit egress are flowing
    # before we push the first greeting frame. Whether or not the inbound track
    # fired, the outbound bridge needs a moment or the first audio is choppy.
    await asyncio.sleep(0.7)

    # Play the greeting BEFORE calling set_participant() so that STT is not yet active.
    # set_participant() activates the input pipeline (VAD + STT); starting it during the
    # greeting causes transcriptions that interrupt or break up the audio.
    handle = session.say(opening_line, allow_interruptions=False)
    logger.info("Greeting started at %.1fs", time.monotonic() - t0)
    await asyncio.wait_for(handle.wait_for_playout(), timeout=60.0)
    logger.info("Opening greeting played at %.1fs", time.monotonic() - t0)

    # Activate STT so the agent can listen to the user's spoken reply.
    session.room_io.set_participant(participant.identity)
    logger.info("STT activated at %.1fs", time.monotonic() - t0)


async def _greet_phone_caller(
    ctx: JobContext,
    session: AgentSession,
    t0: float,
    opening_line: str,
) -> None:
    """Inbound fallback: SIP participant created by dispatch rule, greet when they join."""
    participant: rtc.RemoteParticipant | None = None
    for p in ctx.room.remote_participants.values():
        participant = p
        logger.info("Caller already in room: %s (%s)", p.identity, rtc.ParticipantKind.Name(p.kind))
        break

    if participant is None:
        try:
            participant = await asyncio.wait_for(ctx.wait_for_participant(), timeout=20.0)
            logger.info(
                "Caller joined: %s at %.1fs",
                participant.identity,
                time.monotonic() - t0,
            )
        except asyncio.TimeoutError:
            logger.error("No caller in %s after 20s", ctx.room.name)
            return

    handle = session.say(opening_line, allow_interruptions=False)
    logger.info("Greeting started at %.1fs", time.monotonic() - t0)
    await asyncio.wait_for(handle.wait_for_playout(), timeout=60.0)
    logger.info("Opening greeting played at %.1fs", time.monotonic() - t0)

    session.room_io.set_participant(participant.identity)
    logger.info("STT activated at %.1fs", time.monotonic() - t0)


async def _loop_health_monitor(t0: float, stop: asyncio.Event) -> None:
    """Detect event-loop starvation / CPU saturation during the call.

    Schedules a 0.25s sleep and measures how late the wake-up actually is.
    On a healthy loop the lag is ~0ms; if audio is stretched/choppy because the
    loop is blocked, the lag spikes to hundreds of ms. Also samples process and
    system CPU so we can tell starvation (high lag) from a slow network.
    """
    import psutil

    proc = psutil.Process()
    proc.cpu_percent(None)
    psutil.cpu_percent(None)
    interval = 0.25
    worst = 0.0
    while not stop.is_set():
        start = time.monotonic()
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass
        lag_ms = (time.monotonic() - start - interval) * 1000.0
        worst = max(worst, lag_ms)
        if lag_ms > 150:  # anything above ~150ms will audibly break up audio
            logger.warning(
                "LOOP LAG %.0fms at %.1fs  (proc CPU %.0f%%, system CPU %.0f%%) "
                "— event loop is blocked; this is what breaks up the audio",
                lag_ms, time.monotonic() - t0,
                proc.cpu_percent(None), psutil.cpu_percent(None),
            )
    logger.info("LOOP monitor stopped — worst lag observed: %.0fms", worst)


async def entrypoint(ctx: JobContext) -> None:
    t0 = time.monotonic()
    is_phone = _is_phone_room(ctx.room.name)

    await ctx.connect(
        auto_subscribe=AutoSubscribe.AUDIO_ONLY if is_phone else AutoSubscribe.SUBSCRIBE_ALL,
    )
    logger.info("Connected to %s (%.1fs)", ctx.room.name, time.monotonic() - t0)
 
    # Diagnostic: watch for event-loop starvation, which stretches/breaks audio.
    _loop_stop = asyncio.Event()
    _loop_mon_task = asyncio.create_task(_loop_health_monitor(t0, _loop_stop))
    ctx.room.on("disconnected", lambda *_: _loop_stop.set())

    # Diagnostic: watch the laptop↔LiveKit media link. If our outbound audio is
    # garbled despite a healthy event loop, the WebRTC/UDP uplink is the cause —
    # POOR/LOST quality or reconnecting here is the smoking gun.
    _CQ_NAME = {0: "POOR", 1: "GOOD", 2: "EXCELLENT", 3: "LOST"}
    _local_id = ctx.room.local_participant.identity

    def _on_cq(participant: rtc.Participant, quality) -> None:
        who = "AGENT→cloud uplink" if participant.identity == _local_id else f"{participant.identity}"
        name = _CQ_NAME.get(int(quality), str(quality))
        log = logger.warning if int(quality) in (0, 3) else logger.info
        log("NET: connection quality %s = %s (%.1fs)", who, name, time.monotonic() - t0)

    ctx.room.on("connection_quality_changed", _on_cq)
    ctx.room.on("reconnecting", lambda *_: logger.warning("NET: RECONNECTING to LiveKit (%.1fs)", time.monotonic() - t0))
    ctx.room.on("reconnected", lambda *_: logger.warning("NET: reconnected to LiveKit (%.1fs)", time.monotonic() - t0))

    # Start from the on-disk config, then overlay per-call fields from dispatch
    # metadata (populated by run.py for both single and campaign calls).
    call_cfg = get_config()
    job_meta = _get_job_metadata(ctx)
    if job_meta.get("customer_name"):
        call_cfg = {
            **call_cfg,
            "customerName":              job_meta["customer_name"],
            "amountDue":                 str(job_meta.get("amount_due", call_cfg["amountDue"])),
            "amountDueFormatted":        job_meta.get("amount_due_formatted", call_cfg["amountDueFormatted"]),
            "dueDate":                   job_meta.get("due_date", call_cfg["dueDate"]),
            "daysPastDue":               int(job_meta.get("days_past_due", call_cfg["daysPastDue"])),
            "accountEnding":             str(job_meta.get("account_ending", call_cfg["accountEnding"])),
            "registeredMobileLastFour":  str(job_meta.get("registered_mobile_last_four", call_cfg["registeredMobileLastFour"])),
            "scenario":                  job_meta.get("scenario", call_cfg["scenario"]),
        }

    # Bind this call's config so parallel campaigns each see their own data
    # (mock_data._effective_config() reads this context var instead of the file).
    from mock_data import set_call_context_config
    set_call_context_config(call_cfg)

    outcome_log = OutcomeLog(scenario=call_cfg["scenario"])
    ctx.proc.userdata["outcome_log"] = outcome_log

    sm = CallStateMachine()
    guardrails = GuardrailEngine()
    ctx.proc.userdata["state_machine"] = sm
    ctx.proc.userdata["guardrails"] = guardrails
    identity_verified = False

    # ── Pre-call check ──────────────────────────────────────────────────────────
    can_proceed, block_reason = guardrails.check_pre_call(call_cfg["scenario"])
    if not can_proceed:
        logger.warning("Call blocked: %s", block_reason)
        outcome_log.outcome = "call_blocked"
        outcome_log.human_handoff_required = True
        outcome_log.save_to_file()
        return

    outcome_log.call_started = True
    outcome_log.recording_disclosure_played = True  # opening_line always includes the disclosure

    tts_instance = ctx.proc.userdata.get("tts") or murf.TTS(voice=_VOICE, locale=_LOCALE)

    session = AgentSession(
        stt=openai.STT(model="gpt-realtime-whisper", use_realtime=True, language="en", api_key=config.OPENAI_API_KEY) if config.STT_PROVIDER == "openai"
        else deepgram.STT(model="nova-3", language="en-IN"),
        llm=openai.LLM(model="gpt-4o-mini", api_key=config.OPENAI_API_KEY) if config.LLM_PROVIDER == "openai"
        else google.LLM(model="gemini-2.5-flash", api_key=config.GOOGLE_API_KEY),
        tts=tts_instance,
        vad=ctx.proc.userdata["vad"],
    )

    # Outbound: phone number comes from dispatch metadata.
    # Inbound fallback: extract from SIP participant attributes.
    outbound_phone = _get_job_phone(ctx) if is_phone else None
    caller_phone = outbound_phone or await _resolve_caller_phone(ctx, is_phone)

    sm.transition(CallState.OPENING_DISCLOSURE)
    prompt = build_payment_prompt(call_cfg, identity_verified, sm.current_state.value, sm.allowed_actions)
    opening_line = (
        f"Hello, this is {call_cfg['agentName']}, an automated payment assistance agent from "
        f"{call_cfg['companyName']}. This call may be recorded for quality and compliance. "
        f"Am I speaking with {call_cfg['customerName']}?"
    )

    log_phone = caller_phone.strip() if caller_phone else "unknown"
    call_session = CallSession(phone=log_phone, name=call_cfg["customerName"])
    register_call_session(ctx.room.name, call_session)
    transcript_saved = False

    async def _finalize_transcript() -> None:
        nonlocal transcript_saved
        if transcript_saved:
            return
        transcript_saved = True
        infer_intent_from_turns(call_session)
        if outcome_log.outcome != "unknown":
            call_session.call_outcome = outcome_log.outcome
        elif call_session.call_outcome == "unknown" and outcome_log.payment_link_sent:
            call_session.call_outcome = "payment_link_sent"
        outcome_log.scenario = _derive_scenario(outcome_log, sm)
        outcome_log.save_to_file()
        save_transcript_local(call_session)
        await send_post_call_whatsapp(outcome_log, call_session, call_cfg)
        unregister_call_session(ctx.room.name)

    def _on_room_disconnected(*_args: object) -> None:
        asyncio.create_task(_finalize_transcript())

    ctx.room.on("disconnected", _on_room_disconnected)

    def _process_user_turn(utterance: str) -> None:
        """Apply state machine transitions and record a user turn. Called from STT."""
        nonlocal identity_verified
        if not utterance:
            return

        if sm.current_state in (CallState.OPENING_DISCLOSURE, CallState.IDENTITY_VERIFICATION):
            if guardrails.check_wrong_person(utterance, call_cfg["customerName"]):
                sm.transition(CallState.WRONG_PERSON_END)
                _update_agent_instructions(session, call_cfg, identity_verified, sm)

        if not sm.is_terminal():
            stop, reason = guardrails.should_stop_payment_flow(utterance)
            if stop:
                if reason == "dispute":
                    sm.transition(CallState.DISPUTE_INTAKE)
                elif reason == "hardship":
                    sm.transition(CallState.HARDSHIP_ESCALATION)
                elif reason in ("human_requested", "stop_calling"):
                    sm.transition(CallState.HUMAN_HANDOFF)
                _update_agent_instructions(session, call_cfg, identity_verified, sm)

        if sm.current_state == CallState.OPENING_DISCLOSURE:
            sm.transition(CallState.IDENTITY_VERIFICATION)
            _update_agent_instructions(session, call_cfg, identity_verified, sm)

        if (
            outcome_log.identity_verified
            and not identity_verified
            and sm.current_state == CallState.IDENTITY_VERIFICATION
        ):
            identity_verified = True
            outcome_log.amount_disclosed = True
            sm.transition(CallState.PAYMENT_CONTEXT)
            _update_agent_instructions(session, call_cfg, identity_verified, sm)

        call_session.add_turn("user", utterance)

    @session.on("user_input_transcribed")
    def on_user_input_transcribed(event: UserInputTranscribedEvent) -> None:
        if event.is_final and event.transcript:
            _process_user_turn(event.transcript)

    @session.on("conversation_item_added")
    def on_conversation_item_added(event: ConversationItemAddedEvent) -> None:
        item = event.item
        if item.type == "message" and item.role == "assistant":
            text = item.text_content
            if text:
                prohibited, phrase = guardrails.is_prohibited_language(text)
                if prohibited:
                    logger.warning(
                        "GUARDRAIL VIOLATION — prohibited language in agent output: %r", phrase
                    )
                call_session.add_turn("agent", text)

    await session.start(PaymentAgent(prompt, opening_line), room=ctx.room)
    logger.info("Session started (%.1fs)", time.monotonic() - t0)

    if is_phone:
        try:
            if outbound_phone:
                await _dial_and_greet(ctx, session, t0, opening_line, outbound_phone)
            else:
                await _greet_phone_caller(ctx, session, t0, opening_line)
        except asyncio.TimeoutError:
            logger.error("Phone call timed out")
        except Exception:
            logger.exception("Phone call failed")

    while ctx.room.isconnected():
        await asyncio.sleep(0.25)

    await _finalize_transcript()
    logger.info("Room %s disconnected", ctx.room.name)


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name="payment-agent",
            num_idle_processes=1,
        )
    )
