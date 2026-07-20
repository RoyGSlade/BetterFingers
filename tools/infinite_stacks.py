"""The Lost Meaning: Infinite Stacks -- LAN game server entrypoint.

Serves the wave-5 Infinite Stacks game (backend/lan_playground/stacks_api.py:
character creation, exploration, puzzles, combat with live reactions, shops)
to browsers on this machine or, with ``--lan``, to trusted devices on the
user's home network. Mirrors tools/lan_playground.py's security posture
exactly: loopback bind by default, explicit ``--lan`` opt-in for any
non-loopback bind, a high-entropy access code printed once at startup, and
the same Host/Origin allowlisting the rest of the LAN playground uses.

Usage:

    python3 tools/infinite_stacks.py                 # localhost only
    python3 tools/infinite_stacks.py --lan            # reachable from the LAN
    python3 tools/infinite_stacks.py --lan --port 8860 --access-code mycode123

Open the printed URL, enter the printed access code on the title screen,
create a room, and share the room code with the other players. Ctrl+C stops
the server; nothing is persisted.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.lan_playground.security import (  # noqa: E402
    LOOPBACK_HOSTS,
    generate_access_code,
    is_loopback_host,
    reachable_lan_ips,
)
from backend.lan_playground.stacks_api import create_stacks_app  # noqa: E402
from server_security import validate_startup_security  # noqa: E402

DEFAULT_PORT = 8860


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run The Lost Meaning: Infinite Stacks LAN game server.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1, loopback only).")
    parser.add_argument(
        "--lan",
        action="store_true",
        help="Bind to all interfaces (0.0.0.0) so devices on your home network can reach the game. "
        "Off by default -- required for any non-loopback bind.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port to listen on (default: {DEFAULT_PORT}).")
    parser.add_argument(
        "--access-code",
        default=None,
        help="Use this access code instead of generating one. Also settable via "
        "BETTERFINGERS_LAN_ACCESS_CODE.",
    )
    return parser.parse_args(argv)


def _compute_allowed_hosts(extra_ips: list[str]) -> set[str]:
    return set(LOOPBACK_HOSTS) | set(extra_ips)


def _compute_allowed_origins(port: int, extra_ips: list[str]) -> set[str]:
    hosts = set(LOOPBACK_HOSTS) | set(extra_ips)
    origins = set()
    for h in hosts:
        origin_host = f"[{h}]" if ":" in h else h
        origins.add(f"http://{origin_host}:{port}")
    return origins


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    host = args.host
    if args.lan and is_loopback_host(host):
        host = "0.0.0.0"

    access_code = args.access_code or os.getenv("BETTERFINGERS_LAN_ACCESS_CODE") or generate_access_code()

    security = validate_startup_security(host, token=access_code, allow_remote=args.lan)
    if not security["ok"]:
        print(f"ERROR: {security['error']}", file=sys.stderr)
        print("Refusing to start. Pass --lan to opt in to a LAN-reachable bind.", file=sys.stderr)
        return 1
    access_code = security["token"]

    lan_ips = reachable_lan_ips()
    allowed_hosts = _compute_allowed_hosts(lan_ips)
    allowed_origins = _compute_allowed_origins(args.port, lan_ips)

    app = create_stacks_app(
        access_code=access_code,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )

    print("The Lost Meaning: Infinite Stacks -- LAN game server")
    print(f"  bind:         {host}:{args.port}")
    if is_loopback_host(host):
        print(f"  open:         http://127.0.0.1:{args.port}/stacks.html")
        print("  This machine only -- pass --lan to make it reachable from other devices.")
    else:
        if lan_ips:
            for ip in lan_ips:
                print(f"  open:         http://{ip}:{args.port}/stacks.html")
        else:
            print("  WARNING: could not detect a private network address for this machine.")
            print("  Check `ip addr` (Linux) or `ipconfig` (Windows) for an address to share.")
        print("  Share a link above (plus the access code) only with people on your home network.")
    print(f"  access code:  {access_code}")
    print("  Enter the access code on the title screen, create a room, share the room code.")
    print("  Nothing typed here is saved, logged, or leaves this network. Press Ctrl+C to stop.")

    import uvicorn

    uvicorn.run(app, host=host, port=args.port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
