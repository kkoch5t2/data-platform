#!/usr/bin/env python3
"""Check DATLUME sitemap status via the official Google Search Console API."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

CONFIG_DIR = Path.home() / ".config/datlume/gsc"
CREDENTIALS = CONFIG_DIR / "credentials.json"
TOKEN = CONFIG_DIR / "token.json"
PENDING = CONFIG_DIR / "pending.json"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
SITE = "sc-domain:datlume.com"
SITEMAP = "https://datlume.com/sitemap.xml"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/webmasters/v3"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def post_form(url: str, data: dict[str, str]) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def request_json(url: str, access_token: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "DATLUME-GSC-Monitor/1.0",
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def save_token(token: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(json.dumps(token, ensure_ascii=False), encoding="utf-8")
    os.chmod(TOKEN, 0o600)


def client_config() -> dict:
    if not CREDENTIALS.exists():
        raise RuntimeError(f"OAuth credentials missing: {CREDENTIALS}")
    data = load_json(CREDENTIALS)
    cfg = data.get("installed") or data.get("web")
    if not cfg:
        raise RuntimeError("OAuth JSON has neither installed nor web client config")
    return cfg


def _oauth_request(redirect_uri: str) -> tuple[str, str, str]:
    cfg = client_config()
    verifier = base64.urlsafe_b64encode(os.urandom(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": cfg["client_id"], "redirect_uri": redirect_uri,
        "response_type": "code", "scope": SCOPE, "access_type": "offline",
        "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    }
    return verifier, state, AUTH_URL + "?" + urllib.parse.urlencode(params)


def _exchange_code(code: str, verifier: str, redirect_uri: str) -> None:
    cfg = client_config()
    token = post_form(TOKEN_URL, {
        "client_id": cfg["client_id"], "client_secret": cfg.get("client_secret", ""),
        "code": code, "code_verifier": verifier,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    })
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600))
    save_token(token)


def authorize(open_browser: bool = True) -> None:
    result: dict[str, str] = {}
    state_holder: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] != state_holder.get("state"):
                self.send_response(400); self.end_headers(); return
            result["code"] = query.get("code", [""])[0]
            result["error"] = query.get("error", [""])[0]
            body = "DATLUME Search Console authorization completed. You can close this tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())
        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}/"
    verifier, state, url = _oauth_request(redirect_uri)
    state_holder["state"] = state
    print("Open this Google authorization URL on the Ubuntu machine:", flush=True)
    print(url, flush=True)
    if open_browser:
        webbrowser.open(url)
    server.timeout = 300
    server.handle_request()
    server.server_close()
    if result.get("error"):
        raise RuntimeError(f"OAuth authorization failed: {result['error']}")
    if not result.get("code"):
        raise RuntimeError("OAuth callback was not received within 5 minutes")
    _exchange_code(result["code"], verifier, redirect_uri)
    print("OAuth token saved securely.", flush=True)


def headless_start() -> None:
    redirect_uri = "http://127.0.0.1:8765/"
    verifier, state, url = _oauth_request(redirect_uri)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PENDING.write_text(json.dumps({
        "verifier": verifier, "state": state, "redirect_uri": redirect_uri,
        "created_at": int(time.time()),
    }), encoding="utf-8")
    os.chmod(PENDING, 0o600)
    print(url)


def headless_complete(callback_url: str) -> None:
    if not PENDING.exists():
        raise RuntimeError("No pending headless OAuth request; run --headless-start first")
    pending = load_json(PENDING)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(callback_url).query)
    if query.get("state", [""])[0] != pending.get("state"):
        raise RuntimeError("OAuth state mismatch")
    if query.get("error", [""])[0]:
        raise RuntimeError(f"OAuth authorization failed: {query['error'][0]}")
    code = query.get("code", [""])[0]
    if not code:
        raise RuntimeError("Authorization code missing from callback URL")
    _exchange_code(code, pending["verifier"], pending["redirect_uri"])
    PENDING.unlink(missing_ok=True)
    print("OAuth token saved securely.")


def access_token() -> str:
    cfg = client_config()
    if not TOKEN.exists():
        raise RuntimeError("OAuth token missing. Run: python3 scripts/check-gsc-sitemap.py --authorize")
    token = load_json(TOKEN)
    if token.get("access_token") and int(token.get("expires_at", 0)) > int(time.time()) + 60:
        return token["access_token"]
    refresh = token.get("refresh_token")
    if not refresh:
        raise RuntimeError("OAuth refresh token missing; re-run --authorize")
    fresh = post_form(TOKEN_URL, {
        "client_id": cfg["client_id"], "client_secret": cfg.get("client_secret", ""),
        "refresh_token": refresh, "grant_type": "refresh_token",
    })
    token.update(fresh)
    token["refresh_token"] = refresh
    token["expires_at"] = int(time.time()) + int(fresh.get("expires_in", 3600))
    save_token(token)
    return token["access_token"]


def check_sitemap() -> int:
    site = urllib.parse.quote(SITE, safe="")
    payload = request_json(f"{API_BASE}/sites/{site}/sitemaps", access_token())
    rows = payload.get("sitemap") or []
    target = next((x for x in rows if x.get("path") == SITEMAP), None)
    if target is None:
        print(json.dumps({"ok": False, "reason": "sitemap_not_found", "site": SITE, "sitemap": SITEMAP}))
        return 2
    result = {
        "ok": int(target.get("errors", 0) or 0) == 0 and int(target.get("warnings", 0) or 0) == 0,
        "site": SITE, "sitemap": SITEMAP,
        "isPending": bool(target.get("isPending", False)),
        "lastSubmitted": target.get("lastSubmitted"),
        "lastDownloaded": target.get("lastDownloaded"),
        "warnings": int(target.get("warnings", 0) or 0),
        "errors": int(target.get("errors", 0) or 0),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorize", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--headless-start", action="store_true")
    parser.add_argument("--complete-stdin", action="store_true")
    args = parser.parse_args()
    try:
        if args.authorize:
            authorize(open_browser=not args.no_browser)
            return 0
        if args.headless_start:
            headless_start()
            return 0
        if args.complete_stdin:
            headless_complete(sys.stdin.readline().strip())
            return 0
        return check_sitemap()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        print(f"GSC HTTP error: {exc.code} {detail}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"GSC monitor error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
