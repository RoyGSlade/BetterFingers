"""LAN persona rewrite playground -- CLI entrypoint (board #33).

Launches an isolated, text-only web demo for trusted friends on the user's
home network: they pick a persona, paste text, optionally add a custom
rewrite instruction, and see the local model's refined output. No
microphone, no text-to-speech, no audio APIs, nothing persisted.

Binds to loopback (127.0.0.1) by default. Reaching other devices on the
network requires the explicit ``--lan`` flag; a high-entropy access code is
generated (or supplied) either way and printed once at startup -- nothing
after that prints or logs it again.

Usage:

    python3 tools/lan_playground.py                 # localhost only
    python3 tools/lan_playground.py --lan            # reachable from the LAN
    python3 tools/lan_playground.py --lan --port 8850 --access-code mycode123

See docs/LAN_PLAYGROUND.md for the full walkthrough (Linux/Windows commands,
firewall notes, shutdown instructions).
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.lan_playground.app import DEFAULT_PORT, build_default_app  # noqa: E402
from backend.lan_playground.security import (  # noqa: E402
    LOOPBACK_HOSTS,
    generate_access_code,
    is_loopback_host,
    reachable_lan_ips,
)
from server_security import validate_startup_security  # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LAN persona rewrite playground.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1, loopback only).")
    parser.add_argument(
        "--lan",
        action="store_true",
        help="Bind to all interfaces (0.0.0.0) so devices on your home network can reach this demo. "
        "Off by default -- required for any non-loopback bind.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port to listen on (default: {DEFAULT_PORT}).")
    parser.add_argument(
        "--access-code",
        default=None,
        help="Use this access code instead of generating one. Also settable via "
        "BETTERFINGERS_LAN_ACCESS_CODE.",
    )
    parser.add_argument(
        "--generate-timeout",
        type=float,
        default=None,
        help="Seconds to wait for a rewrite before giving up (default: 75).",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=None,
        help="Maximum number of rewrites processed at once (default: 2).",
    )
    parser.add_argument(
        "--rate-limit-per-min",
        type=int,
        default=None,
        help="Maximum rewrite requests per client per minute (default: 12).",
    )
    return parser.parse_args(argv)


def _compute_allowed_hosts(extra_ips: list[str]) -> set[str]:
    return set(LOOPBACK_HOSTS) | set(extra_ips)


def _compute_allowed_origins(host: str, port: int, extra_ips: list[str]) -> set[str]:
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
    allowed_origins = _compute_allowed_origins(host, args.port, lan_ips)

    kwargs = {}
    if args.generate_timeout is not None:
        kwargs["generate_timeout_s"] = args.generate_timeout
    if args.max_concurrency is not None:
        kwargs["max_concurrency"] = args.max_concurrency
    if args.rate_limit_per_min is not None:
        kwargs["rate_limit_per_min"] = args.rate_limit_per_min

    app = build_default_app(
        access_code=access_code,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
        **kwargs,
    )

    print("BetterFingers LAN Playground -- Spellcheck & Sorcery")
    print(f"  bind:         {host}:{args.port}")
    if is_loopback_host(host):
        print(f"  open:         http://127.0.0.1:{args.port}/?code={access_code}")
        print("  This machine only -- pass --lan to make it reachable from other devices.")
    else:
        if lan_ips:
            for ip in lan_ips:
                print(f"  open:         http://{ip}:{args.port}/?code={access_code}")
        else:
            print("  WARNING: could not detect a private network address for this machine.")
            print("  Check `ip addr` (Linux) or `ipconfig` (Windows) for an address to share.")
        print("  Share a link above (or the address + access code) only with people on your home network.")
        print("  Once you create a room in the browser, its lobby shows a QR code and a shorter room")
        print("  code your friends can scan or type in -- generated locally, no internet service.")
    print(f"  access code:  {access_code}")
    print("  Nothing typed here is saved, logged, or leaves this network. Press Ctrl+C to stop.")

    import uvicorn

    uvicorn.run(app, host=host, port=args.port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
