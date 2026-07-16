from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(
            f"Required environment variable '{name}' is not set. "
            "Copy .env.example to .env and fill in your credentials."
        )
    return value


def _optional(name: str) -> str | None:
    return os.getenv(name) or None


def _normalize_sip_uri(uri: str) -> str:
    value = uri.strip()
    if value.lower().startswith("sip:"):
        value = value[4:]
    return value


# ── LiveKit (required) ─────────────────────────────────────────────────────────
LIVEKIT_URL: str = _require("LIVEKIT_URL")
LIVEKIT_API_KEY: str = _require("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET: str = _require("LIVEKIT_API_SECRET")

# Only needed for SIP transfer (human handoff over PSTN)
LIVEKIT_SIP_URI: str | None = _optional("LIVEKIT_SIP_URI")

# ── STT provider: "deepgram" (default) or "openai" ────────────────────────────
STT_PROVIDER: str = os.getenv("STT_PROVIDER", "deepgram")
DEEPGRAM_API_KEY: str | None = _optional("DEEPGRAM_API_KEY")
OPENAI_API_KEY: str | None = _optional("OPENAI_API_KEY")

if STT_PROVIDER == "deepgram" and not DEEPGRAM_API_KEY:
    raise ValueError("DEEPGRAM_API_KEY is required when STT_PROVIDER=deepgram")
if STT_PROVIDER == "openai" and not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is required when STT_PROVIDER=openai")

# ── LLM provider: "gemini" (default) or "openai" ─────────────────────────────
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")
GOOGLE_API_KEY: str | None = _optional("GOOGLE_API_KEY")

if LLM_PROVIDER == "gemini" and not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY is required when LLM_PROVIDER=gemini")
if LLM_PROVIDER == "openai" and not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")

# ── Murf TTS (required) ───────────────────────────────────────────────────────
MURF_API_KEY: str = _require("MURF_API_KEY")

# Optional voice-id override. When set, it takes precedence over "agentVoice" in
# scenario_config.json. Murf voice IDs look like "en-IN-anisha" — the locale is
# the first two segments. List available voices with scripts/list_voices.py.
MURF_VOICE_ID: str | None = _optional("MURF_VOICE_ID")

# ── Human handoff — SIP transfer to human agent (optional) ────────────────────
# Set HUMAN_TRANSFER_NUMBER to enable live SIP transfers when the agent escalates.
HUMAN_TRANSFER_NUMBER: str | None = _optional("HUMAN_TRANSFER_NUMBER")


def handoff_enabled() -> bool:
    return bool(HUMAN_TRANSFER_NUMBER and LIVEKIT_SIP_URI)


# ── Twilio — SIP trunk setup + post-call WhatsApp (optional at agent runtime) ─
TWILIO_ACCOUNT_SID: str | None = _optional("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN: str | None = _optional("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER: str | None = _optional("TWILIO_PHONE_NUMBER")
TWILIO_WHATSAPP_FROM: str | None = _optional("TWILIO_WHATSAPP_FROM")


def whatsapp_enabled() -> bool:
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM)
