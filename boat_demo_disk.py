"""One clean pass: write on the home disk, stop, fork, read, retry the key."""

import json
import os
import time
import urllib.error
import urllib.request
import uuid

BASE = "https://boat.dev/api/v1"
KEY = os.environ["BOAT_API_KEY"]


def call(method, path, body=None, headers=None, timeout=120):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            "Authorization": "Bearer " + KEY,
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode()
            return res.status, json.loads(raw) if raw else {}, round(time.time() - started, 2)
    except urllib.error.HTTPError as err:
        raw = err.read().decode()
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw[:400]}
        return err.code, parsed, round(time.time() - started, 2)


def sid(payload):
    box = payload.get("sandbox")
    if isinstance(box, dict) and box.get("id"):
        return box["id"]
    return payload.get("id")


def state_of(payload):
    box = payload.get("sandbox") or payload
    return box.get("state") or box.get("status")


def wait_state(sandbox_id, wanted, limit=180):
    started = time.time()
    last = None
    while time.time() - started < limit:
        code, payload, _ = call("GET", f"/sandboxes/{sandbox_id}")
        state = state_of(payload)
        last = state
        if state in wanted:
            return {"state": state, "seconds": round(time.time() - started, 2), "http": code}
        if state in ("error",):
            return {"state": state, "seconds": round(time.time() - started, 2), "http": code}
        time.sleep(2)
    return {"state": last, "seconds": round(time.time() - started, 2), "http": None}


def run(sandbox_id, command):
    code, payload, elapsed = call(
        "POST", f"/sandboxes/{sandbox_id}/commands", {"command": command}
    )
    stdout = payload.get("stdout") or (payload.get("command") or {}).get("stdout") or ""
    exit_code = payload.get("exitCode")
    if exit_code is None and isinstance(payload.get("command"), dict):
        exit_code = payload["command"].get("exitCode")
    return {"http": code, "exit": exit_code, "stdout": stdout.strip()[:600], "seconds": elapsed}


def main():
    created = []
    report = {}
    try:
        code, payload, elapsed = call(
            "POST", "/sandboxes", {"type": "small", "ttlSeconds": 600, "noEnv": True}
        )
        parent = sid(payload)
        report["create"] = {"http": code, "id": parent, "seconds": elapsed}
        if not parent:
            report["create_body"] = payload
            return
        created.append(parent)
        report["ready"] = wait_state(parent, {"ready", "idle", "running"})
        report["write"] = run(
            parent,
            "printf 'the pledge\\n' > \"$HOME/llmday.txt\" && echo HOME=$HOME && cat \"$HOME/llmday.txt\"",
        )
        code, payload, elapsed = call("POST", f"/sandboxes/{parent}/fork", {"ttlSeconds": 180})
        report["fork_before_stop"] = {
            "http": code,
            "code": (payload.get("error") or {}).get("code") or payload.get("code"),
            "message": (payload.get("error") or {}).get("message") or payload.get("message"),
            "seconds": elapsed,
        }
        code, _, elapsed = call("POST", f"/sandboxes/{parent}/stop")
        report["stop"] = {"http": code, "seconds": elapsed}
        report["archived"] = wait_state(parent, {"archived", "stopped"})
        idem = str(uuid.uuid4())
        code, payload, elapsed = call(
            "POST",
            f"/sandboxes/{parent}/fork",
            {"type": "small", "ttlSeconds": 300},
            headers={"Idempotency-Key": idem},
        )
        child = sid(payload)
        report["fork"] = {"http": code, "id": child, "seconds": elapsed}
        if not child:
            report["fork_body"] = payload
            return
        created.append(child)
        report["child_ready"] = wait_state(child, {"ready", "idle", "running"})
        report["child_read"] = run(child, "cat \"$HOME/llmday.txt\"; echo exit:$?")
        code, payload, elapsed = call(
            "POST",
            f"/sandboxes/{parent}/fork",
            {"type": "small", "ttlSeconds": 300},
            headers={"Idempotency-Key": idem},
        )
        report["retry"] = {
            "http": code,
            "id": sid(payload),
            "same": sid(payload) == child,
            "seconds": elapsed,
        }
    finally:
        report["stopped"] = []
        for sandbox_id in created:
            code, _, elapsed = call("POST", f"/sandboxes/{sandbox_id}/stop")
            report["stopped"].append({"id": sandbox_id, "http": code, "seconds": elapsed})
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
