
import json
import re
import requests
from pathlib import Path
from collections import Counter

BASE = Path(__file__).resolve().parent

CITY = "Казань"
COUNTRY = "Египет"
DATE = "15.11.2026"
NIGHTS = 8
AGES = [36, 36]

BG_URL = "https://www.bgoperator.ru/site"


def load_json(filename):
    return json.loads(
        (BASE / filename).read_text(encoding="utf-8-sig")
    )


def load_fltx():
    text = (BASE / "bg_resorts.json").read_text(
        encoding="utf-8-sig"
    )
    match = re.search(r"\bvar\s+BG_FLTX\s*=", text)

    if not match:
        raise ValueError("Не найден BG_FLTX")

    return json.loads(
        text[match.end():].strip().rstrip(";").strip()
    )


def get_ids():
    countries = load_json("bg_countries.json")
    fltx = load_fltx()

    country = next(
        (
            item for item in countries
            if item.get("title_ru", "").casefold()
            == COUNTRY.casefold()
        ),
        None,
    )

    if country is None:
        raise ValueError(f"Страна не найдена: {COUNTRY}")

    departures = {}

    for item in fltx.get("flt2", []):
        if isinstance(item, list) and len(item) >= 2:
            info = item[1]
            if isinstance(info, dict) and info.get("n"):
                departures[info["n"].casefold()] = str(item[0])

    city_id = departures.get(CITY.casefold())

    if not city_id:
        raise ValueError(f"Город не найден: {CITY}")

    allowed = set(
        filter(None, country.get("town_from", "").split("#"))
    )

    if city_id not in allowed:
        raise ValueError(
            f"Нет пары {CITY} → {COUNTRY} в справочнике"
        )

    return str(country["id"]), city_id


def build_p():
    # Пока только проверенный состав: 2 взрослых.
    # Для произвольных возрастов генератор ещё требует проверки.
    if DATE != "15.11.2026" or AGES != [36, 36]:
        raise ValueError("Этот тест настроен на проверенный состав")

    return "0151019900.0151019900"


def main():
    country_id, city_id = get_ids()
    passenger_code = build_p()

    print("=== BG LIVE SEARCH DIAGNOSTIC ===")
    print("Маршрут:", CITY, "→", COUNTRY)
    print("Дата:", DATE)
    print("Ночей:", NIGHTS)
    print("Туристы:", AGES)
    print("flt:", country_id)
    print("flt2:", city_id)
    print("p:", passenger_code)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.9",
    })

    # Этап 1: запрос страницы поиска.
    params = {
        "action": "price",
        "tid": "211",
        "flt": country_id,
        "flt2": city_id,
        "bfr": "1",
        "data": DATE,
        "d2": DATE,
        "f7": str(NIGHTS),
        "ho": "0",
        "ins": "15-40000-USD",
    }

    print("\n=== 1. ПОИСКОВАЯ СТРАНИЦА ===")

    try:
        response = session.get(
            BG_URL,
            params=params,
            timeout=45,
        )
        print("HTTP:", response.status_code)
        print("Размер ответа:", len(response.content))
        response.raise_for_status()
    except requests.RequestException as exc:
        print("NETWORK ERROR:", str(exc)[:300])
        return

    html = response.text

    # Собираем ID, которые действительно встречаются
    # в ссылках/атрибутах ответа.
    ids = list(dict.fromkeys(
        re.findall(r"\b121\d{9}\b", html)
    ))

    print("Найдено похожих ID маршрутов:", len(ids))
    print("Первые ID:", ids[:12])

    # Ранее полученный реальный ID маршрута.
    # Используем только как контрольную проверку API.
    known_route = "121110211282"

    print("\n=== 2. КОНТРОЛЬНЫЙ ЗАПРОС BG API ===")
    print("Контрольный маршрут:", known_route)

    api_params = {
        "xml": "31",
        "action": "price",
        "id_price": known_route,
        "p": passenger_code,
    }

    try:
        api_response = session.get(
            BG_URL,
            params=api_params,
            timeout=45,
        )
        print("HTTP:", api_response.status_code)
        print("Размер ответа:", len(api_response.content))
        api_response.raise_for_status()
    except requests.RequestException as exc:
        print("API NETWORK ERROR:", str(exc)[:300])
        return

    try:
        payload = api_response.json()
    except ValueError:
        print("Ответ API не JSON")
        print("Начало ответа:", api_response.text[:350])
        return

    if isinstance(payload, dict):
        print("Ключи ответа:", list(payload)[:20])
        entries = payload.get("entries", [])
    elif isinstance(payload, list):
        entries = payload
    else:
        print("Неожиданный тип ответа:", type(payload).__name__)
        return

    if not isinstance(entries, list):
        print("Поле entries не является списком")
        return

    print("Всего записей:", len(entries))

    if not entries:
        print("Предложений нет или формат запроса неполный")
        return

    print("\nКлючи первой записи:")
    print(list(entries[0])[:35])

    print("\n=== 3. ПРОВЕРКА НОЧЕЙ ===")

    durations = Counter(
        str(entry.get("duration", "нет"))
        for entry in entries
        if isinstance(entry, dict)
    )

    print("Распределение duration:", dict(durations))

    exact_nights = [
        entry for entry in entries
        if isinstance(entry, dict)
        and str(entry.get("duration")) == str(NIGHTS)
    ]

    print(f"Записей ровно на {NIGHTS} ночей:", len(exact_nights))

    print("\n=== 4. ПРИЗНАКИ ПОЛНОГО ТУРА ===")

    for label, items in [
        ("Все записи", entries),
        (f"Ровно {NIGHTS} ночей", exact_nights),
    ]:
        flight_count = sum(
            bool(item.get("flight"))
            for item in items
            if isinstance(item, dict)
        )

        accommodation_count = sum(
            bool(item.get("accomodation"))
            or bool(item.get("accommodation"))
            for item in items
            if isinstance(item, dict)
        )

        both_count = sum(
            bool(item.get("flight"))
            and (
                bool(item.get("accomodation"))
                or bool(item.get("accommodation"))
            )
            for item in items
            if isinstance(item, dict)
        )

        print(
            f"{label}: "
            f"flight={flight_count}, "
            f"accommodation={accommodation_count}, "
            f"both={both_count}"
        )

    print("\n=== 5. ПРИМЕРЫ ЗАПИСЕЙ ===")

    for entry in entries[:2]:
        if not isinstance(entry, dict):
            continue

        sample = {
            key: entry.get(key)
            for key in [
                "id_hotel",
                "tour_date",
                "dt",
                "duration",
                "tourComposition",
                "prices",
            ]
            if key in entry
        }

        print(
            json.dumps(
                sample,
                ensure_ascii=False,
                default=str,
            )[:1500]
        )

    print("\n=== ИТОГ ===")

    if exact_nights:
        print("Найдены записи на запрошенное число ночей.")
    else:
        print(
            "На контрольном маршруте нет записей "
            "ровно на 8 ночей."
        )

    print(
        "ВАЖНО: наличие flight/accomodation как полей "
        "ещё не доказывает корректность полного пакета. "
        "Для этого нужен разбор компонентов и цен."
    )


if __name__ == "__main__":
    main()
