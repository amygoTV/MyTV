#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""触发 GitHub Actions workflow 并轮询状态。

用法:
  python3 scripts/trigger_workflow.py <owner/repo> <workflow_id> [inputs_json]
  python3 scripts/trigger_workflow.py --poll <owner/repo> <workflow_id> [minutes]
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error

API = "https://api.github.com"


def token():
    """从 git credential manager 取 token（不打印）。"""
    env = dict(os.environ)
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        env.pop(k, None)
    p = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                       capture_output=True, text=True, env=env)
    for line in p.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    return ""


def api(path, method="GET", body=None, tok=None):
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", "Bearer " + tok)
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace") or "{}")
    except Exception as e:
        return -1, {"error": str(e)}


def main():
    tok = token()
    if not tok:
        print("NO_TOKEN")
        return 2
    mode = sys.argv[1]
    repo = sys.argv[2]
    wid = sys.argv[3]
    if mode == "--poll":
        minutes = float(sys.argv[4]) if len(sys.argv) > 4 else 10
        deadline = time.time() + minutes * 60
        seen = None
        while time.time() < deadline:
            st, d = api("/repos/%s/actions/workflows/%s/runs?per_page=5" % (repo, wid), tok=tok)
            runs = d.get("workflow_runs", [])
            if runs:
                r = runs[0]
                key = (r["id"], r["status"], r["conclusion"])
                if key != seen:
                    seen = key
                    print("[%s] run=%s %s/%s sha=%s url=%s" % (
                        time.strftime("%H:%M:%S"), r["id"], r["status"], r["conclusion"],
                        r["head_sha"][:8], r["html_url"]), flush=True)
                if r["status"] == "completed":
                    # 列出 job 步骤结论
                    st2, jd = api("/repos/%s/actions/runs/%s/jobs" % (repo, r["id"]), tok=tok)
                    for j in jd.get("jobs", []):
                        print("  JOB %s: %s" % (j["name"], j["conclusion"]))
                        for s in j.get("steps", []):
                            print("    [%s] %s" % (s["conclusion"], s["name"]))
                    return 0 if r["conclusion"] == "success" else 1
            time.sleep(20)
        print("TIMEOUT waiting")
        return 3
    else:
        inputs = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
        ref = sys.argv[5] if len(sys.argv) > 5 else "master"
        st, d = api("/repos/%s/actions/workflows/%s/dispatches" % (repo, wid),
                    method="POST", body={"ref": ref, "inputs": inputs}, tok=tok)
        print("dispatch status=%s %s" % (st, d.get("message", "")))
        return 0 if st == 204 else 1


if __name__ == "__main__":
    sys.exit(main())
