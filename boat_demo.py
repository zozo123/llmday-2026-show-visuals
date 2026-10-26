"""Live boat.dev demo for the LLMday talk.

Reads BOAT_API_KEY from the environment. Prints sandbox ids and timings only.
Stops every sandbox it creates.
"""

import json
import os
import time
import urllib.error
import urllib.request
import uuid

BASE = "https://boat.dev/api/v1"
KEY = os.environ["BOAT_API_KEY"]


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
            parsed = {"raw": raw[:400]}
        return err.code, parsed, time.time() - started


def sid(payload):
    if isinstance(payload.get("sandbox"), dict) and payload["sandbox"].get("id"):
        return payload["sandbox"]["id"]
    return payload.get("id")


def wait_ready(sandbox_id, limit=180):
    deadline = time.time() + limit
    last = None
    while time.time() < deadline:
        code, payload, _ = call("GET", f"/sandboxes/{sandbox_id}")
        state = (payload.get("sandbox") or payload).get("state") or payload.get("status")
        last = {"http": code, "state": state}
        if state in ("ready", "idle", "running"):
            return last
        if state in ("error", "archived", "stopped"):
            return last
        time.sleep(3)
    return last


def run(sandbox_id, command):
    code, payload, elapsed = call(
        "POST",
        f"/sandboxes/{sandbox_id}/commands",
        {"command": command},
        timeout=120,
    )
    stdout = payload.get("stdout") or (payload.get("command") or {}).get("stdout") or ""
    exit_code = payload.get("exitCode")
    if exit_code is None and isinstance(payload.get("command"), dict):
        exit_code = payload["command"].get("exitCode")
    return {
        "http": code,
        "exit": exit_code,
        "stdout": stdout.strip()[:500],
        "seconds": round(elapsed, 2),
        "error": payload.get("error") or payload.get("code") or payload.get("message"),
    }


def main():
    created = []
    report = {}
    try:
        code, payload, elapsed = call(
            "POST",
            "/sandboxes",
            {"type": "small", "ttlSeconds": 600, "noEnv": True},
        )
        parent = sid(payload)
        report["create"] = {
            "http": code,
            "id": parent,
            "seconds": round(elapsed, 2),
            "error": None if parent else payload,
        }
        if not parent:
            print(json.dumps(report, indent=2))
            return
        created.append(parent)
        report["parent_ready"] = wait_ready(parent)
        report["fork_inside"] = run(
            parent,
            "python3 -c 'import os; p=os.fork(); "
            "(os.waitpid(p,0), print(\"parent got %d\" % p)) if p else "
            "(print(\"child got 0\"), os._exit(0))'",
        )
        report["write"] = run(
            parent, "printf 'the pledge\\n' > /tmp/llmday.txt && cat /tmp/llmday.txt"
        )
        idem = str(uuid.uuid4())
        code, payload, elapsed = call(
            "POST",
            f"/sandboxes/{parent}/fork",
            {"type": "small", "ttlSeconds": 300},
            headers={"Idempotency-Key": idem},
        )
        child = sid(payload)
        report["fork"] = {
            "http": code,
            "id": child,
            "seconds": round(elapsed, 2),
            "error": None if child else payload,
        }
        if child:
            created.append(child)
            report["child_ready"] = wait_ready(child)
            report["child_read"] = run(child, "cat /tmp/llmday.txt; echo id=$(hostname)")
            code2, payload2, elapsed2 = call(
                "POST",
                f"/sandboxes/{parent}/fork",
                {"type": "small", "ttlSeconds": 300},
                headers={"Idempotency-Key": idem},
            )
            report["fork_retry"] = {
                "http": code2,
                "id": sid(payload2),
                "same": sid(payload2) == child,
                "seconds": round(elapsed2, 2),
            }
    finally:
        stopped = []
        for sandbox_id in created:
            code, payload, elapsed = call("POST", f"/sandboxes/{sandbox_id}/stop")
            stopped.append({"id": sandbox_id, "http": code, "seconds": round(elapsed, 2)})
        report["stopped"] = stopped
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
