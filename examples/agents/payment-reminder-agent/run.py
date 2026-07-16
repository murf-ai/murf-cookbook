"""
Payment reminder system — single entry point.

Single call (audio):
  python run.py --to +911234567890

Campaign from CSV (one call at a time):
  python run.py --csv reminders.csv

Campaign from CSV (all calls at once):
  python run.py --csv reminders.csv --mode parallel

CSV columns:
  name, phone, amount_due, due_date, account_ending, registered_mobile_last_four
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import date, datetime

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"), override=False)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run")

_CONFIG_PATH = os.path.join(_ROOT, "scenario_config.json")


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


_E164_RE = re.compile(r"^\+\d{7,15}$")

def _clean_phone(raw: str) -> str:
    """Return the phone in E.164 format or raise with a helpful message."""
    phone = raw.strip()
    if not _E164_RE.match(phone):
        raise ValueError(
            f"Invalid phone number {phone!r}.\n"
            "  Phone must be in E.164 format: +CountryCodeNumber (e.g. +911234567890).\n"
            "  If you edited the CSV in Excel, it likely converted the number to scientific\n"
            "  notation (e.g. 9.1234E+90). Open the file in Notepad/VS Code instead and\n"
            "  re-enter the numbers with a leading '+' and no spaces or dashes."
        )
    return phone


_DUE_DATE_FORMATS = (
    "%B %d, %Y",   # June 21, 2026
    "%B %d %Y",    # June 21 2026
    "%d/%m/%Y",    # 21/06/2026
    "%Y-%m-%d",    # 2026-06-21
)


def _parse_due_date(s: str) -> date:
    for fmt in _DUE_DATE_FORMATS:
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse due date: {s!r}  (expected e.g. 'June 21, 2026')")


def _days_past_due(due_date_str: str) -> int:
    return max(0, (date.today() - _parse_due_date(due_date_str)).days)


def _format_inr(amount_str: str) -> str:
    """Format a plain integer as Indian rupees: 10000 → ₹10,000."""
    amount = int(float(amount_str.replace(",", "").strip()))
    return f"₹{amount:,}"


def _row_to_meta(row: dict) -> dict:
    due_date = row["due_date"].strip()
    amount   = row["amount_due"].strip()
    return {
        "phone_number":                _clean_phone(row["phone"]),
        "customer_name":               row["name"].strip(),
        "amount_due":                  amount,
        "amount_due_formatted":        _format_inr(amount),
        "due_date":                    due_date,
        "days_past_due":               _days_past_due(due_date),
        "account_ending":              row["account_ending"].strip(),
        "registered_mobile_last_four": row["registered_mobile_last_four"].strip(),
    }


async def _dispatch(lk, room_name: str, meta: dict) -> None:
    from livekit import api as lk_api
    await lk.room.create_room(lk_api.CreateRoomRequest(name=room_name))
    dispatch = await lk.agent_dispatch.create_dispatch(
        lk_api.CreateAgentDispatchRequest(
            agent_name="payment-agent",
            room=room_name,
            metadata=json.dumps(meta),
        )
    )
    logger.info("Dispatched → room=%s  dispatch=%s", room_name, dispatch.id)


async def _wait_for_room_close(
    lk, room_name: str, timeout_s: int = 600, agent_proc: "subprocess.Popen | None" = None
) -> bool:
    """Poll every 5s until the room disappears (call ended) or timeout.
    If agent_proc is supplied and exits unexpectedly the room is deleted immediately."""
    from livekit import api as lk_api
    await asyncio.sleep(15)  # initial wait — dial + ring + answer takes ~10s
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if agent_proc is not None and agent_proc.poll() is not None:
            logger.warning("Agent process exited — deleting room %s and moving on", room_name)
            try:
                await lk.room.delete_room(lk_api.DeleteRoomRequest(room=room_name))
            except Exception:
                pass
            return False
        try:
            result = await lk.room.list_rooms(lk_api.ListRoomsRequest(names=[room_name]))
            if not result.rooms:
                return True
        except Exception as exc:
            logger.warning("Room poll error: %s", exc)
        await asyncio.sleep(5)
    return False


# ── call modes ────────────────────────────────────────────────────────────────

async def _run_sequential(rows: list[dict], proc: list | None = None) -> None:
    from livekit import api as lk_api
    lk = lk_api.LiveKitAPI(
        url=os.environ["LIVEKIT_URL"],
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )
    try:
        for i, row in enumerate(rows, 1):
            name = row["name"].strip()
            phone = row["phone"].strip()

            # Between calls: wait for the agent to recover from any WebRTC cleanup,
            # and restart it if the process died (e.g. from an unrecoverable panic).
            if i > 1:
                await asyncio.sleep(5)
                if proc is not None and proc[0].poll() is not None:
                    print(f"\n  Agent process exited — restarting before call {i}…")
                    proc[0] = _start_agent()
                    lk_tmp = lk_api.LiveKitAPI(
                        url=os.environ["LIVEKIT_URL"],
                        api_key=os.environ["LIVEKIT_API_KEY"],
                        api_secret=os.environ["LIVEKIT_API_SECRET"],
                    )
                    try:
                        await _wait_for_agent_ready(lk_tmp)
                        print("  Agent restarted.\n")
                    finally:
                        await lk_tmp.aclose()

            print(f"\n[{i}/{len(rows)}] Calling {name} ({phone}) …")
            room_name = f"payment-{uuid.uuid4().hex[:8]}"
            meta = _row_to_meta(row)
            await _dispatch(lk, room_name, meta)
            print(f"         Waiting for call to finish (room: {room_name}) …")
            agent_p = proc[0] if proc else None
            closed = await _wait_for_room_close(lk, room_name, agent_proc=agent_p)
            status = "done" if closed else "timed out"
            print(f"         {name}: {status}.")
    finally:
        await lk.aclose()


async def _run_parallel(rows: list[dict]) -> None:
    from livekit import api as lk_api
    lk = lk_api.LiveKitAPI(
        url=os.environ["LIVEKIT_URL"],
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )
    try:
        print(f"\nDispatching {len(rows)} calls simultaneously …")
        tasks = []
        for row in rows:
            room_name = f"payment-{uuid.uuid4().hex[:8]}"
            tasks.append(_dispatch(lk, room_name, _row_to_meta(row)))
        await asyncio.gather(*tasks)
        print(f"All {len(rows)} calls dispatched.")
    finally:
        await lk.aclose()


async def _run_single(phone: str) -> None:
    from livekit import api as lk_api
    phone = _clean_phone(phone)
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    amount   = str(cfg["amountDue"])
    due_date = cfg["dueDate"]
    meta = {
        "phone_number":                phone,
        "customer_name":               cfg["customerName"],
        "amount_due":                  amount,
        "amount_due_formatted":        _format_inr(amount),
        "due_date":                    due_date,
        "days_past_due":               _days_past_due(due_date),
        "account_ending":              str(cfg["accountEnding"]),
        "registered_mobile_last_four": str(cfg["registeredMobileLastFour"]),
    }
    lk = lk_api.LiveKitAPI(
        url=os.environ["LIVEKIT_URL"],
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )
    try:
        room_name = f"payment-{uuid.uuid4().hex[:8]}"
        print(f"\nCalling {phone} (room: {room_name}) …")
        await _dispatch(lk, room_name, meta)
        print("Call dispatched — your phone will ring in ~5 s.")
    finally:
        await lk.aclose()


# ── agent worker ──────────────────────────────────────────────────────────────

def _start_agent() -> subprocess.Popen:
    """Start the LiveKit agent worker in the background (same terminal output)."""
    return subprocess.Popen(
        [sys.executable, os.path.join(_ROOT, "agent.py"), "start"],
    )


async def _wait_for_agent_ready(lk, timeout_s: int = 30) -> None:
    """Poll LiveKit until we can reach it, then add a short buffer for registration."""
    from livekit import api as lk_api
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            await lk.room.list_rooms(lk_api.ListRoomsRequest())
            await asyncio.sleep(3)  # extra time for worker process to register
            return
        except Exception:
            await asyncio.sleep(1)
    raise RuntimeError("Could not connect to LiveKit after 30 s — check LIVEKIT_URL and credentials.")


# ── main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Payment reminder system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--to", metavar="PHONE",
                       help="Single call: E.164 phone number, e.g. +911234567890")
    group.add_argument("--csv", metavar="FILE",
                       help="Campaign CSV file, e.g. reminders.csv")
    parser.add_argument("--mode", choices=["sequential", "parallel"], default="sequential",
                        help="Campaign mode when using --csv (default: sequential)")
    args = parser.parse_args()

    print("\n" + "=" * 62)
    print("  PAYMENT REMINDER SYSTEM")
    print("=" * 62)

    print("\nStarting agent worker …")
    proc = [_start_agent()] 

    from livekit import api as lk_api
    lk = lk_api.LiveKitAPI(
        url=os.environ["LIVEKIT_URL"],
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )

    try:
        await _wait_for_agent_ready(lk)
        print("Agent ready.\n")
        await lk.aclose()

        if args.csv:
            rows = _load_csv(args.csv)
            print(f"Loaded {len(rows)} contact(s) from {args.csv}")
            if args.mode == "parallel":
                await _run_parallel(rows)
            else:
                await _run_sequential(rows, proc=proc)
        else:
            await _run_single(args.to)

        print("\nAgent is running — press Ctrl+C when done.")
        while True:
            if proc[0].poll() is not None:
                break
            await asyncio.sleep(2)

    except KeyboardInterrupt:
        print("\nStopping …")
    finally:
        if proc[0].poll() is None:
            proc[0].terminate()
            try:
                proc[0].wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc[0].kill()


if __name__ == "__main__":
    asyncio.run(main())
