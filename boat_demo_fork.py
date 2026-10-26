"""Fork the stopped demo sandbox, read the file, retry the same key, stop the child."""

import json
import os
import time
import urllib.error
import urllib.request
import uuid

BASE = "https://boat.dev/api/v1"
KEY = os.environ["BOAT_API_KEY"]
PARENT = "bx_d83f6bht"


def call(method, path, body=None, headers=None, timeout=90):
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
            return res.status, json.loads(raw) if raw else {}, time.time() - started
    except urllib.error.HTTPError as err:
        raw = err.read().decode()
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw[:500]}
        return err.code, parsed, time.time() - started


def sid(payload):
    if isinstance(payload.get("sandbox"), dict) and payload["sandbox"].get("id"):
        return payload["sandbox"]["id"]
    return payload.get("id")


def state_of(payload):
    box = payload.get("sandbox") or payload
    return box.get("state") or box.get("status")


def wait_ready(sandbox_id, limit=180):
    deadline = time.time() + limit
    last = None
    while time.time() < deadline:
        code, payload, _ = call("GET", f"/sandboxes/{sandbox_id}")
        state = state_of(payload)
        last = {"http": code, "state": state}
        if state in ("ready", "idle", "running"):
            return last
        if state in ("error", "archived"):
            return last
        time.sleep(3)
    return last


def run(sandbox_id, command):
    code, payload, elapsed = call(
        "POST", f"/sandboxes/{sandbox_id}/commands", {"command": command}, timeout=120
    )
    stdout = payload.get("stdout") or (payload.get("command") or {}).get("stdout") or ""
    exit_code = payload.get("exitCode")
    if exit_code is None and isinstance(payload.get("command"), dict):
        exit_code = payload["command"].get("exitCode")
    err = payload.get("code") or payload.get("message")
    if isinstance(payload.get("error"), dict):
        err = payload["error"].get("code") or payload["error"].get("message")
    return {
        "http": code,
        "exit": exit_code,
        "stdout": stdout.strip()[:500],
        "seconds": round(elapsed, 2),
        "error": err if code >= 400 else None,
    }


def main():
    report = {}
    child = None
    code, payload, _ = call("GET", f"/sandboxes/{PARENT}")
    report["parent"] = {"http": code, "state": state_of(payload)}
    idem = str(uuid.uuid4())
    for attempt in range(8):
        code, payload, elapsed = call(
            "POST",
            f"/sandboxes/{PARENT}/fork",
            {"type": "small", "ttlSeconds": 300},
            headers={"Idempotency-Key": idem},
        )
        child = sid(payload)
        err = payload.get("code") or (payload.get("error") or {}).get("code")
        report["fork_attempt"] = {
            "n": attempt + 1,
            "http": code,
            "id": child,
            "error": err,
            "seconds": round(elapsed, 2),
        }
        if child:
            break
        if err not in ("sandbox_stopping", "fork_failed", "sandbox_resuming"):
            break
        time.sleep(5)
    if not child:
        print(json.dumps(report, indent=2))
        return
    report["child_ready"] = wait_ready(child)
    report["child_read"] = run(child, "cat /tmp/llmday.txt")
    report["child_fork"] = run(
        child,
        "python3 -c 'import os; p=os.fork(); "
        "open(\"/tmp/who.txt\",\"a\").write((\"child got 0\\n\") if p==0 else (\"parent got %d\\n\"%p)); "
        "os._exit(0) if p==0 else os.waitpid(p,0)' && cat /tmp/who.txt",
    )
    code2, payload2, elapsed2 = call(
        "POST",
        f"/sandboxes/{PARENT}/fork",
        {"type": "small", "ttlSeconds": 300},
        headers={"Idempotency-Key": idem},
    )
    report["fork_retry"] = {
        "http": code2,
        "id": sid(payload2),
        "same": sid(payload2) == child,
        "seconds": round(elapsed2, 2),
    }
    code, _, elapsed = call("POST", f"/sandboxes/{child}/stop")
    report["stopped_child"] = {"id": child, "http": code, "seconds": round(elapsed, 2)}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
