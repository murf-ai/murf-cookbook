from __future__ import annotations


class GuardrailEngine:

    @staticmethod
    def check_pre_call(scenario: str) -> tuple[bool, str]:
        """Returns (can_proceed, block_reason). Blocks grievance_pending scenario."""
        if scenario == "grievance_pending":
            return (False, "Active grievance ticket on file — call blocked until resolved.")
        return (True, "")

    @staticmethod
    def should_stop_payment_flow(utterance: str) -> tuple[bool, str]:
        """Checks utterance for triggers that stop the normal payment flow.

        Returns (True, reason) where reason is one of:
        'dispute', 'hardship', 'human_requested', 'stop_calling'
        """
        text = utterance.lower()

        dispute_phrases = [
            "already paid",
            "paid already",
            "paid this",
            "dispute",
            "wrong amount",
            "incorrect amount",
            "i didn't borrow",
            "i did not borrow",
            "don't owe",
            "do not owe",
        ]
        for phrase in dispute_phrases:
            if phrase in text:
                return (True, "dispute")

        hardship_phrases = [
            "lost my job",
            "lost job",
            "cannot pay",
            "can't pay",
            "cant pay",
            "unable to pay",
            "medical emergency",
            "death in family",
            "in the hospital",
            "in hospital",
            "unemployed",
            "no income",
            "financial hardship",
        ]
        for phrase in hardship_phrases:
            if phrase in text:
                return (True, "hardship")

        human_phrases = [
            "speak to a human",
            "talk to a human",
            "speak to a person",
            "talk to a person",
            "real person",
            "real agent",
            "human agent",
            "escalate",
        ]
        for phrase in human_phrases:
            if phrase in text:
                return (True, "human_requested")

        stop_phrases = [
            "stop calling",
            "stop calling me",
            "remove me",
            "do not call",
            "don't call",
            "opt out",
            "take me off",
        ]
        for phrase in stop_phrases:
            if phrase in text:
                return (True, "stop_calling")

        return (False, "")

    @staticmethod
    def is_prohibited_language(agent_text: str) -> tuple[bool, str]:
        """Detects prohibited language in agent output.

        Returns (True, matched_phrase) if prohibited language is found.
        """
        text = agent_text.lower()

        prohibited = [
            "legal action",
            "contact your family",
            "contact your employer",
            "contact your references",
            "tell your family",
            "tell your employer",
        ]
        for phrase in prohibited:
            if phrase in text:
                return (True, phrase)

        return (False, "")

    @staticmethod
    def check_wrong_person(utterance: str, expected_name: str) -> bool:
        """Returns True if the utterance indicates the caller is not the expected person."""
        text = utterance.lower()
        name = expected_name.lower()

        wrong_person_phrases = [
            "wrong number",
            "wrong person",
            "you have the wrong",
            f"not {name}",
            f"no {name} here",
            f"no {name}",
            "different person",
            "nobody by that name",
        ]
        for phrase in wrong_person_phrases:
            if phrase in text:
                return True

        return False
