"""List Murf TTS voices, optionally filtered by locale.

Use this to find a voice id for the MURF_VOICE_ID env var (or the "agentVoice"
field in scenario_config.json). Murf voice ids look like "en-IN-anisha" — the
first two segments are the locale.

Usage:
  python scripts/list_voices.py                # all voices
  python scripts/list_voices.py en-IN          # only en-IN voices
  python scripts/list_voices.py en             # every en-* locale
  python scripts/list_voices.py --json en-US   # raw JSON for en-US

Requires MURF_API_KEY in your environment / .env.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import config  # noqa: E402  loads .env and validates MURF_API_KEY

VOICES_URL = "https://api.murf.ai/v1/speech/voices"


def fetch_voices() -> list[dict]:
    req = urllib.request.Request(VOICES_URL, headers={"api-key": config.MURF_API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"Murf API error {e.code}: {e.read().decode('utf-8', 'replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"Could not reach Murf API: {e.reason}")
    # The endpoint returns a bare list; tolerate a wrapped {"voices": [...]} too.
    return data if isinstance(data, list) else data.get("voices", [])


def _voice_id(v: dict) -> str:
    return v.get("voiceId") or v.get("voice_id") or ""


def _locale(v: dict) -> str:
    # Derive locale from the voice id ("en-IN-anisha" -> "en-IN").
    return "-".join(_voice_id(v).split("-")[:2])


def main() -> None:
    parser = argparse.ArgumentParser(description="List Murf TTS voices.")
    parser.add_argument(
        "locale",
        nargs="?",
        help="Filter by locale prefix, e.g. 'en-IN' or 'en'. Omit for all voices.",
    )
    parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    args = parser.parse_args()

    voices = fetch_voices()

    if args.locale:
        prefix = args.locale.lower()
        voices = [v for v in voices if _locale(v).lower().startswith(prefix)]

    if not voices:
        print(f"No voices found{f' for locale {args.locale!r}' if args.locale else ''}.")
        return

    if args.json:
        print(json.dumps(voices, indent=2, ensure_ascii=False))
        return

    voices.sort(key=lambda v: (_locale(v), _voice_id(v)))
    width = max(len(_voice_id(v)) for v in voices)
    print(f"{len(voices)} voice(s):\n")
    for v in voices:
        name = v.get("displayName") or v.get("name") or ""
        styles = v.get("availableStyles") or v.get("styles") or []
        style_str = f"  styles: {', '.join(styles)}" if styles else ""
        print(f"  {_voice_id(v):<{width}}  {name}{style_str}")


if __name__ == "__main__":
    main()
