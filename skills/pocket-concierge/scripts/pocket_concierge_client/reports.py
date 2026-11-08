"""Offline aggregation of measured command usage."""
import json
import math
from pathlib import Path

from .transport import CliError


def read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError):
        raise CliError("invalid_argument", f"Cannot read CLI JSON result: {path}") from None


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def aggregate_usage(paths):
    paths = [str(Path(p).resolve()) for p in paths]
    if len(set(paths)) != len(paths):
        raise CliError("invalid_argument", "Do not count the same result file twice.")
    commands = []
    for path in paths:
        result = read_json(path)
        if not isinstance(result.get("usage"), dict) or not finite(result["usage"].get("transport_attempts")) or result.get("command") == "usage":
            raise CliError("invalid_argument", f"Expected an individual CLI result with usage: {path}")
        commands.append({"file": path, "command": result.get("command"), "checked_at": result.get("checked_at"), "status": result.get("status"), "usage": result["usage"]})
    def total(key):
        values = [c["usage"].get(key) for c in commands]
        return sum(values) if all(finite(v) for v in values) else None
    dependencies = {}
    for command in commands:
        for dep in command["usage"].get("dependencies", []):
            key = (dep.get("transport"), dep.get("tool"))
            previous = dependencies.setdefault(key, {**dep, "versions": [], "tool_versions": [], "attempts": 0, "successful_reads": 0})
            for field in ("versions", "tool_versions"):
                previous[field] = list(dict.fromkeys(previous[field]+dep.get(field, [])))
            for field in ("attempts", "successful_reads"):
                previous[field] += dep.get(field, 0)
    totals = {key: total(key) for key in ("transport_attempts", "network_requests_started", "browser_launches", "response_body_bytes", "cache_hits", "throttle_wait_ms", "connection_reuses")}
    totals.update(summed_command_elapsed_ms=total("elapsed_ms"), metrics_complete=all(c["usage"].get("metrics_complete") for c in commands))
    return {"commands": commands, "totals": totals, "dependencies": list(dependencies.values()),
            "note": "Offline sum of recorded command usage. Summed command duration is not wall time when commands overlap; excludes development, tests, model work and this report command. Response bytes are not total wire traffic."}
