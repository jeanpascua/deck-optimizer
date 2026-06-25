#!/usr/bin/env python3
"""Scrape ShareDeck (sharedeck.games) for community-tested Steam Deck settings."""

import json
import logging
import os
import re
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "deck-optimizer" / "sharedeck"
CACHE_TTL_DAYS = 7
REPORTS_URL = "https://sharedeck.games/reports?app_id={}"
HEADERS = "User-Agent: deck-optimizer/1.0"


def _curl_get(url: str) -> str:
    result = subprocess.run(
        ["curl", "-s", "-H", HEADERS, url],
        capture_output=True, text=True, timeout=15,
    )
    return result.stdout if result.returncode == 0 else ""


def _parse_reports(html: str, display_filter: str = "lcd") -> list[dict]:
    blocks = re.split(r'id="report_\d+"', html)
    if len(blocks) <= 1:
        return []

    reports = []
    for block in blocks[1:]:
        report = {}

        display_match = re.search(r'(LCD|OLED)', block, re.IGNORECASE)
        if display_match:
            report["display"] = display_match.group(1).lower()
            if display_filter and report["display"] != display_filter.lower():
                continue

        fps_match = re.search(r'(\d{2,3})\s*fps', block, re.IGNORECASE)
        if fps_match:
            report["fps_limit"] = int(fps_match.group(1))

        tdp_match = re.search(r'(\d{1,2}(?:\.\d)?)\s*[Ww]', block)
        if tdp_match:
            report["tdp"] = float(tdp_match.group(1))

        preset_match = re.search(r'(?:preset|quality|graphics)[:\s]*(low|medium|high|ultra)', block, re.IGNORECASE)
        if preset_match:
            report["graphics_preset"] = preset_match.group(1).lower()

        res_match = re.search(r'(\d{3,4})\s*x\s*(\d{3,4})', block)
        if res_match:
            report["resolution"] = f"{res_match.group(1)}x{res_match.group(2)}"

        proton_match = re.search(r'[Pp]roton\s*([\d][\w.-]*|GE[\w.-]*)', block)
        if proton_match:
            report["proton"] = proton_match.group(1).strip()

        refresh_match = re.search(r'(\d{2,3})\s*[Hh]z', block)
        if refresh_match:
            report["refresh_rate"] = int(refresh_match.group(1))

        power_match = re.search(r'(\d{1,2}(?:\.\d)?)\s*[Ww](?:atts?)', block, re.IGNORECASE)
        if power_match:
            report["power_watts"] = float(power_match.group(1))

        if report and len(report) > 1:
            reports.append(report)

    return reports


def _aggregate(reports: list[dict]) -> dict:
    if not reports:
        return {}

    result = {"source": "sharedeck", "report_count": len(reports)}

    tdps = [r["tdp"] for r in reports if "tdp" in r]
    if tdps:
        tdps.sort()
        result["tdp"] = tdps[len(tdps) // 2]

    fps_vals = [r["fps_limit"] for r in reports if "fps_limit" in r]
    if fps_vals:
        fps_vals.sort()
        result["fps_limit"] = fps_vals[len(fps_vals) // 2]

    presets = [r["graphics_preset"] for r in reports if "graphics_preset" in r]
    if presets:
        result["graphics_preset"] = Counter(presets).most_common(1)[0][0]

    resolutions = [r["resolution"] for r in reports if "resolution" in r]
    if resolutions:
        result["resolution"] = Counter(resolutions).most_common(1)[0][0]

    protons = [r["proton"] for r in reports if "proton" in r]
    if protons:
        result["proton"] = Counter(protons).most_common(1)[0][0]

    power_vals = [r["power_watts"] for r in reports if "power_watts" in r]
    if power_vals:
        result["power_watts"] = round(sum(power_vals) / len(power_vals), 1)

    return result


def get_sharedeck_settings(app_id: str, display_model: str = "lcd") -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{app_id}.json"

    if cache_file.exists():
        age_days = (time.time() - cache_file.stat().st_mtime) / 86400
        if age_days < CACHE_TTL_DAYS:
            try:
                return json.loads(cache_file.read_text())
            except json.JSONDecodeError:
                pass

    logger.info(f"Fetching ShareDeck data for app {app_id}...")
    html = _curl_get(REPORTS_URL.format(app_id))
    if not html:
        logger.info(f"No ShareDeck response for app {app_id}")
        return {}

    reports = _parse_reports(html, display_filter=display_model)
    if not reports:
        reports = _parse_reports(html, display_filter=None)

    settings = _aggregate(reports)

    if settings:
        cache_file.write_text(json.dumps(settings, indent=2))
        logger.info(f"ShareDeck: {len(reports)} reports for app {app_id}: {settings}")

    return settings
