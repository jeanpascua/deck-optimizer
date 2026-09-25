"""Minimal stdlib HTTP helpers — SteamOS has no pip, so avoid third-party deps like requests."""

import json
import urllib.request


def get_json(url: str, timeout: float = 10):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def post_json(url: str, payload: dict, timeout: float = 10):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "deck-optimizer"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body) if body else None
