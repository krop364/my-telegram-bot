
import re
import html
import requests
from collections import Counter
from urllib.parse import parse_qs, urlsplit

URL = "https://www.bgoperator.ru/site"

PARAMS = {
    "action": "price",
    "tid": "211",
    "flt": "100410000047",    # Египет
    "flt2": "100510345650",   # Казань
    "bfr": "1",
    "data": "15.11.2026",
    "d2": "15.11.2026",
    "f7": "8",
    "ho": "0",
    "ins": "15-40000-USD",
}

print("=== BG: РЕАЛЬНЫЕ ПАРАМЕТРЫ ИЗ HTML ===")

response = requests.get(
    URL,
    params=PARAMS,
    headers={
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "ru-RU,ru;q=0.9",
    },
    timeout=60,
)

print("HTTP:", response.status_code)
print("Размер:", len(response.content))
response.raise_for_status()

page = html.unescape(response.text)

# Ищем параметры в URL, атрибутах HTML и JS-строках.
# Не предполагаем заранее, что id_price равен templ.
FIELDS = (
    "id_price",
    "templ",
    "kol",
    "dt",
    "p",
    "cntr",
    "otn",
    "x",
    "otv",
)

def extract_values(text, key):
    pattern = rf"(?:[?&;]|^){re.escape(key)}=([^&#\s\"'<>]+)"
    return re.findall(pattern, text, flags=re.IGNORECASE)


print("\n=== 1. НАЙДЕННЫЕ ПАРАМЕТРЫ ===")

for key in FIELDS:
    values = extract_values(page, key)
    unique = list(dict.fromkeys(values))

    print(f"{key}: найдено {len(values)}, уникальных {len(unique)}")
    print("Примеры:", unique[:8])


print("\n=== 2. ССЫЛКИ С ПАРАМЕТРАМИ ===")

# Ищем небольшие фрагменты вокруг id_price, templ или kol.
patterns = [
    r".{0,180}id_price=.{0,350}",
    r".{0,180}templ=.{0,350}",
    r".{0,180}kol=.{0,350}",
]

shown = set()
count = 0

for pattern in patterns:
    for match in re.finditer(
        pattern,
        page,
        flags=re.IGNORECASE,
    ):
        fragment = match.group(0)
        fragment = re.sub(r"\s+", " ", fragment)

        if fragment in shown:
            continue

        shown.add(fragment)
        count += 1

        print(f"\nФрагмент {count}:")
        print(fragment[:650])

        if count >= 12:
            break

    if count >= 12:
        break


print("\n=== 3. МАРШРУТЫ В HTML ===")

routes = list(dict.fromkeys(
    re.findall(r"\b121\d{9}\b", page)
))

print("Количество:", len(routes))
print("ID:", routes)


print("\n=== 4. УПОМИНАНИЯ 8 НОЧЕЙ ===")

# Это лишь текстовая диагностика, не доказательство
# наличия полноценного тура.
for key in ("kol", "f7", "duration"):
    values = extract_values(page, key)
    counts = Counter(values)

    print(key, ":", dict(counts.most_common(12)))


print("\n=== ГОТОВО ===")
print(
    "Параметры извлечены из HTML. "
    "Пока не отправляем их в API и не считаем "
    "упоминание 8 ночей подтверждённым туром."
)
