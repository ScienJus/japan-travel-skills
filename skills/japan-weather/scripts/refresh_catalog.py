#!/usr/bin/env python3
"""Maintainer command: rebuild local JMA routing metadata (five HTTP reads)."""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from weather_common import Client

BASE = "https://www.jma.go.jp/bosai/"
ROUTES = {
    "areas": "common/const/area.json",
    "short_areas": "forecast/const/forecast_area.json",
    "week_areas": "forecast/const/week_area.json",
    "week_area_codes": "forecast/const/week_area05.json",
    "weather_labels": "forecast/",
}


def main():
    client = Client(timeout=20)
    catalog = {"sources": [], "processing": "JMA area fields selected; weather-code labels extracted from the official forecast page. No forecast data is bundled."}
    total = 0
    for key, route in ROUTES.items():
        url = BASE + route
        raw = client.read(url)
        total += len(raw)
        catalog["sources"].append({"url": url, "sha256": hashlib.sha256(raw).hexdigest()})
        if key == "weather_labels":
            # Parse only numeric keys and JSON string arrays; never execute JS.
            html = raw.decode("utf-8")
            match = re.search(r"\.TELOPS=\{(.*?)\};", html, re.S)
            if not match:
                raise ValueError("Cannot locate the JMA weather-code labels")
            labels = {}
            for item in re.finditer(r'(\d{3}):(\[(?:"(?:[^"\\]|\\.)*"(?:,)?)+\])', match.group(1)):
                values = json.loads(item.group(2))
                labels[item.group(1)] = {"ja": values[3], "en": values[4]}
            if not all(code in labels for code in ("100", "200", "300", "400")) or len(labels) < 50:
                raise ValueError("Incomplete JMA weather-code labels")
            catalog["weather_codes"] = labels
        else:
            catalog[key] = json.loads(raw.decode("utf-8"))
    areas = catalog["areas"]
    catalog["areas"] = {
        level: {code: {k: value[k] for k in fields if k in value} for code, value in areas[level].items()}
        for level, fields in {
            "offices": ("name",), "class10s": ("name", "parent"),
            "class15s": ("name", "parent"), "class20s": ("name", "enName", "kana", "parent"),
        }.items()
    }
    # JMA Forecast.Common.getPathCode on the source page combines these products.
    catalog["office_paths"] = {"014030": "014100", "460040": "460100"}
    for code, city in catalog["areas"]["class20s"].items():
        sub = catalog["areas"]["class15s"][city["parent"]]
        region = catalog["areas"]["class10s"][sub["parent"]]
        if region["parent"] not in catalog["areas"]["offices"]:
            raise ValueError("Broken municipality ancestry: " + code)
    catalog["retrieved_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    target = Path(__file__).resolve().parent / "data/catalog.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"file": str(target), "municipalities": len(catalog["areas"]["class20s"]),
                      "weather_codes": len(catalog["weather_codes"]), "http_requests": 5, "response_body_bytes": total}))


if __name__ == "__main__":
    main()
