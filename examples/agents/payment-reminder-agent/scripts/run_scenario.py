"""Scenario runner — shows what the payment agent would do for each scenario.

Usage:
  python scripts/run_scenario.py --scenario normal_reminder
  python scripts/run_scenario.py --scenario grievance_pending

Valid scenarios: normal_reminder, already_paid, hardship, wrong_person, grievance_pending
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from guardrails import GuardrailEngine
from mock_data import get_config
from prompts.payment_prompt import build_payment_prompt
from state_machine import CallState, CallStateMachine

VALID_SCENARIOS = [
    "normal_reminder",
    "already_paid",
    "hardship",
    "wrong_person",
    "grievance_pending",
]

EXPECTED_OUTCOMES: dict[str, dict] = {
    "normal_reminder": {
        "scenario": "normal_reminder",
        "call_started": True,
        "identity_verified": True,
        "amount_disclosed": True,
        "payment_link_sent": True,
        "promise_to_pay_date": "June 25, 2026",
        "dispute_detected": False,
        "hardship_detected": False,
        "human_handoff_required": False,
        "outcome": "promise_to_pay",
    },
    "already_paid": {
        "scenario": "already_paid",
        "call_started": True,
        "identity_verified": True,
        "dispute_detected": True,
        "ticket_created": True,
        "future_automated_reminders_paused": True,
        "human_handoff_required": True,
        "payment_reminder_stopped": True,
        "outcome": "payment_dispute",
    },
    "hardship": {
        "scenario": "hardship",
        "call_started": True,
        "identity_verified": True,
        "hardship_detected": True,
        "human_callback_requested": True,
        "human_handoff_required": True,
        "payment_reminder_stopped": True,
        "outcome": "hardship_detected",
    },
    "wrong_person": {
        "scenario": "wrong_person",
        "call_started": True,
        "identity_verified": False,
        "amount_disclosed": False,
        "outcome": "identity_mismatch",
    },
    "grievance_pending": {
        "scenario": "grievance_pending",
        "call_started": False,
        "human_handoff_required": True,
        "outcome": "call_blocked",
    },
}

EXPECTED_STATE_PATHS: dict[str, list[CallState]] = {
    "normal_reminder": [
        CallState.PRE_CALL_CHECK,
        CallState.OPENING_DISCLOSURE,
        CallState.IDENTITY_VERIFICATION,
        CallState.PAYMENT_CONTEXT,
        CallState.INTENT_CLASSIFICATION,
        CallState.SEND_PAYMENT_LINK,
        CallState.PROMISE_TO_PAY,
        CallState.CALL_SUMMARY,
    ],
    "already_paid": [
        CallState.PRE_CALL_CHECK,
        CallState.OPENING_DISCLOSURE,
        CallState.DISPUTE_INTAKE,
        CallState.HUMAN_HANDOFF,
    ],
    "hardship": [
        CallState.PRE_CALL_CHECK,
        CallState.OPENING_DISCLOSURE,
        CallState.HARDSHIP_ESCALATION,
        CallState.HUMAN_HANDOFF,
    ],
    "wrong_person": [
        CallState.PRE_CALL_CHECK,
        CallState.OPENING_DISCLOSURE,
        CallState.WRONG_PERSON_END,
    ],
    "grievance_pending": [
        CallState.PRE_CALL_CHECK,
    ],
}

SAMPLE_EXCHANGES: dict[str, list[tuple[str, str]]] = {
    "normal_reminder": [
        ("AGENT", "Hello, this is Asha, an automated payment assistance agent from NovaFin. "
                  "This call may be recorded for quality and compliance. Am I speaking with Ramesh?"),
        ("USER",  "Yes, this is Ramesh."),
        ("AGENT", "Could I ask for the last four digits of your registered mobile number "
                  "and the last four digits of your account number?"),
        ("USER",  "Mobile is 1 2 3 4, account is 4 3 2 1."),
        ("AGENT", "[calls verify_borrower_identity] Your identity has been confirmed. "
                  "You have an outstanding payment of Rs.8,390 due on June 5, 2026. "
                  "Would you like me to send the payment link to your registered number?"),
        ("USER",  "Yes, please send it."),
        ("AGENT", "[calls send_payment_link] I've sent the payment link to your registered mobile number. "
                  "Do you have a date in mind when you'd be able to make the payment?"),
        ("USER",  "I'll pay by June 25th."),
        ("AGENT", "[calls log_promise_to_pay] Thank you, Ramesh. I've noted that you plan to pay by June 25, 2026. "
                  "Have a good day, goodbye."),
    ],
    "already_paid": [
        ("AGENT", "Hello, this is Asha... Am I speaking with Ramesh?"),
        ("USER",  "Yes, but I already paid this amount last week."),
        ("AGENT", "[guardrail: dispute -> DISPUTE_INTAKE] [calls create_dispute_ticket] "
                  "I've raised a dispute ticket for you. Our team will follow up shortly."),
    ],
    "hardship": [
        ("AGENT", "Hello, this is Asha... Am I speaking with Ramesh?"),
        ("USER",  "Yes, but I lost my job and cannot pay right now."),
        ("AGENT", "[guardrail: hardship -> HARDSHIP_ESCALATION] [calls flag_hardship] "
                  "I'm truly sorry to hear that. I've flagged your account and a team member "
                  "will call you back to discuss your options."),
    ],
    "wrong_person": [
        ("AGENT", "Hello, this is Asha... Am I speaking with Ramesh?"),
        ("USER",  "Wrong number, there's no Ramesh here."),
        ("AGENT", "[guardrail: wrong person -> WRONG_PERSON_END] [calls end_call_wrong_person] "
                  "I apologise for the interruption. Have a good day, goodbye."),
    ],
    "grievance_pending": [],
}


def divider(char: str = "-", width: int = 60) -> None:
    print(char * width)


def section(title: str) -> None:
    print(f"\n{title}")
    divider()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Payment agent scenario runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--scenario",
        choices=VALID_SCENARIOS,
        default="normal_reminder",
        metavar="SCENARIO",
        help=f"One of: {', '.join(VALID_SCENARIOS)}",
    )
    args = parser.parse_args()

    cfg = copy.deepcopy(get_config())
    cfg["scenario"] = args.scenario

    guardrails = GuardrailEngine()

    print()
    divider("=")
    print(f"  SCENARIO RUNNER: {args.scenario.upper()}")
    divider("=")

    # Config
    section("CONFIG")
    for k, v in cfg.items():
        print(f"  {k}: {v!r}")

    # Pre-call check
    section("PRE-CALL CHECK")
    can_proceed, block_reason = guardrails.check_pre_call(args.scenario)
    if not can_proceed:
        print(f"  BLOCKED: {block_reason}")
        section("EXPECTED OUTCOME LOG")
        print(json.dumps(EXPECTED_OUTCOMES[args.scenario], indent=2, ensure_ascii=False))
        print()
        divider("=")
        return

    print(f"  OK — call may proceed (scenario={args.scenario!r})")

    # Expected state path
    section("EXPECTED STATE MACHINE PATH")
    path = EXPECTED_STATE_PATHS[args.scenario]
    print("  " + " -> ".join(s.value for s in path))

    # Opening line
    section("OPENING LINE")
    opening = (
        f"Hello, this is {cfg['agentName']}, an automated payment assistance agent from "
        f"{cfg['companyName']}. This call may be recorded for quality and compliance. "
        f"Am I speaking with {cfg['customerName']}?"
    )
    print(f"  {opening}")

    # Initial system prompt
    sm = CallStateMachine()
    sm.transition(CallState.OPENING_DISCLOSURE)
    prompt = build_payment_prompt(cfg, False, sm.current_state.value, sm.allowed_actions)
    section("INITIAL SYSTEM PROMPT (identity_verified=False)")
    for line in prompt.split("\n"):
        print(f"  {line}")

    # Sample exchanges
    exchanges = SAMPLE_EXCHANGES.get(args.scenario, [])
    if exchanges:
        section("EXPECTED EXCHANGES")
        for role, text in exchanges:
            label = f"  {role}:"
            print(f"{label:<9} {text}")

    # Expected outcome
    section("EXPECTED FINAL OUTCOME LOG")
    print(json.dumps(EXPECTED_OUTCOMES[args.scenario], indent=2, ensure_ascii=False))

    print()
    divider("=")


if __name__ == "__main__":
    main()
