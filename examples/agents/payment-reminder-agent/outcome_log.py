from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass
class OutcomeLog:
    scenario: str = ""
    call_started: bool = False
    recording_disclosure_played: bool = False
    identity_verified: bool = False
    amount_disclosed: bool = False
    payment_link_sent: bool = False
    promise_to_pay_date: str | None = None
    dispute_detected: bool = False
    payment_reminder_stopped: bool = False
    ticket_created: bool = False
    ticket_id: str | None = None
    future_automated_reminders_paused: bool = False
    hardship_detected: bool = False
    human_callback_requested: bool = False
    human_handoff_required: bool = False
    outcome: str = "unknown"

    def to_dict(self) -> dict:
        return asdict(self)

    def save_to_file(self) -> str:
        os.makedirs("logs", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"logs/{self.scenario}_{timestamp}.json"
        data = self.to_dict()
        json_str = json.dumps(data, indent=2)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(json_str)
        print(json_str)
        return filename
