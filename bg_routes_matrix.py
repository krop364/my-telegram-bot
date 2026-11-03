
"""Universal Biblio-Globus route and price diagnostic.

Reads:
    bg_countries.json
    bg_departures.json

Checks:
    xml=11 -> tour programs
    xml=51 -> published prices and booking links

Standalone script. Does not import or modify bot.py or bg_search.py.

Run:
    python bg_routes_matrix.py

Optional:
    python bg_routes_matrix.py --all
    python bg_routes_matrix.py --countries 20
    python bg_routes_matrix.py --max-schedule 60 --max-prices 20
"""

import argparse
import json
import re
import traceback
from collections import Counter
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

# These codes were observed in our previous BG tests.
# We do not extrapolate them to arbitrary dates.
VERIFIED_PERSONS = {
    "15.11.2026": "0151019900.0151019900",
    "20.11.2026": "0201019900.0201019900",
}

TEST_DATES = tuple(VERIFIED_PERSONS)


def normalize(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip().casefold().replace("ё", "е"),
    )


def load_catalog(filename):
    path = ROOT / filename

    if not path.is_file():
        raise FileNotFoundError(
            f"Не найден {filename} рядом с bg_routes_matrix.py"
        )

    data = json.loads(
        path.read_text(encoding="utf-8-sig")
    )

    if not isinstance(data, list):
        raise ValueError(
            f"{filename}: ожидается JSON-список"
        )

    rows = [
        row
        for row in data
        if isinstance(row, dict)
    ]

    print(
        f"Каталог {filename}: "
        f"{len(rows)} записей"
    )

    return rows


def build_catalogs():
    countries_raw = load_catalog("bg_countries.json")
    cities_raw = load_catalog("bg_departures.json")

    countries = {}

    for row in countries_raw:
        country_id = str(row.get("id") or "")
        title = str(row.get("title_ru") or "").strip()

        if not (
            country_id.startswith("1004")
            and country_id.isdigit()
            and title
        ):
            continue

        countries[country_id] = row

    cities = {}

    for row in cities_raw:
        city_id = str(row.get("id") or "")
        title = str(row.get("title_ru") or "").strip()

        if not (
            city_id.startswith("1005")
            and city_id.isdigit()
            and title
        ):
            continue

        cities[city_id] = row

    active_countries = [
        row
        for row in countries.values()
        if normalize(row.get("tours")) == "да"
    ]

    active_countries.sort(
        key=lambda row: normalize(
            row.get("title_ru")
        )
    )

    print()
    print("=== КАТАЛОГИ BG ===")
    print("Всего стран:", len(countries))
    print(
        "Стран с tours=Да:",
        len(active_countries)
    )
    print(
        "Географических записей 1005:",
        len(cities)
    )

    return active_countries, cities


def get_allowed_cities(country, cities):
    """Use country.town_from as BG's departure-city list."""

    raw = str(country.get("town_from") or "")

    if not raw.strip():
        return []

    city_ids = [
        value.strip()
        for value in raw.split("#")
        if value.strip()
    ]

    result = []
    seen = set()

    for city_id in city_ids:
        if city_id in seen:
            continue

        seen.add(city_id)

        row = cities.get(city_id)

        if not row:
            continue

        result.append((
            city_id,
            str(row.get("title_ru") or ""),
        ))

    return result


def get_json(session, params):
    response = session.get(
        API,
        params=params,
        timeout=TIMEOUT,
    )

    response.raise_for_status()

    try:
        data = response.json()
    except ValueError:
        raise ValueError(
            "BG вернул не JSON: "
            + response.text[:180]
        )

    if not isinstance(data, dict):
        raise ValueError(
            "BG вернул JSON не в формате объекта"
        )

    return data


def parse_nights(value):
    """Parse durations such as '/6/9/13'."""

    return {
        int(number)
        for number in re.findall(
            r"\d+",
            str(value or ""),
        )
    }


def discover_programs(
    session,
    country_id,
    city_id,
):
    """xml=11: flt=country, flt2=departure city."""

    data = get_json(
        session,
        [
            ("action", "files"),
            ("flt", country_id),
            ("flt2", city_id),
            ("xml", "11"),
        ],
    )

    if data.get("ERROR"):
        print(
            "    BG ERROR:",
            str(data["ERROR"])[:180],
        )
        return []

    entries = data.get("entries") or []

    if not isinstance(entries, list):
        print(
            "    ОШИБКА: entries не список"
        )
        return []

    return [
        entry
        for entry in entries
        if isinstance(entry, dict)
    ]


def matching_programs(entries):
    """Find programs on previously tested dates."""

    result = {}
    seen_dates = set()

    for row in entries:
        day = str(row.get("date") or "")

        if day:
            seen_dates.add(day)

        if day not in VERIFIED_PERSONS:
            continue

        program = str(
            row.get("id_price") or ""
        )

        if not program.isdigit():
            continue

        durations = sorted(
            n
            for n in parse_nights(
                row.get("duration")
            )
            if 1 <= n <= 30
        )

        for nights in durations:
            key = (
                program,
                day,
                nights,
            )

            result.setdefault(
                key,
                row,
            )

    return result, seen_dates


def booking_link(
    section,
    entry,
    price,
    persons,
    program,
):
    """Build URL from BG's own fragments."""

    href0 = str(
        section.get("href0") or ""
    )

    href1 = str(
        entry.get("href1") or ""
    )

    href2 = str(
        price.get("href2") or ""
    )

    if (
        "/zaya" not in href0
        or "templ=" not in href1
    ):
        return None

    link = (
        urljoin(BASE, href0)
        + href1
        + "&p="
        + persons
        + href2
    )

    parsed = urlsplit(link)
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

    if (
        query.get("p", [""])[0]
        != persons
    ):
        return None

    if (
        query.get("templ", [""])[0]
        != str(program)
    ):
        return None

    # Do NOT reject by dt or kol:
    # those can represent one hotel/stage of a combined tour.
    return link


def fetch_prices(
    session,
    country_id,
    city_id,
    program,
    day,
    nights,
):
    """xml=51: obtain public prices for one program."""

    persons = VERIFIED_PERSONS[day]

    params = [
        ("xml", "51"),
        ("action", "price"),
        ("id_price", program),
        ("flt2", city_id),
    ]

    params.extend(
        ("f8", meal)
        for meal in (
            "BB",
            "HB",
            "FB",
            "AI",
            "AO",
        )
    )

    params.extend([
        ("entr", "-100"),
        ("data", day),
        ("f7", str(nights)),
        ("flt", country_id),
        ("p", persons),
    ])

    data = get_json(
        session,
        params,
    )

    if data.get("ERROR"):
        print(
            "      BG ERROR:",
            str(data["ERROR"])[:180],
        )
        return []

    section = (
        data.get("PRICE_SECTION")
        or {}
    )

    entries = (
        section.get("entries")
        or []
    )

    if not isinstance(entries, list):
        print(
            "      ОШИБКА: PRICE_SECTION.entries не список"
        )
        return []

    filters = data.get("FILTER") or {}

    hotels = {}

    if isinstance(filters, dict):
        for hotel in filters.get("HOTELS") or []:
            if isinstance(hotel, dict):
                hotels[
                    str(hotel.get("ID"))
                ] = str(
                    hotel.get("TITLE")
                    or ""
                )

    valid = []
    rejected = Counter()

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        # Validate the package itself.
        if (
            str(entry.get("tour_date"))
            != day
        ):
            rejected["дата"] += 1
            continue

        if (
            str(entry.get("duration"))
            != str(nights)
        ):
            rejected["ночи"] += 1
            continue

        prices = (
            entry.get("prices")
            or []
        )

        if not isinstance(prices, list):
            continue

        for price in prices:
            if not isinstance(price, dict):
                continue

            raw_rub = re.sub(
                r"\s+",
                "",
                str(
                    price.get("RUR")
                    or ""
                ),
            )

            try:
                rub = int(raw_rub)
            except (
                ValueError,
                TypeError,
            ):
                rejected["цена"] += 1
                continue

            if rub <= 0:
                rejected["цена"] += 1
                continue

            link = booking_link(
                section,
                entry,
                price,
                persons,
                program,
            )

            if not link:
                rejected["ссылка"] += 1
                continue

            hotel_id = str(
                entry.get("id_hotel")
                or ""
            )

            hotel_name = hotels.get(
                hotel_id,
                "",
            )

            airline = str(
                entry.get("aircompany")
                or ""
            )

            valid.append({
                "price_rub": rub,
                "hotel": hotel_name,
                "hotel_id": hotel_id,
                "airline": airline,
                "link": link,
            })

    # One record per unique booking link.
    unique = {}

    for item in valid:
        link = item["link"]

        if (
            link not in unique
            or item["price_rub"]
            < unique[link]["price_rub"]
        ):
            unique[link] = item

    offers = sorted(
        unique.values(),
        key=lambda x: x["price_rub"],
    )

    print(
        "      xml=51:",
        len(entries),
        "строк,",
        len(offers),
        "уникальных предложений",
    )

    if rejected:
        print(
            "      Отклонено:",
            dict(rejected),
        )

    if section.get("next_page"):
        print(
            "      ВНИМАНИЕ: BG указал next_page; "
            "проверена только полученная страница"
        )

    for item in offers[:2]:
        query = parse_qs(
            urlsplit(
                item["link"]
            ).query
        )

        print(
            "      ОТЕЛЬ:",
            item["hotel"]
            or "[название отсутствует]",
        )

        print(
            "      ЦЕНА:",
            f'{item["price_rub"]:,} ₽',
        )

        print(
            "      ПОЛНЫЙ ТУР:",
            day,
            "|",
            nights,
            "ночей",
        )

        print(
            "      В ССЫЛКЕ:",
            "dt=",
            query.get("dt", [""])[0],
            "| kol=",
            query.get("kol", [""])[0],
        )

        print(
            "      БРОНИРОВАНИЕ:",
            item["link"][:350],
        )

    return offers


def select_countries(
    countries,
    count,
    all_countries,
):
    if all_countries:
        return countries

    count = max(
        1,
        min(count, len(countries)),
    )

    # Spread the sample across the whole catalog.
    indexes = [
        i * len(countries) // count
        for i in range(count)
    ]

    return [
        countries[i]
        for i in indexes
    ]


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--all",
        action="store_true",
        help="Select all countries with tours=Да",
    )

    parser.add_argument(
        "--countries",
        type=int,
        default=15,
        help="Countries in the default sample",
    )

    parser.add_argument(
        "--max-schedule",
        type=int,
        default=45,
        help="Maximum xml=11 requests",
    )

    parser.add_argument(
        "--max-prices",
        type=int,
        default=15,
        help="Maximum xml=51 requests",
    )

    parser.add_argument(
        "--cities-per-country",
        type=int,
        default=3,
        help="Departure cities checked per country",
    )

    args = parser.parse_args()

    print(
        "=== BG: УНИВЕРСАЛЬНЫЙ ТЕСТ "
        "ВСЕХ ДОСТУПНЫХ НАПРАВЛЕНИЙ ==="
    )

    countries, cities = build_catalogs()

    selected = select_countries(
        countries,
        args.countries,
        args.all,
    )

    max_schedule = max(
        1,
        args.max_schedule,
    )

    max_prices = max(
        0,
        args.max_prices,
    )

    max_cities = max(
        1,
        args.cities_per_country,
    )

    print()
    print(
        "Выбрано стран:",
        len(selected),
    )

    print(
        "Лимит xml=11:",
        max_schedule,
    )

    print(
        "Лимит xml=51:",
        max_prices,
    )

    print(
        "Городов на страну:",
        max_cities,
    )

    print(
        "Проверенные даты для цен:",
        ", ".join(TEST_DATES),
    )

    session = requests.Session()
    session.headers.update(
        HEADERS
    )

    schedule_calls = 0
    price_calls = 0

    countries_with_schedule = set()
    countries_with_prices = set()

    total_offers = 0
    stats = Counter()

    for country in selected:
        if schedule_calls >= max_schedule:
            print(
                "\nДостигнут лимит xml=11."
            )
            break

        country_id = str(
            country.get("id")
        )

        country_name = str(
            country.get("title_ru")
            or ""
        )

        departure_cities = get_allowed_cities(
            country,
            cities,
        )

        print()
        print("=" * 72)

        print(
            "СТРАНА:",
            country_name,
            "|",
            country_id,
        )

        print(
            "Городов в town_from:",
            len(departure_cities),
        )

        if not departure_cities:
            stats["нет городов в town_from"] += 1

            print(
                "Нет городов вылета в каталоге. "
                "Страна не исключается из будущего "
                "универсального поиска."
            )

            continue

        # Prefer cities that appear in the country's
        # published departure list. No country-specific IDs.
        checked_cities = departure_cities[
            :max_cities
        ]

        for city_id, city_name in checked_cities:
            if schedule_calls >= max_schedule:
                break

            schedule_calls += 1

            print()
            print(
                "  ВЫЛЕТ:",
                city_name,
                "|",
                city_id,
            )

            try:
                entries = discover_programs(
                    session,
                    country_id,
                    city_id,
                )

            except Exception as exc:
                print(
                    "    ОШИБКА xml=11:",
                    type(exc).__name__,
                    str(exc)[:180],
                )

                stats["ошибка xml=11"] += 1
                continue

            print(
                "    xml=11:",
                len(entries),
                "строк расписания",
            )

            if not entries:
                stats["пустое расписание"] += 1
                continue

            countries_with_schedule.add(
                country_id
            )

            stats["расписание найдено"] += 1

            matching, dates = matching_programs(
                entries
            )

            print(
                "    Уникальных дат в расписании:",
                len(dates),
            )

            print(
                "    Комбинаций программ "
                "на проверенные даты:",
                len(matching),
            )

            if not matching:
                stats[
                    "нет программ на тестовые даты"
                ] += 1

                print(
                    "    На 15/20.11.2026 совпадений нет. "
                    "Это не означает отсутствие туров."
                )

                continue

            if price_calls >= max_prices:
                print(
                    "    Лимит xml=51 достигнут. "
                    "Расписание проверено, "
                    "цены пропущены."
                )

                continue

            # At most two price checks per departure city.
            for (
                program,
                day,
                nights,
            ), row in list(
                matching.items()
            )[:2]:

                if price_calls >= max_prices:
                    break

                price_calls += 1

                route_name = re.sub(
                    r"<[^>]+>",
                    "",
                    str(
                        row.get("route")
                        or ""
                    ),
                )[:100]

                print()
                print(
                    "    ПРОГРАММА:",
                    program,
                )

                print(
                    "    МАРШРУТ:",
                    route_name,
                )

                print(
                    "    ДАТА:",
                    day,
                    "| НОЧЕЙ:",
                    nights,
                )

                try:
                    offers = fetch_prices(
                        session,
                        country_id,
                        city_id,
                        program,
                        day,
                        nights,
                    )

                except Exception as exc:
                    print(
                        "      ОШИБКА xml=51:",
                        type(exc).__name__,
                        str(exc)[:180],
                    )

                    stats["ошибка xml=51"] += 1
                    continue

                if offers:
                    countries_with_prices.add(
                        country_id
                    )

                    total_offers += len(
                        offers
                    )

                    stats[
                        "запросы с ценами"
                    ] += 1

                else:
                    stats[
                        "запросы без подходящих цен"
                    ] += 1

    print()
    print("=" * 72)
    print("=== ИТОГИ УНИВЕРСАЛЬНОГО ТЕСТА ===")

    print(
        "Стран в выборке:",
        len(selected),
    )

    print(
        "Стран с непустым xml=11:",
        len(countries_with_schedule),
    )

    print(
        "Стран с ценами и ссылками:",
        len(countries_with_prices),
    )

    print(
        "Запросов xml=11:",
        schedule_calls,
    )

    print(
        "Запросов xml=51:",
        price_calls,
    )

    print(
        "Всего найдено предложений:",
        total_offers,
    )

    print(
        "Статистика:",
        dict(stats),
    )

    print()
    print(
        "ВАЖНО: тест выборочный. "
        "Страны без цен на проверенных датах "
        "не считаются недоступными."
    )

    print(
        "Ссылки являются ссылками BG, "
        "но тест не подтверждает завершение бронирования."
    )

    print(
        "\n=== КОНЕЦ ==="
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
