"""HTTP regression against a temporary DB and an ephemeral local port only."""
import copy
import ast
import importlib.util
import json
import secrets
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer

source = Path(__file__).resolve().parent.parent / 'server.py'
spec = importlib.util.spec_from_file_location("tested_server", source)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
passed = 0

with tempfile.TemporaryDirectory() as directory:
    app.ROOT = Path(directory)
    (app.ROOT / "seed.json").write_text('{"series":[],"samples":[]}', encoding="utf-8")
    app.DB = Path(directory) / "test.sqlite3"
    app.initialize()
    milestone = {"id":"m1", "name":"Test gate", "phase":"concept", "status":"进行中", "due":"", "actual":""}
    project = {"id":"test", "name":"Test", "part":"前翼系列", "owner":"Original owner", "priority":"中", "variants":[{"name":"85", "node":"Test gate", "status":"进行中", "milestones":[copy.deepcopy(milestone)]}], "milestones":[milestone], "approvals":[], "samples":[]}
    with app.database() as con:
        con.execute("UPDATE records SET payload=?, revision=0 WHERE kind='series'", (app.encode([project]),))
        con.execute("UPDATE records SET payload='[]', revision=0 WHERE kind='samples'")
        for role in ("viewer", "pm", "admin"):
            salt = secrets.token_bytes(16)
            con.execute("INSERT INTO accounts VALUES (?,?,?,?)", (role, role, salt, app.digest("test-only-password", salt)))
    server = ThreadingHTTPServer(("127.0.0.1", 0), app.Dashboard)
    server.origin = "http://127.0.0.1:%s" % server.server_port
    server.app_origin = "https://qa.example.test"
    server.page = ""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(route, body=None, session=None):
        headers = {"Origin": server.app_origin}
        if session:
            headers.update(Authorization="Bearer " + session["token"])
            headers["X-CSRF-Token"] = session["csrf"]
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(server.origin + route, data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            response = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        raw = response.read()
        return response.status, json.loads(raw) if raw else None

    def expect(name, actual, expected):
        global passed
        assert actual == expected, (name, actual, expected)
        passed += 1
        print("PASS", name)

    try:
        sessions = {}
        for role in ("viewer", "pm", "admin"):
            status, sessions[role] = request("/api/login", {"username":role, "password":"test-only-password"})
            expect(role + " login", status, 200)
        expect("unauthenticated bootstrap", request("/api/bootstrap")[0], 401)
        upgrade_source = (source.parent / "upgrade-existing.py").read_text(encoding="utf-8")
        health_function = next(node for node in ast.parse(upgrade_source).body if isinstance(node, ast.FunctionDef) and node.name == "health")
        health_globals = {"urllib": urllib, "port": server.server_port, "api_origin": server.app_origin}
        exec(compile(ast.Module(body=[health_function], type_ignores=[]), "health_probe", "exec"), health_globals)
        expect("upgrade health probe includes allowed Origin", health_globals["health"](), True)
        expect("viewer cannot write", request("/api/series", {"revision":0,"records":[project]}, sessions["viewer"])[0], 403)
        changed = copy.deepcopy(project)
        changed["owner"] = "Forbidden edit"
        expect("PM cannot modify protected fields", request("/api/series", {"revision":0,"records":[changed]}, sessions["pm"])[0], 403)
        changed = copy.deepcopy(project)
        changed["variants"][0]["milestones"][0]["status"] = "已完成"
        expect("missing actual date rejected", request("/api/series", {"revision":0,"records":[changed]}, sessions["pm"])[0], 400)
        changed["variants"][0]["milestones"][0]["actual"] = "2026-11-24"
        status, result = request("/api/series", {"revision":0,"records":[changed]}, sessions["pm"])
        expect("PM completion with actual date", status, 200)
        expect("revision advances", result["revision"], 1)
        expect("stale revision rejected", request("/api/series", {"revision":0,"records":[project]}, sessions["admin"])[0], 409)
        status, result = request("/api/bootstrap", session=sessions["viewer"])
        expect("shared saved data visible to viewer", result["state"]["series"]["records"][0]["variants"][0]["milestones"][0]["actual"], "2026-11-24")
        competing = []
        for owner in ("Owner A", "Owner B"):
            next_row = copy.deepcopy(changed)
            next_row["owner"] = owner
            competing.append(next_row)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda row: request("/api/series", {"revision":1,"records":[row]}, sessions["admin"])[0], competing))
        expect("concurrent writers: one succeeds, one conflicts", sorted(responses), [200, 409])
        invalid = {key:"" for key in ("id","family","sample","qty","fabric","drawing","production","due","status","owner","remarks")}
        invalid.update(id="bad", family="Test", sample="Test", status="unknown", progress=999)
        expect("invalid sample rejected", request("/api/samples", {"revision":0,"records":[invalid]}, sessions["admin"])[0], 400)
        invalid["status"] = "进行中"
        invalid["progress"] = 0
        invalid["due"] = "2026-99-99"
        expect("invalid calendar date rejected", request("/api/samples", {"revision":0,"records":[invalid]}, sessions["admin"])[0], 400)
        expect("logout", request("/api/logout", {}, sessions["viewer"])[0], 204)
        expect("revoked session rejected", request("/api/bootstrap", session=sessions["viewer"])[0], 401)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
print(json.dumps({"passed":passed,"database":"temporary; production untouched"}))
