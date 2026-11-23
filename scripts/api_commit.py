#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub git-data API 提交工具（git 协议不可达时的兜底通道）。

用法:
  python3 scripts/api_commit.py <owner/repo> <branch> <msg> <file1> [file2 ...]

流程: 取远端 ref -> 建 blob -> 建 tree -> 建 commit -> 更新 ref
只提交指定文件（相对仓库根），其余文件沿用远端最新 tree。
"""
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"


def token():
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
    req.add_header("User-Agent", "mytv-api-commit")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace") or "{}")
    except Exception as e:
        return -1, {"error": str(e)}


def main():
    repo, branch, msg = sys.argv[1], sys.argv[2], sys.argv[3]
    files = sys.argv[4:]
    tok = token()
    if not tok:
        print("NO_TOKEN")
        return 2
    st, ref = api("/repos/%s/git/ref/heads/%s" % (repo, branch), tok=tok)
    if st != 200:
        print("ref fetch failed", st, ref.get("message"))
        return 1
    base = ref["object"]["sha"]
    print("base commit:", base[:10])

    tree_entries = []
    for f in files:
        raw = open(f, "rb").read()
        st, blob = api("/repos/%s/git/blobs" % repo, method="POST",
                       body={"content": base64.b64encode(raw).decode(), "encoding": "base64"}, tok=tok)
        if st != 201:
            print("blob failed", f, st, blob.get("message"))
            return 1
        tree_entries.append({"path": f, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print("blob %-26s %s" % (f, blob["sha"][:10]))

    st, tree = api("/repos/%s/git/trees" % repo, method="POST",
                   body={"base_tree": base, "tree": tree_entries}, tok=tok)
    if st != 201:
        print("tree failed", st, tree.get("message"))
        return 1
    print("tree:", tree["sha"][:10])

    st, commit = api("/repos/%s/git/commits" % repo, method="POST",
                     body={"message": msg, "tree": tree["sha"], "parents": [base]}, tok=tok)
    if st != 201:
        print("commit failed", st, commit.get("message"))
        return 1
    print("commit:", commit["sha"][:10])

    st, upd = api("/repos/%s/git/refs/heads/%s" % (repo, branch), method="PATCH",
                  body={"sha": commit["sha"], "force": False}, tok=tok)
    if st != 200:
        print("ref update failed", st, upd.get("message"))
        return 1
    print("OK  %s -> %s" % (branch, commit["sha"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
