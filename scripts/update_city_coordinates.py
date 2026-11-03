"""Generate the local Brazilian municipality centroid catalog used by the route map."""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


SERVICE_URL = "https://geo.infrasa.gov.br/server/rest/services/Municipios/FeatureServer/0/query"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "static" / "municipios_brasil_coordinates.json"
PAGE_SIZE = 2_000


def city_key(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(character for character in normalized if not unicodedata.combining(character))
    normalized = re.sub(r"[^A-Za-z0-9 ]+", " ", normalized).upper()
    return re.sub(r"\s+", " ", normalized).strip()


def fetch_page(offset: int) -> list[dict]:
    query = urllib.parse.urlencode(
        {
            "where": "1=1",
            "outFields": "nm_mun,sigla_uf",
            "returnGeometry": "false",
            "returnCentroid": "true",
            "outSR": "4326",
            "orderByFields": "id",
            "resultOffset": offset,
            "resultRecordCount": PAGE_SIZE,
            "f": "json",
        }
    )
    request = urllib.request.Request(
        f"{SERVICE_URL}?{query}",
        headers={"User-Agent": "JR-Dashboard/1.0 (municipality-coordinate-catalog)"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.load(response)
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    return payload.get("features") or []


def main() -> None:
    coordinates: dict[str, list[float]] = {}
    offset = 0
    while True:
        features = fetch_page(offset)
        for feature in features:
            attributes = feature.get("attributes") or {}
            centroid = feature.get("centroid") or {}
            name = city_key(attributes.get("nm_mun"))
            state = str(attributes.get("sigla_uf") or "").strip().upper()
            latitude = centroid.get("y")
            longitude = centroid.get("x")
            if name and state and latitude is not None and longitude is not None:
                coordinates[f"{name}|{state}"] = [round(float(latitude), 6), round(float(longitude), 6)]
        offset += len(features)
        if len(features) < PAGE_SIZE:
            break

    payload = {
        "source": "Malha Municipal Digital do IBGE via Geoportal da Infra S.A.",
        "source_url": "https://geo.infrasa.gov.br/server/rest/services/Municipios/FeatureServer/0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(coordinates),
        "coordinates": dict(sorted(coordinates.items())),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Saved {len(coordinates)} municipalities to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
