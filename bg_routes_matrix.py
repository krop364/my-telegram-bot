import re
import html
import requests
from collections import Counter
from urllib.parse import parse_qs, urlparse

URL = "https://www.bgoperator.ru/site"

PARAMS = {
    "action": "price",
    "tid": "211",
    "flt": "100410000047",
    "flt2": "100510345650",
    "bfr": "1",
    "data": "15.11.2026",
    "d2": "15.11.2026",
    "f7": "8",
    "ho": "0",
    "ins": "15-40000-USD",
}

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0"

response = session.get(URL, params=PARAMS, timeout=60)
response.raise_for_status()

page = html.unescape(response.text)

print("HTTP:", response.status_code)
print("PAGE LENGTH:", len(page))


def parse_link(value):
    value = html.unescape(value)

    if "?" in value:
        query = urlparse(value).query
    else:
        query = value.lstrip("&")

    return parse_qs(query, keep_blank_values=True)


print("\n=== BOOKING LINKS ===")

links = re.findall(
    r'(?:href|urr)=["\']([^"\']+)["\']',
    page,
    flags=re.I,
)

booking = []
seen = set()

for link in links:
    params = parse_link(link)

    if "p" not in params:
        continue

    signature = (
        tuple(params.get("p", [])),
        tuple(params.get("kol", [])),
        tuple(params.get("c", [])),
        tuple(params.get("otn", [])),
        tuple(params.get("id_price", [])),
    )

    if signature in seen:
        continue

    seen.add(signature)
    booking.append(params)

print("UNIQUE BOOKING PARAMETER SETS:", len(booking))

for index, params in enumerate(booking[:8], 1):
    print("\nBOOKING", index)

    for key in (
        "p", "kol", "c", "otn", "sr",
        "cntr", "dt", "id_price",
        "x", "otv", "repl", "templ",
    ):
        if key in params:
            print(key, "=", params[key])


print("\n=== PARAMETER FREQUENCIES ===")

for key in ("p", "kol", "c", "otn", "sr", "cntr"):
    counts = Counter()

    for link in links:
        params = parse_link(link)

        for value in params.get(key, []):
            counts[value] += 1

    print(key, ":", counts.most_common(10))


print("\n=== TOURIST TEXT NEAR BOOKING LINKS ===")

shown = 0

for match in re.finditer(
    r"2\s*взрослых\s*\([^)]*\)",
    page,
    flags=re.I,
):
    fragment = page[
        max(0, match.start() - 180):
        min(len(page), match.end() + 250)
    ]

    fragment = re.sub(r"<[^>]+>", " ", fragment)
    fragment = re.sub(r"\s+", " ", fragment).strip()

    print(fragment[:350])

    shown += 1

    if shown >= 5:
        break


print("\n=== FORM TAGS ===")

forms = re.findall(
    r"<form\b[^>]*>",
    page,
    flags=re.I | re.S,
)

print("FORMS:", len(forms))

for form in forms[:10]:
    print(form[:400])


print("\nDONE")
