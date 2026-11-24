"""Loopback-only Armstrong pilot. Use a managed HTTPS proxy for shared access."""
import argparse
import getpass
import hashlib
import html
import json
import math
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import date
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("ARMSTRONG_DB", ROOT / "team.sqlite3"))
ROLES = {"viewer", "pm", "admin"}
USERNAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
SESSION_AGE = 8 * 3600
ASSETS = {
    "/assets/armstrong-dashboard-hero.jpg": "image/jpeg",
    "/assets/oxanium-latin.woff2": "font/woff2",
}
PRIORITIES = {"最高", "高", "中", "低"}
STATUSES = {"未开始", "进行中", "已完成", "不适用", "已延误", "阻塞", "待确认", "待签署", "暂停", "待图档", "待排期", "待处理", "待归档", "资料准备中", "开模中", "制作中"}
PM_FIELDS = {"variants", "approvals", "updated"}
LOGIN_LIMIT = Lock()
failed_attempts = {}


def encode(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


@contextmanager
def database():
    con = sqlite3.connect(DB, timeout=8)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        with con:
            yield con
    finally:
        con.close()


def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with database() as con:
        con.execute("PRAGMA journal_mode = WAL")
        con.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                name TEXT PRIMARY KEY, role TEXT NOT NULL, salt BLOB NOT NULL, digest BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, account TEXT NOT NULL REFERENCES accounts(name),
                csrf TEXT NOT NULL, expires INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS records (
                kind TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                account TEXT NOT NULL, kind TEXT NOT NULL, revision INTEGER NOT NULL,
                previous TEXT NOT NULL, updated TEXT NOT NULL
            );
        """)
        seed = json.loads((ROOT / "seed.json").read_text(encoding="utf-8"))
        con.executemany("INSERT OR IGNORE INTO records VALUES (?, 0, ?)",
                        [(kind, encode(seed[kind])) for kind in ("series", "samples")])


def digest(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)


def token_key(token):
    return hashlib.sha256(token.encode()).hexdigest()


def text_field(obj, key):
    return isinstance(obj.get(key), str) and len(obj[key]) <= 20_000


def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def object_list(value, validator):
    return isinstance(value, list) and all(isinstance(item, dict) and validator(item) for item in value)


def unique_by(rows, key):
    normalized = [row[key].strip().casefold() for row in rows]
    return all(normalized) and len(normalized) == len(set(normalized))


def milestone(value):
    phase = value.get("phase")
    mid = value.get("id")
    return (text_field(value, "name") and isinstance(mid, str) and isinstance(phase, str)
            and value.get("status") in STATUSES
            and all(isinstance(value.get(key, ""), str) and len(value.get(key, "")) <= 20_000 for key in
                    ("status", "r", "a", "due", "actual", "next", "updated")))


def variant(value):
    return (all(text_field(value, field) for field in ("name", "node", "status"))
            and 0 < len(value["name"].strip()) <= 200 and value["status"] in STATUSES
            and object_list(value.get("milestones"), milestone)
            and unique_by(value["milestones"], "id"))


def approval(value):
    return value.get("status") in STATUSES and all(isinstance(value.get(key, ""), str) and len(value.get(key, "")) <= 20_000 for key in
               ("kind", "scope", "question", "submitter", "approver", "submitted",
                "needed", "status", "impact", "evidence", "confirmedOn"))


def project(value):
    return (all(text_field(value, field) for field in ("id", "name", "part", "owner", "priority"))
            and 0 < len(value["name"].strip()) <= 200
            and value["priority"] in PRIORITIES
            and object_list(value.get("variants"), variant) and unique_by(value["variants"], "name")
            and object_list(value.get("approvals"), approval)
            and object_list(value.get("milestones"), milestone) and unique_by(value["milestones"], "id")
            and isinstance(value.get("samples"), list)
            and all(isinstance(row, list) and all(isinstance(cell, (str, int, float)) for cell in row)
                    for row in value["samples"]))


def sample(value):
    progress = value.get("progress", 0)
    return (type(progress) in (int, float) and math.isfinite(progress) and 0 <= progress <= 100
            and value.get("status") in STATUSES
            and all(isinstance(value.get(key), str) and 0 < len(value[key].strip()) <= 200 for key in ("family", "sample"))
            and all(text_field(value, key) for key in
               ("id", "family", "sample", "qty", "fabric", "drawing", "production", "due",
                 "status", "owner", "remarks")))


def validate_changes(before, after, kind):
    originals = {row["id"]: row for row in before}
    for row in after:
        old = originals.get(row["id"], {})
        if kind == "samples":
            groups = [([row], [old])]
        else:
            if row.get("releaseDate") and row.get("releaseDate") != old.get("releaseDate") and not valid_date(row["releaseDate"]):
                raise ValueError("invalid release date")
            old_approvals = old.get("approvals", [])
            for index, item in enumerate(row["approvals"]):
                prior = old_approvals[index] if index < len(old_approvals) else {}
                for key in ("submitted", "needed", "confirmedOn"):
                    value = item.get(key, "")
                    if value and value != prior.get(key) and not valid_date(value):
                        raise ValueError("invalid confirmation date")
            groups = [(row["milestones"], old.get("milestones", []))]
            old_variants = old.get("variants", [])
            for index, variant_row in enumerate(row["variants"]):
                previous = next((v for v in old_variants if v["name"] == variant_row["name"]),
                                old_variants[index] if index < len(old_variants) else {})
                # A legacy variant without per-milestone history is migrated once;
                # do not invent completion dates for inferred historical steps.
                baseline = previous.get("milestones", variant_row["milestones"] if previous else [])
                groups.append((variant_row["milestones"], baseline))
        for current, previous in groups:
            previous_by_id = {item.get("id"): item for item in previous}
            for item in current:
                prior = previous_by_id.get(item.get("id"), {})
                for key in ("due", "actual", "updated"):
                    value = item.get(key, "")
                    if value and value != prior.get(key) and not valid_date(value):
                        raise ValueError("invalid date")
                if kind == "series" and item.get("status") == "已完成" and prior.get("status") != "已完成" and not valid_date(item.get("actual")):
                    raise ValueError("actual completion date required")


def protected_series(rows):
    return {row["id"]: {k: v for k, v in row.items() if k not in PM_FIELDS} for row in rows}


def permitted(before, after, role, kind):
    if role == "admin":
        return True
    if kind == "series":
        return protected_series(before) == protected_series(after)
    return {row["id"] for row in before} == {row["id"] for row in after}


LOGIN = """<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Armstrong 项目看板 · 登录</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100dvh;display:grid;place-items:center;background:#f2f4f7;color:#182033;font:16px system-ui,sans-serif;padding:24px}
main{width:min(100%,420px);border:1px solid #dce2e9;background:#fff;border-radius:20px;padding:32px}
h1{font-size:25px;margin:0 0 24px}label{display:block;font-weight:600;margin-top:16px}
input,button{display:block;width:100%;margin-top:7px;border:1px solid #ccd4df;border-radius:8px;padding:11px;font:inherit}
button{margin-top:22px;background:#20262e;border:0;color:white;cursor:pointer}.error{color:#ad1a1a}
</style><main><h1>Armstrong 项目看板</h1><p class="error" role="alert">{message}</p>
<form method="post" action="/login">
<label>账号 <span lang="en">Account</span><input name="username" autocomplete="username" maxlength="64" required></label>
<label>密码 <span lang="en">Password</span><input type="password" name="password" autocomplete="current-password" maxlength="256" required></label>
<button>登录 / Sign in</button></form></main></html>"""


class Dashboard(BaseHTTPRequestHandler):
    def response(self, status, payload=b"", kind="text/plain; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        if (urlsplit(self.path).path.startswith("/api/")
                and self.headers.get("Origin") == self.server.app_origin):
            self.send_header("Access-Control-Allow-Origin", self.server.app_origin)
            self.send_header("Vary", "Origin")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def json(self, status, obj):
        self.response(status, encode(obj).encode(), "application/json")

    def login(self, status=200, message=""):
        self.response(status, LOGIN.replace("{message}", html.escape(message)).encode(), "text/html; charset=utf-8")

    def session(self, con):
        authorization = self.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            raw = authorization[7:].strip()
        else:
            cookie = SimpleCookie(self.headers.get("Cookie", "")).get("armstrong_session")
            raw = cookie.value if cookie else ""
        if not raw or len(raw) > 256:
            return None
        return con.execute("""
            SELECT s.token, s.csrf, a.name, a.role
            FROM sessions s JOIN accounts a ON a.name=s.account
            WHERE s.token=? AND s.expires>?
        """, (token_key(raw), int(time.time()))).fetchone()

    def cookie(self, value, age):
        secure = "; Secure" if self.server.origin.startswith("https://") else ""
        return f"armstrong_session={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}{secure}"

    def read(self, limit, content_type):
        if self.headers.get_content_type() != content_type:
            raise ValueError("content type")
        size = int(self.headers.get("Content-Length", "-1"))
        if not 0 < size <= limit:
            raise ValueError("body size")
        return self.rfile.read(size).decode("utf-8")

    def do_GET(self):
        route = urlsplit(self.path).path
        if route == "/api/bootstrap":
            if self.headers.get("Origin") != self.server.app_origin:
                self.json(403, {"error": "origin"})
                return
            with database() as con:
                user = self.session(con)
                if not user:
                    self.json(401, {"error": "login"})
                    return
                state = {row["kind"]: {"revision": row["revision"],
                                       "records": json.loads(row["payload"])}
                         for row in con.execute("SELECT kind, revision, payload FROM records")}
            self.json(200, {"name": user["name"], "role": user["role"],
                            "csrf": user["csrf"], "state": state})
            return
        if route == "/login":
            self.login()
            return
        if route not in {"/", *ASSETS}:
            self.response(404)
            return
        with database() as con:
            user = self.session(con)
            if not user:
                self.response(303, headers={"Location": "/login"})
                return
            if route in ASSETS:
                self.response(200, (ROOT / route.lstrip("/")).read_bytes(), ASSETS[route])
                return
            state = {row["kind"]: {"revision": row["revision"], "records": json.loads(row["payload"])}
                     for row in con.execute("SELECT kind, revision, payload FROM records")}
        bootstrap = encode({"name": user["name"], "role": user["role"], "csrf": user["csrf"],
                            "state": state}).replace("<", "\\u003c")
        page = self.server.page.replace("<!--ARMSTRONG_BOOTSTRAP-->", bootstrap)
        self.response(200, page.encode(), "text/html; charset=utf-8")

    def authenticate(self, name, password):
        if not USERNAME.fullmatch(name) or not 1 <= len(password) <= 256:
            return None, 401, "账号或密码不正确。 Invalid account or password."
        now = int(time.time())
        address = self.client_address[0]
        with LOGIN_LIMIT:
            recent = [stamp for stamp in failed_attempts.get(address, []) if now - stamp < 300]
            if len(recent) >= 12:
                return None, 429, "尝试次数过多，请 5 分钟后重试。 Try again in five minutes."
            recent.append(now)
            failed_attempts[address] = recent
        with database() as con:
            user = con.execute("SELECT salt, digest, role FROM accounts WHERE name=?", (name,)).fetchone()
            calculated = digest(password, user["salt"] if user else bytes(16))
            if not user or not secrets.compare_digest(calculated, user["digest"]):
                return None, 401, "账号或密码不正确。 Invalid account or password."
            token = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            con.execute("DELETE FROM sessions WHERE expires<=?", (now,))
            con.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)",
                        (token_key(token), name, csrf, now + SESSION_AGE))
        with LOGIN_LIMIT:
            if now in failed_attempts[address]:
                failed_attempts[address].remove(now)
        return {"token": token, "csrf": csrf, "name": name, "role": user["role"],
                "expiresIn": SESSION_AGE}, 200, ""

    def sign_in(self):
        try:
            form = parse_qs(self.read(4096, "application/x-www-form-urlencoded"), max_num_fields=4)
            name = form.get("username", [""])[0].strip().lower()
            password = form.get("password", [""])[0]
        except (ValueError, UnicodeError):
            self.login(400, "登录请求无效。 Invalid request.")
            return
        result, status, message = self.authenticate(name, password)
        if not result:
            self.login(status, message)
            return
        self.response(303, headers={"Location": "/",
                                   "Set-Cookie": self.cookie(result["token"], SESSION_AGE)})

    def api_sign_in(self):
        try:
            data = json.loads(self.read(4096, "application/json"))
            if not isinstance(data, dict):
                raise ValueError("body")
            name = data.get("username", "").strip().lower()
            password = data.get("password", "")
            if not isinstance(name, str) or not isinstance(password, str):
                raise ValueError("credentials")
        except (ValueError, UnicodeError, AttributeError, TypeError):
            self.json(400, {"error": "request"})
            return
        result, status, _ = self.authenticate(name, password)
        if not result:
            self.json(status, {"error": "credentials" if status == 401 else "rate"})
            return
        self.json(200, result)

    def do_OPTIONS(self):
        route = urlsplit(self.path).path
        if not route.startswith("/api/") or self.headers.get("Origin") != self.server.app_origin:
            self.response(403)
            return
        requested = self.headers.get("Access-Control-Request-Headers", "").lower()
        allowed = {"authorization", "content-type", "x-csrf-token"}
        requested_set = {item.strip() for item in requested.split(",") if item.strip()}
        if not requested_set.issubset(allowed):
            self.response(403)
            return
        self.response(204, headers={
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type, X-CSRF-Token",
            "Access-Control-Max-Age": "600",
        })

    def do_POST(self):
        route = urlsplit(self.path).path
        origin = self.headers.get("Origin")
        if route == "/api/login":
            allowed_origin = origin == self.server.app_origin
        elif route.startswith("/api/"):
            allowed_origin = origin in {self.server.origin, self.server.app_origin}
        else:
            allowed_origin = origin == self.server.origin
        if not allowed_origin:
            self.json(403, {"error": "origin"})
            return
        if route == "/api/login":
            self.api_sign_in()
            return
        if route == "/login":
            self.sign_in()
            return
        with database() as con:
            user = self.session(con)
            if not user:
                self.json(401, {"error": "login"})
                return
            if not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), user["csrf"]):
                self.json(403, {"error": "token"})
                return
            if route in {"/logout", "/api/logout"}:
                con.execute("DELETE FROM sessions WHERE token=?", (user["token"],))
                con.commit()
                self.response(204, headers={"Set-Cookie": self.cookie("", 0)})
                return
            kinds = {"/api/series": "series", "/api/samples": "samples"}
            if route not in kinds:
                self.json(404, {"error": "route"})
                return
            if user["role"] not in {"pm", "admin"}:
                self.json(403, {"error": "role"})
                return
            try:
                self.save(con, user, kinds[route])
            except (ValueError, UnicodeError, RecursionError, TypeError):
                self.json(400, {"error": "data"})
            except sqlite3.OperationalError:
                self.json(503, {"error": "storage"})

    def save(self, con, user, kind):
        data = json.loads(self.read(4_000_000, "application/json"))
        if not isinstance(data, dict) or type(data.get("revision")) is not int:
            raise ValueError("record envelope")
        rows = data.get("records")
        if not object_list(rows, project if kind == "series" else sample) or not unique_by(rows, "id"):
            raise ValueError("invalid records")
        payload = encode(rows)
        con.execute("BEGIN IMMEDIATE")
        record = con.execute("SELECT revision, payload FROM records WHERE kind=?", (kind,)).fetchone()
        if record["revision"] != data["revision"]:
            self.json(409, {"error": "stale"})
            return
        previous = json.loads(record["payload"])
        if not permitted(previous, rows, user["role"], kind):
            self.json(403, {"error": "role"})
            return
        validate_changes(previous, rows, kind)
        revision = record["revision"]
        if previous != rows:
            revision += 1
            con.execute("UPDATE records SET revision=?, payload=? WHERE kind=?", (revision, payload, kind))
            con.execute("INSERT INTO audit(account, kind, revision, previous, updated) VALUES (?,?,?,?,?)",
                        (user["name"], kind, revision, record["payload"], payload))
        con.commit()
        self.json(200, {"revision": revision})


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--origin", help="Exact external HTTPS origin when using a reverse proxy")
    serve.add_argument("--app-origin", default="https://bfm4wn4zyg-star.github.io",
                       help="Exact GitHub Pages origin allowed to call the shared API")
    account = commands.add_parser("set-account")
    account.add_argument("name")
    account.add_argument("role", choices=sorted(ROLES))
    args = parser.parse_args()
    if hasattr(os, "umask"):
        os.umask(0o077)
    initialize()
    if args.command == "set-account":
        name = args.name.lower()
        if not USERNAME.fullmatch(name):
            parser.error("Use a simple account name, e.g. nathan")
        password = getpass.getpass("Password (at least 12 characters): ")
        if not 12 <= len(password) <= 256 or password != getpass.getpass("Repeat password: "):
            parser.error("Password length or confirmation is invalid")
        salt = secrets.token_bytes(16)
        with database() as con:
            con.execute("""INSERT INTO accounts VALUES (?,?,?,?)
                           ON CONFLICT(name) DO UPDATE SET role=excluded.role, salt=excluded.salt,
                           digest=excluded.digest""", (name, args.role, salt, digest(password, salt)))
            con.execute("DELETE FROM sessions WHERE account=?", (name,))
        print(f"Account {name} saved ({args.role}).")
        return
    origin = args.origin or f"http://127.0.0.1:{args.port}"
    if args.origin and not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::\d+)?", origin):
        parser.error("Proxy origin must be an HTTPS origin with no path or trailing slash")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::\d+)?", args.app_origin):
        parser.error("App origin must be an HTTPS origin with no path or trailing slash")
    with ThreadingHTTPServer(("127.0.0.1", args.port), Dashboard) as server:
        server.origin = origin
        server.app_origin = args.app_origin
        server.page = (ROOT / "index.html").read_text(encoding="utf-8")
        print(f"Armstrong pilot listening on 127.0.0.1:{args.port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
