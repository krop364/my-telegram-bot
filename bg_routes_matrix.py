"""Проверка трёх предполагаемых справочников Библио-Глобуса.

Запуск: python bg_routes_matrix.py
Не изменяет файлы бота и не требует дополнительных библиотек.
"""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SOURCES = {
    "countries": "https://export.bgoperator.ru/yandex?action=countries",
    "resorts": "https://export.bgoperator.ru/auto/jsonResorts.json",
    "directions": "https://export.bgoperator.ru/auto/homepage-124331253701.js",
}

KEYWORDS = (
    "египет",
    "казань",
    "egypt",
    "kazan",
    "100410000047",
    "100510345650",
)


def inspect(name, url):
    print(f"\n=== {name.upper()} ===")
    print("URL:", url)

    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
        },
    )

    try:
        with urlopen(request, timeout=25) as response:
            raw = response.read(3_000_001)
            print("HTTP:", response.status)
            print(
                "Content-Type:",
                response.headers.get("Content-Type", "unknown"),
            )

            if len(raw) > 3_000_000:
                print("ОТВЕТ СЛИШКОМ БОЛЬШОЙ: показаны первые 3 МБ")

    except HTTPError as error:
        print("HTTP ERROR:", error.code)
        return

    except (URLError, TimeoutError, OSError) as error:
        print("NETWORK ERROR:", str(error)[:300])
        return

    text = raw.decode("utf-8-sig", errors="replace")

    print("Размер полученной части (байт):", len(raw))
    print(
        "Начало ответа:",
        re.sub(r"\s+", " ", text[:450]),
    )

    try:
        data = json.loads(text)

    except json.JSONDecodeError:
        print("Формат: не чистый JSON (возможно XML, JS или HTML)")

    else:
        print("Формат: JSON")

        if isinstance(data, list):
            print("Элементов в корневом списке:", len(data))

            if data:
                print("Пример элемента:", str(data[0])[:350])

        elif isinstance(data, dict):
            print("Ключи корневого объекта:", list(data)[:25])

            for key, value in data.items():
                if isinstance(value, list):
                    print(f"Список {key}: {len(value)} элементов")

    print("Совпадения с Египтом / Казанью / известными ID:")

    lines = text.splitlines()

    matches = [
        line.strip()[:500]
        for line in lines
        if any(k in line.lower() for k in KEYWORDS)
    ]

    if matches:
        for line in matches[:8]:
            print(" -", line)

        if len(matches) > 8:
            print(
                " ... всего строк с совпадениями:",
                len(matches),
            )
    else:
        print("Не обнаружены в полученном фрагменте")


if __name__ == "__main__":
    print("BG: проверка доступности справочников")

    for source_name, source_url in SOURCES.items():
        inspect(source_name, source_url)

    print(
        "\nГОТОВО. HTTP 200 сам по себе не доказывает, "
        "что данные подходят для flt/flt2."
    )
