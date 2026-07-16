"""Test post-call WhatsApp confirmations without placing a call.

Sends a real WhatsApp message by default via Twilio.

Usage:
  python scripts/test_whatsapp.py --outcome promise_to_pay --phone +910000000001
  python scripts/test_whatsapp.py --outcome hardship --dry-run
  python scripts/test_whatsapp.py --list-outcomes

Outcomes: promise_to_pay, dispute, hardship, escalation, payment_link,
          wrong_person, call_drop, no_action
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import config
from mock_data import get_config
from outcome_log import OutcomeLog
from tools.transcript import CallSession
from tools.whatsapp import (
    build_whatsapp_message,
    send_whatsapp_message,
    should_send_whatsapp,
)

SCENARIOS: dict[str, dict] = {
    "promise_to_pay": {
        "description": "Borrower committed to pay by a specific date",
        "outcome_log": {
            "outcome": "promise_to_pay",
            "identity_verified": True,
            "promise_to_pay_date": "July 5, 2026",
        },
        "turns": [
            ("agent", "Am I speaking with Aria?"),
            ("user", "Yes, this is Aria."),
            ("agent", "I've noted your payment commitment."),
        ],
        "expect_send": True,
    },
    "dispute": {
        "description": "Borrower disputed the payment — ticket created",
        "outcome_log": {
            "outcome": "payment_dispute",
            "identity_verified": True,
            "dispute_detected": True,
            "ticket_created": True,
            "ticket_id": "TKT-482910",
            "payment_reminder_stopped": True,
            "future_automated_reminders_paused": True,
            "human_handoff_required": True,
        },
        "turns": [
            ("agent", "Am I speaking with Aria?"),
            ("user", "Yes, but I already paid this."),
            ("agent", "I've raised a dispute ticket for you."),
        ],
        "expect_send": True,
    },
    "hardship": {
        "description": "Borrower flagged for hardship — callback arranged",
        "outcome_log": {
            "outcome": "hardship_detected",
            "identity_verified": True,
            "hardship_detected": True,
            "human_callback_requested": True,
            "human_handoff_required": True,
            "payment_reminder_stopped": True,
        },
        "turns": [
            ("agent", "Am I speaking with Aria?"),
            ("user", "Yes, I lost my job and cannot pay."),
            ("agent", "I've flagged your account for hardship review."),
        ],
        "expect_send": True,
    },
    "escalation": {
        "description": "Call transferred to a human agent",
        "outcome_log": {
            "outcome": "transferred_to_human",
            "identity_verified": True,
            "human_handoff_required": True,
        },
        "turns": [
            ("agent", "Am I speaking with Aria?"),
            ("user", "Yes, I need to speak to someone."),
            ("agent", "Transferring you now."),
        ],
        "call_outcome": "transferred_to_human",
        "expect_send": True,
    },
    "payment_link": {
        "description": "Payment link sent during the call",
        "outcome_log": {
            "outcome": "unknown",
            "identity_verified": True,
            "payment_link_sent": True,
        },
        "turns": [
            ("agent", "Am I speaking with Aria?"),
            ("user", "Yes, please send the link."),
            ("agent", "I've sent the payment link."),
        ],
        "expect_send": True,
    },
    "wrong_person": {
        "description": "Callee was not the intended borrower — no message",
        "outcome_log": {
            "outcome": "identity_mismatch",
            "identity_verified": False,
        },
        "turns": [
            ("agent", "Am I speaking with Aria?"),
            ("user", "Wrong number, no Aria here."),
            ("agent", "Sorry for the interruption."),
        ],
        "intent": "wrong_person",
        "expect_send": False,
    },
    "call_drop": {
        "description": "Call dropped before borrower spoke — no message",
        "outcome_log": {
            "outcome": "unknown",
            "call_started": True,
        },
        "turns": [
            ("agent", "Hello, this is Asha from NovaFin..."),
        ],
        "expect_send": False,
    },
    "no_action": {
        "description": "Conversation happened but no action recorded — no message",
        "outcome_log": {
            "outcome": "unknown",
            "identity_verified": True,
        },
        "turns": [
            ("agent", "Am I speaking with Aria?"),
            ("user", "Yes."),
            ("agent", "Could I have the last four digits?"),
            ("user", "Hang on..."),
        ],
        "expect_send": False,
    },
}


def _build_session(
    phone: str,
    cfg: dict,
    turns: list[tuple[str, str]],
    *,
    intent: str = "unknown",
    call_outcome: str = "unknown",
) -> CallSession:
    session = CallSession(phone=phone, name=cfg["customerName"])
    session.intent = intent
    session.call_outcome = call_outcome
    for role, text in turns:
        session.add_turn(role, text)  # type: ignore[arg-type]
    return session


def _build_outcome_log(fields: dict) -> OutcomeLog:
    log = OutcomeLog()
    for key, value in fields.items():
        setattr(log, key, value)
    return log


def divider(char: str = "-", width: int = 70) -> None:
    print(char * width)


async def _run_scenario(name: str, phone: str, *, dry_run: bool) -> int:
    spec = SCENARIOS[name]
    cfg = get_config()

    outcome_log = _build_outcome_log(spec["outcome_log"])
    session = _build_session(
        phone,
        cfg,
        spec["turns"],
        intent=spec.get("intent", "unknown"),
        call_outcome=spec.get("call_outcome", "unknown"),
    )

    will_send = should_send_whatsapp(outcome_log, session)
    message = build_whatsapp_message(outcome_log, cfg, session)

    divider("=")
    print(f"  WHATSAPP TEST: {name}")
    divider("=")
    print(f"  Scenario : {spec['description']}")
    print(f"  Phone    : {phone}")
    print(f"  Should send: {will_send} (expected: {spec['expect_send']})")
    divider()
    print("  Message:")
    for line in message.split(". "):
        if line.strip():
            print(f"    {line.strip()}{'' if line.endswith('.') else '.'}")
    divider()

    if will_send != spec["expect_send"]:
        print("  FAIL: send decision does not match expectation")
        return 1

    if not will_send:
        print("  OK — correctly skipped")
        return 0

    if dry_run:
        print(f"  DRY RUN — would send to whatsapp:{phone.lstrip('+') if phone.startswith('+') else phone}")
        return 0

    if not config.whatsapp_enabled():
        print("  ERROR: Twilio WhatsApp not configured.")
        print("  Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM in .env")
        return 1

    result = send_whatsapp_message(phone, message, dry_run=False)

    if result.get("sent"):
        print(f"  SENT — Twilio SID: {result['sid']}")
        print(f"  To: {result['to']}")
        return 0

    print(f"  NOT SENT — reason: {result.get('reason', 'unknown')}")
    return 1


async def _run_all(phone: str, *, dry_run: bool) -> int:
    failures = 0
    for name in SCENARIOS:
        code = await _run_scenario(name, phone, dry_run=dry_run)
        if code != 0:
            failures += 1
        print()
    print(f"{'All scenarios passed' if failures == 0 else f'{failures} scenario(s) failed'}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test post-call WhatsApp without placing a call (sends by default)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--outcome",
        choices=list(SCENARIOS.keys()),
        default="promise_to_pay",
        help="Simulated call outcome (default: promise_to_pay)",
    )
    parser.add_argument(
        "--phone",
        default="+910000000001",
        help="Recipient E.164 number (default: +910000000001)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the message without sending via Twilio",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run every scenario",
    )
    parser.add_argument(
        "--list-outcomes",
        action="store_true",
        help="List available test outcomes and exit",
    )
    args = parser.parse_args()

    if args.list_outcomes:
        print("Available test outcomes:\n")
        for name, spec in SCENARIOS.items():
            flag = "sends" if spec["expect_send"] else "skips"
            print(f"  {name:<16} [{flag}]  {spec['description']}")
        return

    if args.all:
        sys.exit(asyncio.run(_run_all(args.phone, dry_run=args.dry_run)))

    sys.exit(asyncio.run(_run_scenario(args.outcome, args.phone, dry_run=args.dry_run)))


if __name__ == "__main__":
    main()
