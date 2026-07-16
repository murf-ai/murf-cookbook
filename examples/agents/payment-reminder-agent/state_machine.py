from __future__ import annotations

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class CallState(str, Enum):
    PRE_CALL_CHECK = "PRE_CALL_CHECK"
    OPENING_DISCLOSURE = "OPENING_DISCLOSURE"
    IDENTITY_VERIFICATION = "IDENTITY_VERIFICATION"
    PAYMENT_CONTEXT = "PAYMENT_CONTEXT"
    INTENT_CLASSIFICATION = "INTENT_CLASSIFICATION"
    SEND_PAYMENT_LINK = "SEND_PAYMENT_LINK"
    PROMISE_TO_PAY = "PROMISE_TO_PAY"
    DISPUTE_INTAKE = "DISPUTE_INTAKE"
    HARDSHIP_ESCALATION = "HARDSHIP_ESCALATION"
    WRONG_PERSON_END = "WRONG_PERSON_END"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"
    CALL_SUMMARY = "CALL_SUMMARY"


TERMINAL_STATES: frozenset[CallState] = frozenset(
    {CallState.WRONG_PERSON_END, CallState.HUMAN_HANDOFF, CallState.CALL_SUMMARY}
)

ALLOWED_ACTIONS: dict[CallState, list[str]] = {
    CallState.PRE_CALL_CHECK: [],
    CallState.OPENING_DISCLOSURE: [
        "introduce yourself and the company",
        "state the call may be recorded",
        "ask if speaking with the customer by name",
    ],
    CallState.IDENTITY_VERIFICATION: [
        "ask for the last four digits of the registered mobile number",
        "ask for the last four digits of the account number",
        "call verify_borrower_identity",
    ],
    CallState.PAYMENT_CONTEXT: [
        "state amount due and due date",
        "offer to send the payment link",
    ],
    CallState.INTENT_CLASSIFICATION: [
        "listen for payment intent, dispute, hardship, or stop-calling",
        "route to the appropriate next state",
    ],
    CallState.SEND_PAYMENT_LINK: [
        "call send_payment_link",
        "confirm the link was sent to the registered number",
    ],
    CallState.PROMISE_TO_PAY: [
        "ask for a commitment date",
        "call log_promise_to_pay",
    ],
    CallState.DISPUTE_INTAKE: [
        "call create_dispute_ticket",
        "stop all payment reminder language",
    ],
    CallState.HARDSHIP_ESCALATION: [
        "call flag_hardship",
        "do not pressure the borrower",
    ],
    CallState.WRONG_PERSON_END: [
        "call end_call_wrong_person",
        "apologise and end the call",
    ],
    CallState.HUMAN_HANDOFF: [
        "call transfer_to_human",
        "inform the borrower they are being transferred",
    ],
    CallState.CALL_SUMMARY: [
        "summarise the outcome",
        "thank the borrower and close the call politely",
    ],
}

VALID_TRANSITIONS: dict[CallState, set[CallState]] = {
    CallState.PRE_CALL_CHECK: {
        CallState.OPENING_DISCLOSURE,
    },
    CallState.OPENING_DISCLOSURE: {
        CallState.IDENTITY_VERIFICATION,
        CallState.WRONG_PERSON_END,
        CallState.DISPUTE_INTAKE,
        CallState.HARDSHIP_ESCALATION,
        CallState.HUMAN_HANDOFF,
    },
    CallState.IDENTITY_VERIFICATION: {
        CallState.PAYMENT_CONTEXT,
        CallState.WRONG_PERSON_END,
        CallState.DISPUTE_INTAKE,
        CallState.HARDSHIP_ESCALATION,
        CallState.HUMAN_HANDOFF,
    },
    CallState.PAYMENT_CONTEXT: {
        CallState.INTENT_CLASSIFICATION,
        CallState.DISPUTE_INTAKE,
        CallState.HARDSHIP_ESCALATION,
        CallState.HUMAN_HANDOFF,
    },
    CallState.INTENT_CLASSIFICATION: {
        CallState.SEND_PAYMENT_LINK,
        CallState.PROMISE_TO_PAY,
        CallState.DISPUTE_INTAKE,
        CallState.HARDSHIP_ESCALATION,
        CallState.HUMAN_HANDOFF,
        CallState.CALL_SUMMARY,
    },
    CallState.SEND_PAYMENT_LINK: {
        CallState.PROMISE_TO_PAY,
        CallState.CALL_SUMMARY,
        CallState.DISPUTE_INTAKE,
        CallState.HARDSHIP_ESCALATION,
        CallState.HUMAN_HANDOFF,
    },
    CallState.PROMISE_TO_PAY: {
        CallState.CALL_SUMMARY,
        CallState.HUMAN_HANDOFF,
    },
    CallState.DISPUTE_INTAKE: {
        CallState.HUMAN_HANDOFF,
        CallState.CALL_SUMMARY,
    },
    CallState.HARDSHIP_ESCALATION: {
        CallState.HUMAN_HANDOFF,
        CallState.CALL_SUMMARY,
    },
    CallState.WRONG_PERSON_END: set(),
    CallState.HUMAN_HANDOFF: set(),
    CallState.CALL_SUMMARY: set(),
}


class CallStateMachine:
    def __init__(self) -> None:
        self._state: CallState = CallState.PRE_CALL_CHECK
        self._history: list[str] = [CallState.PRE_CALL_CHECK.value]

    @property
    def current_state(self) -> CallState:
        return self._state

    @property
    def allowed_actions(self) -> list[str]:
        return list(ALLOWED_ACTIONS[self._state])

    def transition(self, new_state: CallState) -> bool:
        if new_state not in VALID_TRANSITIONS.get(self._state, set()):
            logger.warning(
                "Invalid transition %s -> %s — staying in %s",
                self._state.value,
                new_state.value,
                self._state.value,
            )
            return False
        logger.info("State: %s -> %s", self._state.value, new_state.value)
        self._state = new_state
        self._history.append(new_state.value)
        return True

    def is_terminal(self) -> bool:
        return self._state in TERMINAL_STATES

    def history(self) -> list[str]:
        return list(self._history)
