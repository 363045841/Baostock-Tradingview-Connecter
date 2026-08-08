from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
PROXY_CONFIG_FILE = CONFIG_DIR / "proxy.json"


def load_proxy_config() -> dict[str, str]:
    """Load proxy config from ``config/proxy.json``.

    Returns a dict with keys ``http``, ``https``, ``no_proxy``, or empty dict
    if the file does not exist.
    """
    if not PROXY_CONFIG_FILE.is_file():
        return {}
    try:
        raw = json.loads(PROXY_CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            logger.warning("proxy.json must be a JSON object, ignored")
            return {}
        enabled = raw.get("enabled", True)
        if not enabled:
            return {}
        out: dict[str, str] = {}
        if raw.get("http"):
            out["http"] = str(raw["http"]).strip()
        if raw.get("https"):
            out["https"] = str(raw["https"]).strip()
        if raw.get("no_proxy"):
            out["no_proxy"] = str(raw["no_proxy"]).strip()
        return out
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load %s: %s", PROXY_CONFIG_FILE, exc)
        return {}
