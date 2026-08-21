#!/usr/bin/env python3
"""Минимальный локальный broker временных заявок.

Публичный noVNC проксирует Caddy; broker отвечает за token/OTP/cookie.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import fcntl
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from core import ShareKind, ShareState, generate_token, hash_token  # noqa: E402
from store import ShareStore  # noqa: E402

BIND = os.getenv("SHARE_BROKER_BIND", "127.0.0.1")
PORT = int(os.getenv("SHARE_BROKER_PORT", "8790"))
DB = os.getenv("SHARE_BROKER_DB", "/var/lib/procvetaev-browser-share/shares.sqlite")
PEPPER_FILE = os.getenv("SHARE_BROKER_PEPPER_FILE", "/etc/procvetaev-browser/share.pepper")
MAX_TTL = int(os.getenv("SHARE_MAX_TTL_SECONDS", "1800"))
CDP_URL = os.getenv("BROWSER_CDP_URL", "http://127.0.0.1:9222").rstrip("/")
AUTH_BASE_URL = os.getenv("SHARE_AUTH_BASE_URL", "").rstrip("/")
REGISTRATION_URL = os.getenv("SHARE_REGISTRATION_URL", f"{AUTH_BASE_URL}/v1/share/register" if AUTH_BASE_URL else "")
REVOCATION_URL = os.getenv("SHARE_REVOCATION_URL", f"{AUTH_BASE_URL}/v1/share/revoke" if AUTH_BASE_URL else "")

Path(DB).parent.mkdir(parents=True, exist_ok=True)
pepper = Path(PEPPER_FILE).read_bytes().strip()
store = ShareStore(DB, pepper, MAX_TTL)
sessions: dict[str, tuple[str, float]] = {}
sessions_lock = threading.Lock()
ACTIVITY_LOCK = Path("/run/procvetaev-browser/activity.lock")


@contextmanager
def exclusive_browser_lifecycle():
    ACTIVITY_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with ACTIVITY_LOCK.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def listener(action: str, *, check: bool = False) -> None:
    result = subprocess.run(
        ["systemctl", action, "procvetaev-browser-share.service"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if check and result.returncode != 0:
        raise RuntimeError("browser share listener failed to start")
    if action == "start" and check:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", int(os.getenv("BROWSER_SHARE_PORT", "8791"))), timeout=1):
                    return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("browser share listener did not become ready")


def ensure_browser_ready(timeout: float = 20.0) -> None:
    subprocess.run(
        ["systemctl", "start", "procvetaev-browser.target", "procvetaev-chrome.service"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{CDP_URL}/json/version", timeout=1) as response:
                if response.status == HTTPStatus.OK:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("managed Chrome did not expose CDP")


def validate_target_url(value: object) -> str:
    target_url = str(value or "").strip()
    parsed = urlparse(target_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("target_url must be an absolute HTTP(S) URL without credentials")
    return target_url


def create_browser_target(target_url: str) -> str:
    request = Request(f"{CDP_URL}/json/new?{quote(target_url, safe='')}", method="PUT")
    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read())
    target_id = str(payload.get("id") or "").strip()
    if not target_id:
        raise RuntimeError("Chrome did not return a target id")
    return target_id


def close_browser_target(target_id: str) -> None:
    if not target_id:
        return
    try:
        with urlopen(f"{CDP_URL}/json/close/{quote(target_id, safe='')}", timeout=5):
            pass
    except Exception:
        # A user or Chrome may already have closed the owned target.
        pass


def close_owned_target(metadata: dict) -> None:
    close_browser_target(str(metadata.get("browser_target_id") or ""))


def register_session(token: str, share_id: str, expires_at: float) -> None:
    if not AUTH_BASE_URL.startswith("https://") or not REGISTRATION_URL.startswith("https://"):
        raise RuntimeError("Remote Access requires an explicit HTTPS SHARE_AUTH_BASE_URL")
    body = json.dumps({
        "token": token,
        "session_id": share_id,
        "kind": ShareKind.REMOTE_ACCESS.value,
        "expires_at": int(expires_at),
    }, separators=(",", ":")).encode()
    request = Request(
        REGISTRATION_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        if response.status != HTTPStatus.CREATED:
            raise RuntimeError("AUTH rejected temporary-share registration")


def revoke_registration(share_id: str) -> bool:
    if not REVOCATION_URL.startswith("https://"):
        raise RuntimeError("Remote Access requires an explicit HTTPS SHARE_AUTH_BASE_URL")
    body = json.dumps({
        "session_id": share_id,
        "kind": ShareKind.REMOTE_ACCESS.value,
    }, separators=(",", ":")).encode()
    request = Request(
        REVOCATION_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        if response.status != HTTPStatus.OK:
            raise RuntimeError("AUTH rejected temporary-share revocation")
        return bool(json.loads(response.read() or b"{}").get("revoked"))


def expire_loop() -> None:
    while True:
        time.sleep(1)
        expired = store.expire_due()
        if expired:
            expired_ids = {share_id for share_id, _metadata in expired}
            for share_id, metadata in expired:
                close_owned_target(metadata)
                try:
                    revoke_registration(share_id)
                except Exception:
                    pass
            with sessions_lock:
                for session, (share_id, _expires) in list(sessions.items()):
                    if share_id in expired_ids:
                        sessions.pop(session, None)
            if not store.has_open(ShareKind.REMOTE_ACCESS):
                listener("stop")


threading.Thread(target=expire_loop, name="share-expiry", daemon=True).start()


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def parse_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if length > 32_768:
        raise ValueError("payload too large")
    return json.loads(handler.rfile.read(length) or b"{}")


def token_from_path(path: str) -> str:
    parts = path.strip("/").split("/")
    if len(parts) < 3 or parts[0] != "access":
        return ""
    return parts[2]


class BrokerHandler(BaseHTTPRequestHandler):
    server_version = "TemporaryShareBroker/1"

    def log_message(self, _format: str, *_args) -> None:
        # URL-токены, OTP и payload не должны попадать в access log.
        return

    def do_POST(self) -> None:
        try:
            if self.path == "/v1/shares":
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    self.send_error(HTTPStatus.FORBIDDEN)
                    return
                self.create_share()
                return
            if self.path.startswith("/v1/shares/") and self.path.endswith("/revoke"):
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    self.send_error(HTTPStatus.FORBIDDEN)
                    return
                self.revoke_share(self.path.split("/")[3])
                return
            otp_path = self.path.strip("/").split("/")
            if len(otp_path) == 4 and otp_path[:3] == ["v1", "public", "otp"]:
                self.verify_otp(otp_path[3])
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as exc:
            json_response(self, HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/v1/public/registration-proof":
            token = self.headers.get("X-Share-Token", "")
            record = store.get_by_token(token) if token else None
            if (
                self.headers.get("X-Share-Kind") == ShareKind.REMOTE_ACCESS.value
                and record
                and record.kind is ShareKind.REMOTE_ACCESS
                and record.state is ShareState.OPEN
            ):
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
            else:
                self.send_error(HTTPStatus.FORBIDDEN)
            return
        if parsed.path == "/v1/public/authorize":
            self.authorize(
                self.headers.get("X-Share-Token")
                or parse_qs(parsed.query).get("token", [""])[0]
            )
            return
        if parsed.path.startswith("/access/remote/"):
            self.otp_page(token_from_path(parsed.path))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def create_share(self) -> None:
        payload = parse_json(self)
        kind = ShareKind(payload.get("kind", ""))
        if kind is not ShareKind.REMOTE_ACCESS:
            raise ValueError("this broker accepts only remote_access shares")
        if not AUTH_BASE_URL.startswith("https://"):
            raise ValueError("Remote Access is not configured: set an HTTPS SHARE_AUTH_BASE_URL")
        target = "local-browser"
        target_url = validate_target_url(payload.get("target_url"))
        ttl = int(payload.get("ttl_seconds", MAX_TTL))
        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")

        # На VPS один локальный Browser Harness: новая заявка закрывает старую.
        active = store.active_for_target(target)
        if active:
            active_metadata = store.metadata(active.share_id)
            store.revoke(active.share_id)
            close_owned_target(active_metadata)
            try:
                revoke_registration(active.share_id)
            except Exception:
                pass
            with sessions_lock:
                for session, (share_id, _expires) in list(sessions.items()):
                    if share_id == active.share_id:
                        sessions.pop(session, None)

        browser_target_id = ""
        try:
            ensure_browser_ready()
            browser_target_id = create_browser_target(target_url)
            record, token = store.create(kind, ttl, {
                **metadata,
                "target": target,
                "target_url": target_url,
                "browser_target_id": browser_target_id,
            })
        except Exception:
            close_browser_target(browser_target_id)
            raise ValueError("browser target creation failed")
        result = {
            "share_id": record.share_id,
            "public_token": token,
            "public_url": f"{AUTH_BASE_URL}/access/remote/{token}",
            "expires_at": record.expires_at.isoformat(),
        }
        if kind is ShareKind.REMOTE_ACCESS:
            otp = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
            store.set_otp(record.share_id, hash_token(otp, pepper))
            try:
                with exclusive_browser_lifecycle():
                    listener("start", check=True)
                    register_session(token, record.share_id, record.expires_at.timestamp())
            except Exception:
                store.revoke(record.share_id)
                close_browser_target(browser_target_id)
                listener("stop")
                raise ValueError("browser share startup or AUTH registration failed")
            result["otp"] = otp
        json_response(self, HTTPStatus.CREATED, result)

    def revoke_share(self, share_id: str) -> None:
        metadata = store.metadata(share_id)
        changed = store.revoke(share_id)
        close_owned_target(metadata)
        with sessions_lock:
            for session, (owned_id, _expires) in list(sessions.items()):
                if owned_id == share_id:
                    sessions.pop(session, None)
        if changed and not store.has_open(ShareKind.REMOTE_ACCESS):
            listener("stop")
        try:
            central_revoked = revoke_registration(share_id)
        except Exception:
            json_response(self, HTTPStatus.BAD_GATEWAY, {"revoked": changed, "central_revoked": False})
            return
        json_response(self, HTTPStatus.OK, {"revoked": changed, "central_revoked": central_revoked})

    def otp_page(self, token: str) -> None:
        record = store.get_by_token(token)
        if not record or record.kind is not ShareKind.REMOTE_ACCESS or record.state is not ShareState.OPEN:
            self.send_error(HTTPStatus.GONE)
            return
        body = f"""<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>Browser access</title><form method=post action='/v1/public/otp/{token}'><label>OTP <input name=otp autocomplete=one-time-code required maxlength=6></label><button>Open browser</button></form>""".encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def verify_otp(self, token: str) -> None:
        if self.headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded"):
            length = int(self.headers.get("Content-Length", "0"))
            form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            payload = {key: values[0] for key, values in form.items()}
        else:
            payload = parse_json(self)
        otp = str(payload.get("otp", ""))
        record = store.get_by_token(token)
        if not record or record.kind is not ShareKind.REMOTE_ACCESS or record.state is not ShareState.OPEN:
            json_response(self, HTTPStatus.GONE, {"error": "share unavailable"})
            return
        if not store.verify_otp(record.share_id, hash_token(otp, pepper)):
            json_response(self, HTTPStatus.TOO_MANY_REQUESTS, {"error": "otp rejected"})
            return
        session = generate_token()
        with sessions_lock:
            sessions[session] = (record.share_id, record.expires_at.timestamp())
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/access/remote/{token}/vnc.html?resize=scale")
        self.send_header("Set-Cookie", f"share_session={session}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age={MAX_TTL}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def authorize(self, token: str) -> None:
        cookie = self.headers.get("Cookie", "")
        session = next((x.split("=", 1)[1] for x in cookie.split("; ") if x.startswith("share_session=")), "")
        record = store.get_by_token(token)
        now = time.time()
        with sessions_lock:
            session_data = sessions.get(session)
            if session_data and session_data[1] <= now:
                sessions.pop(session, None)
                session_data = None
        if not record or not session_data or session_data[0] != record.share_id:
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.end_headers()
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()


if __name__ == "__main__":
    ThreadingHTTPServer((BIND, PORT), BrokerHandler).serve_forever()
