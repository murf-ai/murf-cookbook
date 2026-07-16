"""
Call transcript collection.
Accumulates speaker turns during a call and saves locally to logs/.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

logger = logging.getLogger(__name__)

_active_sessions: dict[str, "CallSession"] = {}

_TRANSCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs",
)


@dataclass
class Turn:
    role: Literal["agent", "user"]
    text: str
    ts: float = 0.0


@dataclass
class CallSession:
    """Holds transcript state for one call. One instance per active call."""

    phone: str
    name: str = ""
    started_at: float = field(default_factory=time.time)
    turns: list[Turn] = field(default_factory=list)
    intent: str = "unknown"
    call_outcome: str = "unknown"

    def add_turn(self, role: Literal["agent", "user"], text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        if self.turns and self.turns[-1].role == role and self.turns[-1].text == cleaned:
            return
        relative_ts = round(time.time() - self.started_at, 2)
        self.turns.append(Turn(role=role, text=cleaned, ts=relative_ts))

    def set_outcome(self, intent: str, outcome: str) -> None:
        self.intent = intent
        self.call_outcome = outcome

    def to_transcript_json(self) -> list[dict]:
        return [{"role": t.role, "text": t.text, "ts": t.ts} for t in self.turns]

    def duration_seconds(self) -> int:
        return int(time.time() - self.started_at)


def register_call_session(room_name: str, session: CallSession) -> None:
    _active_sessions[room_name] = session


def unregister_call_session(room_name: str) -> CallSession | None:
    return _active_sessions.pop(room_name, None)


def get_call_session(room_name: str) -> CallSession | None:
    return _active_sessions.get(room_name)


def infer_intent_from_turns(session: CallSession) -> None:
    """Infer payment intent from transcript keywords when not set by a tool."""
    if session.intent != "unknown":
        return

    all_text = " ".join(t.text.lower() for t in session.turns)

    if any(w in all_text for w in ("already paid", "paid already", "paid this", "dispute")):
        session.intent = "payment_dispute"
    elif any(w in all_text for w in ("lost my job", "cannot pay", "hardship", "medical", "hospital")):
        session.intent = "hardship"
    elif any(w in all_text for w in ("promise", "will pay", "pay by", "pay tomorrow")):
        session.intent = "promise_to_pay"
    elif any(w in all_text for w in ("wrong number", "wrong person")):
        session.intent = "wrong_person"
    elif any(w in all_text for w in ("stop calling", "remove me", "do not call")):
        session.intent = "opt_out"
    elif session.turns:
        session.intent = "general_inquiry"


def save_transcript_local(session: CallSession) -> str | None:
    """Save transcript JSON to logs/{name}_{last4}.json."""
    last4 = re.sub(r"\D", "", session.phone)[-4:] if session.phone else "0000"
    safe_name = re.sub(r"[^\w\s-]", "", session.name).strip().replace(" ", "_") or "unknown"
    filename = os.path.join(_TRANSCRIPT_DIR, f"{safe_name}_{last4}.json")
    os.makedirs(_TRANSCRIPT_DIR, exist_ok=True)
    data = {
        "name": session.name,
        "phone": session.phone,
        "started_at": datetime.fromtimestamp(session.started_at, tz=timezone.utc).isoformat(),
        "duration_seconds": session.duration_seconds(),
        "intent": session.intent,
        "call_outcome": session.call_outcome,
        "transcript": session.to_transcript_json(),
    }
    with open(filename, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    logger.info("Transcript saved: %s", filename)
    return filename
