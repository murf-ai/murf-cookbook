from __future__ import annotations

import contextvars
import json
import os
import re

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenario_config.json")

# Per-call context config — set in agent.py entrypoint so parallel calls each
# see their own caller details rather than the shared scenario_config.json.
_call_ctx: contextvars.ContextVar[dict | None] = contextvars.ContextVar("call_cfg", default=None)


def get_config() -> dict:
    """Read scenario_config.json fresh from disk on every call."""
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def set_call_context_config(cfg: dict) -> None:
    """Bind caller-specific config to the current asyncio task context."""
    _call_ctx.set(cfg)


def _effective_config() -> dict:
    """Per-call context config if set (parallel campaigns), else reads from file."""
    ctx_cfg = _call_ctx.get()
    return ctx_cfg if ctx_cfg is not None else get_config()


def get_loan_account() -> dict:
    cfg = _effective_config()
    return {
        "customerName": cfg["customerName"],
        "accountEnding": cfg["accountEnding"],
        "amountDue": cfg["amountDue"],
        "amountDueFormatted": cfg["amountDueFormatted"],
        "dueDate": cfg["dueDate"],
        "daysPastDue": cfg["daysPastDue"],
        "registeredMobileLastFour": cfg["registeredMobileLastFour"],
    }


def has_grievance_pending() -> bool:
    return _effective_config().get("scenario") == "grievance_pending"


def is_mobile_match(digits_provided: str) -> bool:
    cleaned = re.sub(r"\D", "", digits_provided.strip())
    return cleaned == str(_effective_config()["registeredMobileLastFour"])


def is_account_match(digits_provided: str) -> bool:
    cleaned = re.sub(r"\D", "", digits_provided.strip())
    return cleaned == str(_effective_config()["accountEnding"])


def is_identity_match(mobile_last_four: str, account_last_four: str) -> bool:
    """Identity is confirmed only when both the mobile and account last four match."""
    return is_mobile_match(mobile_last_four) and is_account_match(account_last_four)


def get_scenario() -> str:
    return _effective_config()["scenario"]
