"""Configuration defaults and JSON persistence for the KMTronic antenna controller."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any

DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
DEFAULT_PATTERNS = {
    "N": [1, 0, 0, 0],
    "NE": [0, 1, 0, 0],
    "E": [1, 1, 0, 0],
    "SE": [0, 0, 1, 0],
    "S": [1, 0, 1, 0],
    "SW": [0, 1, 1, 0],
    "W": [1, 1, 1, 0],
    "NW": [0, 0, 0, 1],
}
DEFAULT_AUX_LABELS = ["BPF 1", "BPF 2", "AUX 3", "AUX 4"]
DEFAULT_DIR_COLORS = {d: "#0055cc" for d in DIRS}
DEFAULT_AUX_COLORS = ["#006600", "#006600", "#006600", "#006600"]
DEFAULT_OFF_COLOR = "#cc0000"
DEFAULT_THEME = {
    "appBg": "#f0f0f0",
    "canvasBg": "#ffffff",
    "ringColor": "#cccccc",
    "wedgeColor": "#dbe8fa",
}
DEFAULT_CFG = {
    "transport": "udp",
    "host": "192.168.2.190",
    "port": 12345,
    "user": "admin",
    "password": "admin",
    "mode": "ff",
    "demo": True,
    "offset": 0,
    "dirPatterns": DEFAULT_PATTERNS,
    "auxLabels": DEFAULT_AUX_LABELS,
    "dirColors": DEFAULT_DIR_COLORS,
    "auxColors": DEFAULT_AUX_COLORS,
    "offColor": DEFAULT_OFF_COLOR,
    "theme": DEFAULT_THEME,
}


def config_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "9ca_cfg.json")


def resolve_config_path() -> str:
    path = config_path()
    return os.path.abspath(path)


def load_cfg() -> dict[str, Any]:
    cfg = deepcopy(DEFAULT_CFG)
    path = resolve_config_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        cfg.update(saved)
        if "dirPatterns" not in saved:
            cfg["dirPatterns"] = deepcopy(DEFAULT_PATTERNS)
        if "dirColors" not in saved:
            cfg["dirColors"] = deepcopy(DEFAULT_DIR_COLORS)
        else:
            for direction in DIRS:
                cfg["dirColors"].setdefault(direction, DEFAULT_DIR_COLORS[direction])
        if "auxColors" not in saved or len(cfg.get("auxColors", [])) < 4:
            cfg["auxColors"] = list(DEFAULT_AUX_COLORS)
        if "offColor" not in saved:
            cfg["offColor"] = DEFAULT_OFF_COLOR
        if "theme" not in saved:
            cfg["theme"] = deepcopy(DEFAULT_THEME)
        else:
            for key, value in DEFAULT_THEME.items():
                cfg["theme"].setdefault(key, value)
        if "auxLabels" not in saved:
            cfg["auxLabels"] = list(DEFAULT_AUX_LABELS)
    except (OSError, ValueError):
        pass
    return cfg


def save_cfg(cfg: dict[str, Any]) -> None:
    path = resolve_config_path()
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(cfg, handle, indent=2)
    except OSError:
        pass
