import httpx


def geocode_address(address, city=None, zip_code=None):
    """Return (latitude, longitude) from Nominatim, or None on failure."""
    query = address
    if city:
        query += f", {city}"
    if zip_code:
        query += f" {zip_code}"

    try:
        resp = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": "LesTtraiteursEngages/1.0"},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None
        return (float(data[0]["lat"]), float(data[0]["lon"]))
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return None
