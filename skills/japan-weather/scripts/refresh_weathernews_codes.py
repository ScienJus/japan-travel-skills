#!/usr/bin/env python3
"""Maintainer-only: refresh Weathernews forecast code labels (one HTTP read)."""
import datetime as dt
import hashlib
import json

from weather_common import Client
from weathernews import CODES_PATH, LEGEND_URL, IconLegendParser


def save_codes(raw):
    parser = IconLegendParser()
    parser.feed(raw.decode("utf-8"))
    if not all(k in parser.labels for k in ("100", "200", "203", "300", "400")) or len(parser.labels) < 100:
        raise ValueError("Incomplete Weathernews legend; existing file was not overwritten.")
    result = {"source_url": LEGEND_URL, "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "source_sha256": hashlib.sha256(raw).hexdigest(),
              "processing": "Only numeric forecast codes and short labels from Weathernews's published forecast code table. No icons, forecast captures or JMA code labels are bundled.",
              "labels": parser.labels}
    CODES_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    client = Client()
    result = save_codes(client.read(LEGEND_URL))
    print(json.dumps({"file": str(CODES_PATH), "codes": len(result["labels"]), "usage": client.usage()}))
