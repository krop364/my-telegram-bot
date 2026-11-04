
"""Universal Biblio-Globus diagnostic: catalogs -> xml=11 -> xml=51.

Only this file is changed. Does not import bot.py or bg_search.py.

Default:
  - considers all countries marked tours=Да
  - checks at most 45 country/city schedule combinations
  - checks at most 15 price combinations
  - distributes price checks across different countries

Optional:
  python bg_routes_matrix.py --max-schedule 100 --max-prices 30
"""

import argparse
import json
import re
import traceback
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import requests


BASE = "https://www.bgoperator.ru/"
API = urljoin(BASE, "site")
ROOT = Path(__file__).resolve().parent

TIMEOUT = 35

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": BASE,
}

# Verified in previous BG diagnostic runs for two adults.
# Do not extrapolate to other dates or passenger compositions.
PERSON_CODES = {
    "15.11.2026": "0151019900.0151019900",
    "20.11.2026": "0201019900.0201019900",
}


def norm(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip().casefold().replace("ё", "е"),
    )


def load_json(filename):
    path = ROOT / filename

    if not path.is_file():
        raise FileNotFoundError(
            f"Нет файла {filename} рядом с bg_routes_matrix.py"
        )

    data = json.loads(
        path.read_text(encoding="utf-8-sig")
    )

    if not isinstance(data, list):
        raise ValueError(
            f"{filename}: ожидался JSON-список"
        )

    return [
        row for row in data
        if isinstance(row, dict)
    ]


def load_catalogs():
    raw_countries = load_json("bg_countries.json")
    raw_cities = load_json("bg_departures.json")

    countries = [
        row for row in raw_countries
        if str(row.get("id", "")).startswith("1004")
        and norm(row.get("tours")) == "да"
        and row.get("title_ru")
    ]

    countries.sort(
        key=lambda row: norm(row.get("title_ru"))
    )

    cities = {
        str(row["id"]): row
        for row in raw_cities
        if str(row.get("id", "")).startswith("1005")
        and row.get("title_ru")
    }

    print("=== КАТАЛОГИ ===")
    print("Всего стран:", len(raw_countries))
    print("Стран с tours=Да:", len(countries))
    print("Географических записей:", len(raw_cities))
    print("Записей 1005:", len(cities))

    return countries, cities


def country_cities(country, cities):
    raw = str(country.get("town_from") or "")
    result = []
    seen = set()

    for city_id in raw.split("#"):
        city_id = city_id.strip()

        if city_id in seen:
            continue

        seen.add(city_id)

        row = cities.get(city_id)

        if row:
            result.append((
                city_id,
                str(row.get("title_ru") or ""),
            ))

    return result


def bg_json(session, params):
    response = session.get(
        API,
        params=params,
        timeout=TIMEOUT,
    )

    size = len(response.content)

    if response.status_code != 200:
        raise ValueError(
            f"HTTP {response.status_code}, bytes={size}, "
            f"body={response.text[:120]!r}"
        )

    if not response.content.strip():
        raise ValueError(
            f"ПУСТОЙ ОТВЕТ: HTTP 200, bytes={size}, "
            f"url={response.url[:180]}"
        )

    try:
        data = response.json()
    except ValueError:
        raise ValueError(
            f"НЕ JSON: HTTP 200, bytes={size}, "
            f"body={response.text[:180]!r}"
        )

    if not isinstance(data, dict):
        raise ValueError(
            f"НЕ ОБЪЕКТ: {type(data).__name__}"
        )

    return data


def duration_values(raw):
    return {
        int(x)
        for x in re.findall(r"\d+", str(raw or ""))
    }


def get_schedule(session, country_id, city_id):
    # Confirmed BG parameter mapping:
    # flt = destination country (1004...)
    # flt2 = departure city (1005...)
    data = bg_json(
        session,
        [
            ("action", "files"),
            ("flt", country_id),
            ("flt2", city_id),
            ("xml", "11"),
        ],
    )

    if data.get("ERROR"):
        raise ValueError(
            "BG ERROR: " + str(data["ERROR"])[:160]
        )

    entries = data.get("entries") or []

    if not isinstance(entries, list):
        raise ValueError("xml=11 entries не список")

    return [
        row for row in entries
        if isinstance(row, dict)
    ]


def schedule_candidates(entries):
    """Choose one candidate per program/date; prefer useful durations.

    This prevents the first program's 1- and 2-night
    variants from consuming all price requests.
    """
    candidates = {}
    dates = set()

    for row in entries:
        day = str(row.get("date") or "")
        program = str(row.get("id_price") or "")

        if day:
            dates.add(day)

        if day not in PERSON_CODES:
            continue

        if not program.isdigit():
            continue

        durations = [
            n for n in duration_values(row.get("duration"))
            if 1 <= n <= 30
        ]

        if not durations:
            continue

        # Prefer a standard-length holiday when available.
        preferred = sorted(
            durations,
            key=lambda n: (abs(n - 7), n),
        )[0]

        key = (program, day)

        candidates.setdefault(
            key,
            (
                program,
                day,
                preferred,
                str(row.get("route") or ""),
            ),
        )

    # Prefer 7-night-like options, then date/program.
    ordered = sorted(
        candidates.values(),
        key=lambda x: (
            abs(x[2] - 7),
            x[1],
            x[0],
        ),
    )

    return ordered, dates


def safe_price(value):
    """Accept only unambiguous positive integer RUB amounts."""
    if isinstance(value, bool):
        return None

    raw = str(value or "").strip()

    if not re.fullmatch(
        r"\d[\d\s\u00a0\u202f]*",
        raw,
    ):
        return None

    try:
        amount = int(re.sub(r"\s+", "", raw))
    except ValueError:
        return None

    return amount if amount > 0 else None


def create_booking_url(
    section,
    entry,
    price,
    persons,
    program,
):
    href0 = str(section.get("href0") or "")
    href1 = str(entry.get("href1") or "")
    href2 = str(price.get("href2") or "")

    if "/zaya" not in href0 or "templ=" not in href1:
        return None

    url = (
        urljoin(BASE, href0)
        + href1
        + "&p="
        + persons
        + href2
    )

    parsed = urlsplit(url)
    query = parse_qs(parsed.query)

    if (
        parsed.scheme != "https"
        or parsed.hostname not in (
            "bgoperator.ru",
            "www.bgoperator.ru",
        )
        or parsed.path != "/zaya"
    ):
        return None

    if query.get("p", [""])[0] != persons:
        return None

    if query.get("templ", [""])[0] != program:
        return None

    # dt and kol may refer to a booking segment.
    # Do not compare them with the full package date/nights.
    return url


def get_prices(
    session,
    country_id,
    city_id,
    program,
    day,
    nights,
):
    persons = PERSON_CODES[day]

    params = [
        ("xml", "51"),
        ("action", "price"),
        ("id_price", program),
        ("flt2", city_id),
    ]

    params.extend(
        ("f8", meal)
        for meal in ("BB", "HB", "FB", "AI", "AO")
    )

    params.extend([
        ("entr", "-100"),
        ("data", day),
        ("f7", str(nights)),
        ("flt", country_id),
        ("p", persons),
    ])

    data = bg_json(session, params)

    if data.get("ERROR"):
        raise ValueError(
            "BG ERROR: " + str(data["ERROR"])[:160]
        )

    section = data.get("PRICE_SECTION") or {}

    if not isinstance(section, dict):
        raise ValueError("PRICE_SECTION не объект")

    entries = section.get("entries") or []

    if not isinstance(entries, list):
        raise ValueError("PRICE_SECTION.entries не список")

    filters = data.get("FILTER") or {}
    hotels = {}

    if isinstance(filters, dict):
        for hotel in filters.get("HOTELS") or []:
            if isinstance(hotel, dict):
                hotels[str(hotel.get("ID"))] = str(
                    hotel.get("TITLE") or ""
                )

    rejected = Counter()
    examples = {}
    valid = {}

    for entry in entries:
        if not isinstance(entry, dict):
            rejected["entry не объект"] += 1
            continue

        if str(entry.get("tour_date")) != day:
            rejected["дата тура"] += 1
            continue

        if str(entry.get("duration")) != str(nights):
            rejected["ночи тура"] += 1
            continue

        prices = entry.get("prices") or []

        if not isinstance(prices, list):
            rejected["prices не список"] += 1
            continue

        if not prices:
            rejected["prices пуст"] += 1
            continue

        for price in prices:
            if not isinstance(price, dict):
                rejected["price не объект"] += 1
                continue

            rub = safe_price(price.get("RUR"))

            if rub is None:
                rejected["цена"] += 1

                if "цена" not in examples:
                    examples["цена"] = {
                        "RUR": price.get("RUR"),
                        "price_keys": list(price.keys())[:25],
                        "price_example": {
                            k: str(v)[:100]
                            for k, v in list(price.items())[:12]
                        },
                    }

                continue

            link = create_booking_url(
                section,
                entry,
                price,
                persons,
                program,
            )

            if not link:
                rejected["ссылка"] += 1

                if "ссылка" not in examples:
                    examples["ссылка"] = {
                        "href0": str(section.get("href0"))[:150],
                        "href1": str(entry.get("href1"))[:150],
                        "href2": str(price.get("href2"))[:150],
                    }

                continue

            hotel_id = str(entry.get("id_hotel") or "")

            offer = {
                "rub": rub,
                "hotel": hotels.get(hotel_id, ""),
                "url": link,
            }

            if (
                link not in valid
                or rub < valid[link]["rub"]
            ):
                valid[link] = offer

    offers = sorted(
        valid.values(),
        key=lambda x: x["rub"],
    )

    print(
        f"    xml=51: entries={len(entries)}, "
        f"valid={len(offers)}, "
        f"rejected={dict(rejected)}"
    )

    if section.get("next_page"):
        print(
            "    ВНИМАНИЕ: next_page — "
            "проверена только полученная страница"
        )

    for reason, example in examples.items():
        print(
            f"    ДИАГНОСТИКА [{reason}]:",
            json.dumps(
                example,
                ensure_ascii=False,
                default=str,
            )[:900],
        )

    for offer in offers[:1]:
        query = parse_qs(
            urlsplit(offer["url"]).query
        )

        print(
            f"    ПРИМЕР: "
            f"{offer['hotel'] or '[отель без названия]'} "
            f"| {offer['rub']:,} ₽"
        )

        print(
            "    Полный тур:",
            day,
            nights,
            "ночей",
        )

        print(
            "    Параметры ссылки:",
            "dt=" + query.get("dt", [""])[0],
            "kol=" + query.get("kol", [""])[0],
        )

        print(
            "    Бронирование:",
            offer["url"][:300],
        )

    return offers


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--max-schedule",
        type=int,
        default=45,
    )

    parser.add_argument(
        "--max-prices",
        type=int,
        default=15,
    )

    parser.add_argument(
        "--cities-per-country",
        type=int,
        default=1,
    )

    args = parser.parse_args()

    max_schedule = max(1, args.max_schedule)
    max_prices = max(0, args.max_prices)
    cities_per_country = max(1, args.cities_per_country)

    print(
        "=== BG: УНИВЕРСАЛЬНАЯ ДИАГНОСТИКА v2 ==="
    )

    countries, cities = load_catalogs()

    print()
    print(
        "Стран для рассмотрения:",
        len(countries),
    )
    print(
        "Лимит расписаний:",
        max_schedule,
    )
    print(
        "Лимит цен:",
        max_prices,
    )
    print(
        "Городов на страну:",
        cities_per_country,
    )
    print(
        "Даты с проверенными кодами:",
        ", ".join(PERSON_CODES),
    )

    session = requests.Session()
    session.headers.update(HEADERS)

    schedule_calls = 0
    price_calls = 0

    schedule_countries = set()
    price_countries = set()
    failed_countries = set()
    no_city_countries = []

    stats = Counter()

    # Save one or more price candidates per country.
    price_tasks = defaultdict(list)

    print()
    print("=== ЭТАП 1: РАСПИСАНИЯ xml=11 ===")

    for country in countries:
        if schedule_calls >= max_schedule:
            print(
                "\nЛимит расписаний достигнут."
            )
            break

        country_id = str(country["id"])
        country_name = str(country["title_ru"])

        departure_cities = country_cities(
            country,
            cities,
        )

        print()
        print(
            f"СТРАНА: {country_name} ({country_id}) "
            f"| городов={len(departure_cities)}"
        )

        if not departure_cities:
            no_city_countries.append(country_name)
            stats["нет town_from"] += 1
            continue

        for city_id, city_name in departure_cities[
            :cities_per_country
        ]:
            if schedule_calls >= max_schedule:
                break

            schedule_calls += 1

            print(
                f"  ВЫЛЕТ: {city_name} ({city_id})"
            )

            try:
                entries = get_schedule(
                    session,
                    country_id,
                    city_id,
                )
            except (
                requests.RequestException,
                ValueError,
            ) as exc:
                print(
                    "    ОШИБКА xml=11:",
                    str(exc)[:250],
                )

                failed_countries.add(country_name)
                stats["ошибка расписания"] += 1
                continue

            print(
                "    Строк расписания:",
                len(entries),
            )

            if not entries:
                stats["пустое расписание"] += 1
                continue

            schedule_countries.add(country_name)
            stats["есть расписание"] += 1

            candidates, dates = schedule_candidates(
                entries
            )

            print(
                "    Уникальных дат:",
                len(dates),
            )
            print(
                "    Кандидатов на проверенные даты:",
                len(candidates),
            )

            if candidates:
                # Keep at most 3 alternatives per country.
                # Price phase will try different countries first.
                for program, day, nights, route in candidates[:3]:
                    price_tasks[country_name].append({
                        "country_id": country_id,
                        "city_id": city_id,
                        "city_name": city_name,
                        "program": program,
                        "day": day,
                        "nights": nights,
                        "route": route,
                    })

    print()
    print("=== ЭТАП 2: ЦЕНЫ xml=51 ===")

    # Round-robin: first candidate from each country,
    # then second candidate, then third.
    # This prevents one country from using all requests.
    ordered_tasks = []

    for index in range(3):
        for country_name, tasks in price_tasks.items():
            if index < len(tasks):
                ordered_tasks.append(
                    (country_name, tasks[index])
                )

    print(
        "Стран с кандидатами на цены:",
        len(price_tasks),
    )
    print(
        "Всего подготовлено запросов:",
        len(ordered_tasks),
    )

    total_offers = 0

    for country_name, task in ordered_tasks:
        if price_calls >= max_prices:
            print(
                "\nЛимит цен достигнут."
            )
            break

        price_calls += 1

        print()
        print(
            f"СТРАНА: {country_name} "
            f"| ВЫЛЕТ: {task['city_name']}"
        )

        print(
            "  ПРОГРАММА:",
            task["program"],
        )

        print(
            "  ДАТА:",
            task["day"],
            "| НОЧЕЙ:",
            task["nights"],
        )

        print(
            "  МАРШРУТ:",
            re.sub(
                r"<[^>]+>",
                "",
                task["route"],
            )[:120],
        )

        try:
            offers = get_prices(
                session,
                task["country_id"],
                task["city_id"],
                task["program"],
                task["day"],
                task["nights"],
            )
        except (
            requests.RequestException,
            ValueError,
            TypeError,
        ) as exc:
            print(
                "    ОШИБКА xml=51:",
                str(exc)[:250],
            )

            stats["ошибка цен"] += 1
            continue

        if offers:
            price_countries.add(country_name)
            total_offers += len(offers)
            stats["запросы с ценами"] += 1
        else:
            stats["запросы без цен"] += 1

    print()
    print("=" * 70)
    print("=== ИТОГИ ===")

    print(
        "Стран с tours=Да:",
        len(countries),
    )
    print(
        "Запросов xml=11:",
        schedule_calls,
    )
    print(
        "Стран с расписанием:",
        len(schedule_countries),
    )
    print(
        "Запросов xml=51:",
        price_calls,
    )
    print(
        "Стран с ценами:",
        len(price_countries),
    )
    print(
        "Всего предложений:",
        total_offers,
    )

    print()
    print("СТРАНЫ С РАСПИСАНИЕМ:")
    for name in sorted(schedule_countries):
        print(" +", name)

    print()
    print("СТРАНЫ С ЦЕНАМИ:")
    if price_countries:
        for name in sorted(price_countries):
            print(" +", name)
    else:
        print(" Нет подтверждённых предложений в выборке")

    print()
    print("СТРАНЫ С ОШИБКАМИ xml=11:")
    if failed_countries:
        for name in sorted(failed_countries):
            print(" !", name)
    else:
        print(" Нет")

    print()
    print(
        "Стран без town_from:",
        len(no_city_countries),
    )

    print(
        "Статистика:",
        dict(stats),
    )

    print()
    print(
        "ПРИМЕЧАНИЕ: проверена только часть "
        "направлений и программ в пределах лимитов."
    )
    print(
        "Отсутствие результата не означает "
        "отсутствие туров в стране."
    )
    print(
        "Цены и ссылки получены из ответов BG; "
        "фактическое бронирование не проверялось."
    )
    print()
    print("=== КОНЕЦ ===")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
