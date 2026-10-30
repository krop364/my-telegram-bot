import re
import html
import requests
from collections import Counter
from urllib.parse import urlparse, parse_qs

URL = "https://www.bgoperator.ru/site"

params = {
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

response = session.get(URL, params=params, timeout=60)
response.raise_for_status()

page = html.unescape(response.text)

print("HTTP:", response.status_code)
print("PAGE LENGTH:", len(page))


def clean(value):
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()[:300]


print("\n=== INPUTS AND SELECTS ===")

tags = re.findall(
    r"<(?:input|select|option|button)\b[^>]*>",
    page,
    flags=re.I | re.S,
)

interesting = (
    "adult", "child", "age", "pax", "tourist",
    "people", "person", "pass", "возраст",
    "взрос", "дет", "количество", "p=",
)

found = []
for tag in tags:
    low = tag.lower()
    if any(word in low for word in interesting):
        found.append(clean(tag))

for item in list(dict.fromkeys(found))[:60]:
    print(item)

print("MATCHING CONTROLS:", len(found))


print("\n=== SCRIPT REFERENCES ===")

scripts = re.findall(
    r"<script\b[^>]*src=['\"]([^'\"]+)",
    page,
    flags=re.I,
)

for script in list(dict.fromkeys(scripts))[:35]:
    print(script)


print("\n=== PASSENGER CONTEXT ===")

patterns = [
    r"2\s*взрослых",
    r"возраст[а-я]*",
    r"турист[а-я]*",
    r"количество\s+детей",
]

seen = set()

for pattern in patterns:
    for match in list(re.finditer(pattern, page, re.I))[:8]:
        fragment = clean(
            page[max(0, match.start() - 350):match.end() + 350]
        )
        if fragment not in seen:
            seen.add(fragment)
            print(fragment)


print("\n=== PRICE LINKS: PARAMETER NAMES ===")

keys = Counter()
samples = []

for match in re.finditer(
    r'(?:href|urr)=["\']([^"\']+)',
    page,
    flags=re.I,
):
    link = html.unescape(match.group(1))
    if "id_price=" not in link and "p=" not in link:
        continue

    query = urlparse(link).query
    if not query and "?" not in link:
        query = link.lstrip("&")

    parsed = parse_qs(query)

    keys.update(parsed.keys())

    if len(samples) < 3:
        samples.append({
            key: value[:2]
            for key, value in parsed.items()
            if key in ("p", "id_price", "data", "d2", "f7", "q")
        })

print("PARAMETERS:", keys.most_common(30))

for sample in samples:
    print("SAMPLE:", sample)

print("\nDONE")
