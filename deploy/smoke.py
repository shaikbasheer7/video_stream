#!/usr/bin/env python3
"""Smoke / end-to-end test against any environment (local stack, staging, production). Stdlib only.

    python3 deploy/smoke.py --base-url https://staging.example.com            # quick checks
    python3 deploy/smoke.py --base-url ... --full --video clip.mp4           # register-less full path

Credentials for the login and --full steps come from SMOKE_EMAIL / SMOKE_PASSWORD (a dedicated account).
--full uploads the clip, waits for encoding, plays the HLS master + a segment through the CDN with the signed
cookies, then deletes the video again. Exit code 0 only if every step passed.
"""

import argparse
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


class Client:
    def __init__(self, base_url):
        self.base = base_url.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.plain = urllib.request.build_opener()  # presigned S3 URLs: no cookies, no auth header
        self.token = None

    def request(self, method, url, body=None, headers=None, opener=None, raw=False):
        url = url if url.startswith("http") else self.base + url
        data = raw if raw is not False else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(url, data=data, method=method)
        if body is not None and raw is False:
            req.add_header("Content-Type", "application/json")
        if self.token and url.startswith(self.base + "/api/"):
            req.add_header("Authorization", f"Bearer {self.token}")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with (opener or self.opener).open(req, timeout=60) as res:
                return res.status, res.headers, res.read()
        except urllib.error.HTTPError as err:
            return err.code, err.headers, err.read()

    def json(self, method, path, body=None):
        status, _, payload = self.request(method, path, body)
        try:
            return status, json.loads(payload or b"null")
        except ValueError:
            return status, payload[:200]


class Smoke:
    def __init__(self):
        self.failures = 0

    def check(self, name, ok, detail=""):
        print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail) if detail else ''}", flush=True)
        if not ok:
            self.failures += 1
        return ok


def run(args):
    c, s = Client(args.base_url), Smoke()

    status, body = c.json("GET", "/api/health/ready/")
    s.check("readiness: all dependencies up", status == 200, body)

    status, headers, page = c.request("GET", "/")
    s.check("web app served", status == 200 and b'id="root"' in page, status)
    csp = headers.get("Content-Security-Policy", "") if headers else ""
    s.check("security headers present", "default-src 'self'" in csp and headers.get("X-Frame-Options") == "DENY")

    status, body = c.json("GET", "/api/videos/")
    s.check("public video list", status == 200 and "results" in (body or {}), status)

    email, password = os.environ.get("SMOKE_EMAIL"), os.environ.get("SMOKE_PASSWORD")
    if not email or not password:
        print("[SKIP] login and --full (set SMOKE_EMAIL / SMOKE_PASSWORD)")
        return s.failures

    status, body = c.json("POST", "/api/auth/login/", {"email": email, "password": password})
    if not s.check("login", status == 200 and "access" in (body or {}), status):
        return s.failures
    c.token = body["access"]
    status, body = c.json("GET", "/api/auth/me/")
    s.check("authenticated request (/me)", status == 200 and body.get("email") == email.lower(), status)

    if args.full:
        full_path(c, s, Path(args.video), args.timeout)
    return s.failures


def full_path(c, s, video_path, timeout):
    data = video_path.read_bytes()
    title = f"smoke {time.strftime('%Y-%m-%d %H:%M:%S')}"
    status, created = c.json(
        "POST",
        "/api/videos/",
        {"title": title, "filename": video_path.name, "size": len(data), "content_type": "video/mp4"},
    )
    if not s.check("create upload", status == 201, status):
        return
    video_id, upload = created["video"]["id"], created["upload"]
    try:
        if not s.check("small clip uses a single presigned PUT", upload["method"] == "single", upload["method"]):
            return
        status, _, _ = c.request("PUT", upload["url"], raw=data, headers=upload["headers"], opener=c.plain)
        s.check("upload straight to storage", status == 200, status)
        status, body = c.json("POST", f"/api/videos/{video_id}/complete/", {})
        s.check("complete upload", status == 200 and body.get("status") == "uploaded", status)

        deadline, video = time.time() + timeout, {}
        while time.time() < deadline:
            status, video = c.json("GET", f"/api/videos/{video_id}/")
            if video.get("status") in ("ready", "failed"):
                break
            time.sleep(3)
        if not s.check("encoded", video.get("status") == "ready", video.get("status") or "timeout"):
            return
        qualities = [r["quality"] for r in video.get("renditions", [])]
        s.check("renditions", bool(qualities), qualities)

        master_url = video["playback"]["hls_url"]
        status, _, master = c.request("GET", master_url)  # signed cookies from the detail response
        s.check("master playlist via CDN (signed cookies)", status == 200 and master.startswith(b"#EXTM3U"), status)
        variant = next(line for line in master.decode().splitlines() if line and not line.startswith("#"))
        variant_url = master_url.rsplit("/", 1)[0] + "/" + variant
        status, _, playlist = c.request("GET", variant_url)
        segment = next(line for line in playlist.decode().splitlines() if line and not line.startswith("#"))
        status, _, seg = c.request("GET", variant_url.rsplit("/", 1)[0] + "/" + segment)
        s.check("first segment via CDN", status == 200 and len(seg) > 1000, f"{status}, {len(seg)} bytes")

        status, _, _ = c.request("GET", master_url, opener=c.plain)
        s.check("CDN refuses requests without cookies", status == 403, status)
        thumb_status, _, _ = c.request("GET", video["thumbnail_url"], opener=c.plain)
        s.check("thumbnail public via CDN", thumb_status == 200, thumb_status)
    finally:
        status, _ = c.json("DELETE", f"/api/videos/{video_id}/")
        s.check("cleanup: delete smoke video", status == 204, status)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--full", action="store_true", help="upload, encode, play and delete a clip")
    parser.add_argument("--video", default=str(Path(__file__).with_name("smoke-clip.mp4")))
    parser.add_argument("--timeout", type=int, default=600, help="seconds to wait for encoding")
    failures = run(parser.parse_args())
    print("SMOKE TEST " + ("PASSED" if not failures else f"FAILED ({failures})"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
