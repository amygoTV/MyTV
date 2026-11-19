#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate upstream interfaces and regenerate aizheteng.json.

aizheteng.json is a TVBox multi-warehouse index:

    {"urls": [{"name": "...", "url": "..."}, ...]}

Every child URL must point to a single-source TVBox config that contains a
non-empty "sites" array. This script reads the latest mirror list, matches it
against scripts/aizheteng_sources.json, probes candidates with a TVBox-like
User-Agent, and keeps the first working URL for each entry.

Standard library only.
"""

import argparse
import concurrent.futures
import gzip
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Windows 控制台默认可能是 GBK，避免含 emoji 的线路名导致脚本崩溃。
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

UA = "okhttp/3.15"
MAX_BYTES = 2 * 1024 * 1024
SSL_CONTEXT = ssl._create_unverified_context()


def log(message):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), message), flush=True)


def strip_comments(text):
    """Remove // and /* */ comments without touching URL strings."""
    out = []
    index = 0
    length = len(text)
    in_string = False
    escaped = False
    while index < length:
        char = text[index]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] in "/*":
            if text[index + 1] == "/":
                index += 2
                while index < length and text[index] not in "\r\n":
                    index += 1
                continue
            index += 2
            while index + 1 < length and not (
                text[index] == "*" and text[index + 1] == "/"
            ):
                index += 1
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def strip_trailing_commas(text):
    """Remove trailing commas before } or ] outside strings."""
    out = []
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            out.append(char)
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead] in " \t\r\n":
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                continue
        out.append(char)
    return "".join(out)


def parse_config(raw):
    """Return (site_count, "") for a usable single-source TVBox config."""
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except Exception as exc:
            return None, "gzip error: %s" % exc

    text = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return None, "unsupported encoding"

    try:
        data = json.loads(strip_trailing_commas(strip_comments(text)))
    except Exception as exc:
        return None, "invalid json: %s" % str(exc)[:120]

    if not isinstance(data, dict):
        return None, "not a json object"
    sites = data.get("sites")
    if not isinstance(sites, list) or not sites:
        return None, "no non-empty sites array"
    return len(sites), ""


def fetch(url, timeout, retries=2):
    last_error = "unknown error"
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": UA, "Accept": "*/*"},
            )
            with urllib.request.urlopen(
                request, timeout=timeout, context=SSL_CONTEXT
            ) as response:
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    return None, "response too large"
                return data, ""
        except urllib.error.HTTPError as exc:
            last_error = "HTTP %s" % exc.code
            if exc.code in (403, 404, 410, 423):
                break
        except Exception as exc:
            last_error = str(exc)[:160]
        if attempt + 1 < retries:
            time.sleep(1)
    return None, last_error


def validate(url, timeout):
    raw, error = fetch(url, timeout)
    if raw is None:
        return False, error
    count, error = parse_config(raw)
    if count is None:
        return False, error
    return True, "sites=%d" % count


def load_list(path):
    entries = []
    text = Path(path).read_text(encoding="utf-8-sig")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        filename = parts[0].strip()
        if not filename.lower().endswith(".json"):
            continue
        name = re.sub(r"\.json$", "", filename, flags=re.IGNORECASE)
        entries.append(
            {"filename": filename, "name": name, "url": parts[3].strip()}
        )
    return entries


def prefer_previous(candidates, previous_url):
    """Keep the last working URL first so daily runs do not flip mirrors."""
    if previous_url and previous_url in candidates:
        candidates = [previous_url] + [
            url for url in candidates if url != previous_url
        ]
    return candidates


def build_candidates(source, list_entries, mirrors, previous_url=None):
    candidates = []
    seen = set()

    def add(url):
        url = (url or "").strip()
        if url and url not in seen:
            seen.add(url)
            candidates.append(url)

    for match in source.get("match", []):
        for entry in list_entries:
            if entry["name"] != match:
                continue
            encoded = urllib.parse.quote(entry["filename"], safe="")
            for base in mirrors:
                add(base.rstrip("/") + "/tvbox/" + encoded)

    for url in source.get("fallbacks", []):
        add(url)
    return prefer_previous(candidates, previous_url)


def choose(candidates, timeout):
    if not candidates:
        return None, "no candidates"
    failures = []
    for url in candidates:
        ok, detail = validate(url, timeout)
        if ok:
            return url, detail
        failures.append("%s (%s)" % (url, detail))
    return None, "; ".join(failures[-3:])


def process(job, timeout):
    kind, index, name, candidates = job
    url, detail = choose(candidates, timeout)
    return kind, index, name, url, detail


def read_current(path):
    if not path.exists():
        return {"urls": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log("warning: cannot parse %s: %s" % (path, exc))
        return {"urls": []}
    if not isinstance(data, dict) or not isinstance(data.get("urls"), list):
        return {"urls": []}
    return data


def summary_table(rows):
    lines = [
        "| 状态 | 名称 | 地址 | 说明 |",
        "|---|---|---|---|",
    ]
    for status, name, url, detail in rows:
        safe_url = (url or "-").replace("|", "%7C")
        safe_detail = (detail or "-").replace("|", "/")
        lines.append("| %s | %s | %s | %s |" % (status, name, safe_url, safe_detail))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Validate and regenerate aizheteng.json"
    )
    parser.add_argument("--list", default="list.txt", help="mirror list.txt path")
    parser.add_argument(
        "--sources",
        default="scripts/aizheteng_sources.json",
        help="source definitions path",
    )
    parser.add_argument(
        "--output", default="aizheteng.json", help="output index path"
    )
    parser.add_argument("--summary", help="append a Markdown report to this file")
    parser.add_argument("--timeout", type=int, default=15, help="per-request timeout")
    parser.add_argument("--workers", type=int, default=8, help="parallel workers")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the result without writing"
    )
    args = parser.parse_args()

    sources_path = Path(args.sources)
    output_path = Path(args.output)
    list_path = Path(args.list)

    try:
        config = json.loads(sources_path.read_text(encoding="utf-8"))
    except Exception as exc:
        log("error: cannot read %s: %s" % (sources_path, exc))
        return 2

    mirrors = config.get("mirrors") or []
    pinned = config.get("pinned") or []
    definitions = config.get("sources") or []
    if not mirrors:
        log("error: no mirrors configured")
        return 2

    if not list_path.exists():
        log("error: list file not found: %s" % list_path)
        return 2
    list_entries = load_list(list_path)
    if not list_entries:
        log("error: list file is empty or malformed: %s" % list_path)
        return 2
    log("loaded %d interfaces from %s" % (len(list_entries), list_path))

    current = read_current(output_path)
    previous = {}
    for item in current.get("urls", []):
        if isinstance(item, dict) and item.get("name") and item.get("url"):
            previous[item["name"]] = item["url"]

    jobs = []
    for index, pin in enumerate(pinned):
        jobs.append(
            (
                "pinned",
                index,
                pin["name"],
                prefer_previous(
                    list(pin.get("urls", [])), previous.get(pin["name"])
                ),
            )
        )
    for index, source in enumerate(definitions):
        jobs.append(
            (
                "source",
                index,
                source["name"],
                build_candidates(
                    source,
                    list_entries,
                    mirrors,
                    previous.get(source["name"]),
                ),
            )
        )

    log("probing %d entries ..." % len(jobs))
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(process, job, args.timeout) for job in jobs]
        for future in concurrent.futures.as_completed(futures):
            kind, index, name, url, detail = future.result()
            results[(kind, index)] = (name, url, detail)

    output = []
    rows = []
    pinned_ok = 0
    source_ok = 0

    for index, pin in enumerate(pinned):
        name, url, detail = results[("pinned", index)]
        status = "OK"
        if url is None:
            if name in previous:
                url = previous[name]
                status = "KEEP"
            elif pin.get("urls"):
                url = pin["urls"][0]
                status = "FALLBACK"
            else:
                status = "SKIP"
        if url:
            output.append({"url": url, "name": name})
            rows.append((status, name, url, detail))
            if status == "OK":
                pinned_ok += 1
        else:
            rows.append((status, name, "", detail))

    for index, source in enumerate(definitions):
        name, url, detail = results[("source", index)]
        status = "OK"
        if url is None:
            if name in previous:
                url = previous[name]
                status = "KEEP"
            else:
                status = "SKIP"
        if url:
            output.append({"url": url, "name": name})
            rows.append((status, name, url, detail))
            if status == "OK":
                source_ok += 1
        else:
            rows.append((status, name, "", detail))

    defined = {pin["name"] for pin in pinned} | {
        source["name"] for source in definitions
    }
    for item in current.get("urls", []):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        url = item.get("url")
        if not name or not url or name in defined:
            continue
        ok, detail = validate(url, args.timeout)
        if ok:
            output.append({"url": url, "name": name})
            rows.append(("KEEP-UNKNOWN", name, url, detail))
        else:
            rows.append(("DROP-UNKNOWN", name, url, detail))

    document = {"urls": output}
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"

    if args.dry_run:
        print(text)
    else:
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(output_path)

    width = max((len(row[1]) for row in rows), default=10)
    for status, name, url, detail in rows:
        print(
            "[%-11s] %-*s %s (%s)"
            % (status, width, name, url or "-", detail or "-"),
            flush=True,
        )

    log(
        "done: %d entries (%d pinned OK, %d sources OK), output=%s"
        % (len(output), pinned_ok, source_ok, output_path)
    )

    if args.summary:
        report = [
            "## aizheteng.json 自动更新",
            "",
            "共 **%d** 条线路，固定线路 **%d/%d** 验活通过，自动线路 **%d/%d** 验活通过。"
            % (len(output), pinned_ok, len(pinned), source_ok, len(definitions)),
            "",
            summary_table(rows),
            "",
        ]
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(report) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
