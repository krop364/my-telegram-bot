import re
import requests
from collections import Counter
from urllib.parse import unquote, parse_qs

BASE = "https://www.bgoperator.ru/site"

DATES = ["15.11.2026", "20.11.2026", "25.11.2026"]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,*/*",
})


def extract_values(html, key):
    """Ищет значения параметра в URL и HTML-атрибутах."""
    text = unquote(html)

    patterns = [
        rf"(?:[?&]|&amp;){re.escape(key)}=([^&\s\"'<>]+)",
        rf'["\']{re.escape(key)}["\']\s*:\s*["\']([^"\']+)',
        rf'["\']{re.escape(key)}["\']\s*,\s*["\']([^"\']+)',
    ]

    values = []
    for pattern in patterns:
        values.extend(re.findall(pattern, text, re.I))

    return Counter(values)


def inspect_date(day):
    params = {
        "action": "price",
        "tid": "211",
        "flt": "100410000047",
        "flt2": "100510345650",
        "bfr": "1",
        "data": day,
        "d2": day,
        "f7": "8",
        "ho": "0",
        "ins": "15-40000-USD",
    }

    try:
        response = session.get(BASE, params=params, timeout=40)
        response.raise_for_status()
    except requests.RequestException as exc:
        print("REQUEST ERROR:", exc)
        return

    html = response.text

    print("\nDATE:", day)
    print("HTTP:", response.status_code)
    print("HTML LENGTH:", len(html))

    for key in ("p", "id_price", "F4", "f7"):
        values = extract_values(html, key)
        print(f"\n{key} VALUES:", len(values))

        for value, count in values.most_common(12):
            print(" ", repr(value[:180]), "COUNT:", count)

    print("\nPASSENGER-RELATED FRAGMENTS:")

    patterns = [
        r".{0,100}(?:возраст|взросл|ребен|дети|турист).{0,140}",
        r".{0,100}(?:child|adult|passenger|pax).{0,140}",
    ]

    found = set()

    for pattern in patterns:
        for fragment in re.findall(
            pattern, html, flags=re.I | re.S
        ):
            cleaned = re.sub(r"\s+", " ", fragment)
            cleaned = re.sub(r"<[^>]+>", " ", cleaned)

            if cleaned not in found:
                found.add(cleaned)
                print(" ", cleaned[:240])

            if len(found) >= 12:
                break

        if len(found) >= 12:
            break

    if not found:
        print(" No passenger-related fragments found")


for date in DATES:
    inspect_date(date)

print("\nDONE")
