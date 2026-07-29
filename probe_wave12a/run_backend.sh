#!/usr/bin/env bash
# Wave 12A-B probe: real backend on a CLEAN data root, exactly like a new user.
set -u
cd /home/donaven/Desktop/BetterFingers
export BETTERFINGERS_DATA_DIR=/home/donaven/Desktop/BetterFingers/probe_wave12a/dataroot
export BETTERFINGERS_AUTH_TOKEN=wave12a-probe-token
mkdir -p "$BETTERFINGERS_DATA_DIR"
exec .venv/bin/python server.py --port 8011 --log-level INFO
