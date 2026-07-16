"""Create a LiveKit SIP outbound trunk pointing at your Twilio Elastic SIP Trunk.

Run this ONCE after completing the Twilio console steps below.
It prints the trunk ID — copy it into .env as LIVEKIT_SIP_OUTBOUND_TRUNK_ID.

TWILIO SETUP (do this first in console.twilio.com):
  1. Elastic SIP Trunking → Trunks → Create new SIP Trunk
       Name: anything, e.g. "LiveKit Outbound"
  2. Open the trunk → Termination tab
       Enable termination.
       SIP URI: choose a unique subdomain, e.g.  livekit-outbound.pstn.twilio.com
       Save.
  3. Termination → Credential Lists → + Create new credential list
       Name: livekit-creds
       Add a credential: username + password (anything you choose)
       Save, then add that credential list to the trunk's Termination tab.

  Add to .env:
    TWILIO_SIP_TERM_URI=livekit-outbound.pstn.twilio.com
    TWILIO_SIP_USERNAME=<credential username you chose>
    TWILIO_SIP_PASSWORD=<credential password you chose>
    TWILIO_PHONE_NUMBER=+12015551234   (your Twilio number, also in .env)

Then run:  python scripts/setup_outbound_trunk.py
"""
import asyncio
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from livekit import api
from livekit.protocol import sip as sip_proto


def _need(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        print(f"[ERROR] {name} not set in .env")
        sys.exit(1)
    return v


async def main() -> None:
    lk = api.LiveKitAPI(
        url=_need("LIVEKIT_URL"),
        api_key=_need("LIVEKIT_API_KEY"),
        api_secret=_need("LIVEKIT_API_SECRET"),
    )

    address  = _need("TWILIO_SIP_TERM_URI")   # e.g. livekit-outbound.pstn.twilio.com
    username = _need("TWILIO_SIP_USERNAME")
    password = _need("TWILIO_SIP_PASSWORD")

    # Caller-ID number — accept both TWILIO_ and TWILLIO_ (double-L) variants
    twilio_number = (
        os.getenv("TWILIO_PHONE_NUMBER", "").strip()
        or os.getenv("TWILLIO_PHONE_NUMBER", "").strip()
    )
    if not twilio_number:
        print("[ERROR] TWILIO_PHONE_NUMBER (or TWILLIO_PHONE_NUMBER) not set in .env")
        sys.exit(1)

    req = api.CreateSIPOutboundTrunkRequest()
    req.trunk.name          = "Twilio Outbound"
    req.trunk.address       = address
    req.trunk.auth_username = username
    req.trunk.auth_password = password
    req.trunk.transport     = sip_proto.SIPTransport.SIP_TRANSPORT_TCP
    req.trunk.numbers.append(twilio_number)

    trunk = await lk.sip.create_sip_outbound_trunk(req)
    await lk.aclose()

    print(f"\nOutbound trunk created: {trunk.sip_trunk_id}")
    print(f"  Name:    {trunk.name}")
    print(f"  Address: {trunk.address}")
    print()
    print("Add this line to your .env:")
    print(f"  LIVEKIT_SIP_OUTBOUND_TRUNK_ID={trunk.sip_trunk_id}")


asyncio.run(main())
