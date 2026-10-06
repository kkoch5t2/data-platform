#!/usr/bin/env python3
"""Reconnect only after sustained Wi-Fi disconnection; never cycle a healthy link."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

DEVICE = "wlp1s0"
PROFILE = "898cdab1-2788-4c4f-980a-ae4d0148844e"
DELAY = 180
COOLDOWN = 600

def run(*args, timeout=15):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "LC_ALL": "C"})

def decision(state, now, status, enabled):
    if not enabled or status != 30:
        return {}, False
    state = dict(state)
    state.setdefault("since", now)
    due = now - state["since"] >= DELAY
    due = due and now - state.get("attempt", -COOLDOWN) >= COOLDOWN
    if due:
        state["attempt"] = now
    return state, due

def self_test():
    s, due = decision({}, 100, 30, True)
    assert not due
    s, due = decision(s, 279, 30, True)
    assert not due
    s, due = decision(s, 280, 30, True)
    assert due
    s, due = decision(s, 879, 30, True)
    assert not due
    s, due = decision(s, 880, 30, True)
    assert due
    for status in (10, 20, 40, 50, 60, 70, 80, 90, 100, 110, 120):
        assert decision(s, 2000, status, True) == ({}, False)
    assert decision(s, 2000, 30, False) == ({}, False)
    print("PASS: delay, cooldown, healthy/connecting/unavailable/radio-off guards")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    result = run("nmcli", "-g", "GENERAL.STATE", "device", "show", DEVICE)
    if result.returncode:
        raise RuntimeError("Cannot read Wi-Fi state: " + result.stderr.strip())
    status = int(result.stdout.split()[0])
    radio = run("nmcli", "radio", "wifi")
    networking = run("nmcli", "networking")
    enabled = radio.stdout.strip() == "enabled" and networking.stdout.strip() == "enabled"
    if args.check:
        print(json.dumps({"device": DEVICE, "state": status, "enabled": enabled,
                          "delay_seconds": DELAY, "cooldown_seconds": COOLDOWN}))
        return
    directory = Path("/run/wifi-reconnect-watchdog")
    directory.mkdir(mode=0o700, exist_ok=True)
    with (directory / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state_path = directory / "state.json"
        try:
            state = json.loads(state_path.read_text())
        except (FileNotFoundError, ValueError):
            state = {}
        state, due = decision(state, time.monotonic(), status, enabled)
        # Persist before attempting, so a failed/timeout attempt still observes cooldown.
        state_path.write_text(json.dumps(state))
        if not due:
            return
        print("Wi-Fi disconnected >=180s; attempting saved 2.4GHz profile", flush=True)
        snapshot = run("nmcli", "-f", "GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS",
                       "device", "show", DEVICE)
        print(snapshot.stdout, flush=True)
        reconnect = run("nmcli", "--wait", "30", "connection", "up", "uuid", PROFILE,
                        "ifname", DEVICE, timeout=40)
        print("Reconnect exit:", reconnect.returncode, flush=True)
        print(reconnect.stdout.strip(), reconnect.stderr.strip(), flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Watchdog error:", error, flush=True)
        raise SystemExit(1)
