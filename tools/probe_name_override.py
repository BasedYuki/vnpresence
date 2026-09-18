"""Does this Discord client honour a per-activity `name`?

Discord normally prints the *application's* name after "Playing", which is why
VNPresence says "Playing a Visual Novel" with the game on the line below. Newer
clients accept a `name` field inside the activity payload, which would let the
header read "Playing Steins;Gate" instead - but support is inconsistent, so the
only reliable answer is to ask your own Discord client.

Run it, look at your profile, and report what the top line says:

    python tools/probe_name_override.py

It publishes a test activity for 45 seconds and then clears it. It changes
nothing in your library or config.
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from vnpresence.config import AppConfig  # noqa: E402

TEST_NAME = "Steins;Gate"


def main() -> int:
    try:
        from pypresence import Presence
    except ImportError:
        print("pypresence is not installed. Run: pip install -e \".[dev]\"")
        return 1

    client_id = AppConfig.load().client_id
    if not client_id:
        print("No Discord application id configured. Run: vnpresence doctor")
        return 1

    rpc = Presence(client_id)
    try:
        rpc.connect()
    except Exception as exc:
        print(f"Could not reach Discord: {exc}")
        print("Is the Discord DESKTOP app running and signed in?")
        return 1

    activity = {
        "name": TEST_NAME,  # the field under test
        "type": 0,
        "details": "probe: is the name field honoured?",
        "state": "Reading",
        "timestamps": {"start": int(time.time())},
    }
    payload = {
        "cmd": "SET_ACTIVITY",
        "args": {"pid": os.getpid(), "activity": activity},
        "nonce": "vnpresence-name-probe",
    }

    print("Sending the activity with a custom name...\n")
    rpc.send_data(1, payload)
    try:
        response = rpc.read_output()
        print("Discord replied with:")
        print(json.dumps(response, indent=2)[:1200])
    except Exception as exc:  # pragma: no cover - depends on the client
        print(f"(could not read Discord's reply: {exc})")

    print("\n" + "=" * 62)
    print("Now look at your own Discord profile. Which does the top line say?")
    print(f"  A)  Playing {TEST_NAME}          -> the name field works")
    print("  B)  Playing a Visual Novel     -> it is ignored, as documented")
    print("=" * 62)
    print("\nClearing in 45 seconds. Press Ctrl+C to clear now.")

    try:
        time.sleep(45)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            rpc.clear()
            rpc.close()
        except Exception:
            pass
    print("Cleared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
