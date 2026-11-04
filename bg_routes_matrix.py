
"""Biblio-Globus universal route diagnostic v3.

Reads:
    bg_countries.json
    bg_departures.json

Uses:
    xml=11 - tour schedule
    xml=51 - prices and booking links

Only this file is changed.

Run:
    python bg_routes_matrix.py

Optional:
    python bg_routes_matrix.py --max-schedule 120 --max-prices 40
    python bg_routes_matrix.py --cities-per-country 3
"""

import argparse
import json
import re
import traceback
from collections import Counter, defaultdict
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

# Previously verified for two adults on these dates.
PERSON_CODES = {
    "15.11.2026": "0151019900.0151019900",
    "20.11.2026": "0201019900.0201019900",
}

MOSCOW_ID = "100510000863"
SPB_ID = "100510001075"


def norm(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip().casefold().replace("ё", "е"),
    )


def load_json(filename):
    path = ROOT / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Файл {filename} не найден"
        )

    data = json.loads(
        path.read_text(encoding="utf-8-sig")
    )

    if not isinstance(data, list):
        raise ValueError(
            f"{filename}: ожидался список"
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
    print("Записей городов 1005:", len(cities))

    return countries, cities


def departure_cities(country, cities):
    raw = str(country.get("town_from") or "")
    result = []
    seen = set()

    for city_id in raw.split("#"):
        city_id = city_id.strip()

        if not city_id or city_id in seen:
            continue

        seen.add(city_id)

        row = cities.get(city_id)

        if row:
            result.append((
                city_id,
                str(row.get("title_ru") or ""),
            ))

    # Prefer Moscow, then St Petersburg,
    # then the country's other listed departure cities.
    result.sort(
        key=lambda item: (
            0 if item[0] == MOSCOW_ID
            else 1 if item[0] == SPB_ID
            else 2,
            norm(item[1]),
        )
    )

    return result


def request_json(session, params):
    response = session.get(
        API,
        params=params,
        timeout=TIMEOUT,
    )

    size = len(response.content)

    if response.status_code != 200:
        raise ValueError(
            f"HTTP {response.status_code}, "
            f"bytes={size}, "
            f"body={response.text[:100]!r}"
        )

    if not response.content.strip():
        raise ValueError(
            f"ПУСТОЙ ОТВЕТ HTTP 200, "
            f"bytes={size}"
        )

    try:
        data = response.json()
    except ValueError:
        raise ValueError(
            f"НЕ JSON, bytes={size}, "
            f"body={response.text[:120]!r}"
        )

    if not isinstance(data, dict):
        raise ValueError(
            "BG вернул JSON не в виде объекта"
        )

    return data


def parse_durations(value):
    return {
        int(x)
        for x in re.findall(
            r"\d+",
            str(value or ""),
        )
    }


def get_schedule(session, country_id, city_id):
    data = request_json(
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
            "BG ERROR: "
            + str(data["ERROR"])[:160]
        )

    entries = data.get("entries") or []

    if not isinstance(entries, list):
        raise ValueError(
            "xml=11 entries не список"
        )

    return [
        row for row in entries
        if isinstance(row, dict)
    ]


def find_candidates(entries):
    """One candidate per program/date, preferring ~7 nights."""

    dates = set()
    found = {}

    for row in entries:
        day = str(row.get("date") or "")
        program = str(row.get("id_price") or "")

        if day:
            dates.add(day)

        if day not in PERSON_CODES:
            continue

        if not program.isdigit():
            continue

        nights_list = [
            n for n in parse_durations(
                row.get("duration")
            )
            if 1 <= n <= 30
        ]

        if not nights_list:
            continue

        nights = min(
            nights_list,
            key=lambda n: (
                abs(n - 7),
                n,
            ),
        )

        key = (program, day)

        found.setdefault(
            key,
            {
                "program": program,
                "day": day,
                "nights": nights,
                "route": str(
                    row.get("route") or ""
                ),
            },
        )

    candidates = sorted(
        found.values(),
        key=lambda x: (
            abs(x["nights"] - 7),
            x["day"],
            x["program"],
        ),
    )

    return candidates, dates


def positive_integer(value):
    if isinstance(value, bool):
        return None

    raw = str(value or "").strip()

    if not re.fullmatch(
        r"\d[\d\s\u00a0\u202f]*",
        raw,
    ):
        return None

    try:
        number = int(
            re.sub(r"\s+", "", raw)
        )
    except ValueError:
        return None

    return number if number > 0 else None


def extract_price(price):
    """Return (amount, source_field, currency_confirmed).

    RUR is treated as RUB.
    amount is accepted but its currency remains unconfirmed.
    """

    rub = positive_integer(
        price.get("RUR")
    )

    if rub is not None:
        return rub, "RUR", "RUB"

    amount = positive_integer(
        price.get("amount")
    )

    if amount is not None:
        return amount, "amount", None

    return None, None, None


def booking_url(
    section,
    entry,
    price,
    persons,
    program,
):
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

    if (
        query.get("templ", [""])[0]
        != program
    ):
        return None

    if (
        query.get("p", [""])[0]
        != persons
    ):
        return None

    # Combined tours can have segment-specific dt/kol.
    return url


def get_prices(
    session,
    country_id,
    city_id,
    program,
    day,
    nights,
    country_currency,
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

    data = request_json(
        session,
        params,
    )

    if data.get("ERROR"):
        raise ValueError(
            "BG ERROR: "
            + str(data["ERROR"])[:160]
        )

    section = (
        data.get("PRICE_SECTION")
        or {}
    )

    if not isinstance(section, dict):
        raise ValueError(
            "PRICE_SECTION не объект"
        )

    entries = (
        section.get("entries")
        or []
    )

    if not isinstance(entries, list):
        raise ValueError(
            "PRICE_SECTION.entries не список"
        )

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

    valid = {}
    rejected = Counter()
    source_counts = Counter()
    diagnostic_examples = {}

    for entry in entries:
        if not isinstance(entry, dict):
            continue

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
            rejected["prices не список"] += 1
            continue

        for price in prices:
            if not isinstance(price, dict):
                continue

            amount, source, currency = extract_price(
                price
            )

            if amount is None:
                rejected["нет числовой цены"] += 1

                if "price" not in diagnostic_examples:
                    diagnostic_examples["price"] = {
                        "keys": list(price.keys())[:20],
                        "sample": {
                            k: str(v)[:100]
                            for k, v in list(price.items())[:10]
                        },
                    }

                continue

            link = booking_url(
                section,
                entry,
                price,
                persons,
                program,
            )

            if not link:
                rejected["ссылка"] += 1

                if "link" not in diagnostic_examples:
                    diagnostic_examples["link"] = {
                        "href0": str(
                            section.get("href0")
                        )[:120],
                        "href1": str(
                            entry.get("href1")
                        )[:120],
                        "href2": str(
                            price.get("href2")
                        )[:120],
                    }

                continue

            source_counts[source] += 1

            hotel_id = str(
                entry.get("id_hotel")
                or ""
            )

            offer = {
                "amount": amount,
                "source": source,
                "currency": currency,
                "hotel": hotels.get(
                    hotel_id,
                    "",
                ),
                "url": link,
            }

            if (
                link not in valid
                or amount < valid[link]["amount"]
            ):
                valid[link] = offer

    offers = sorted(
        valid.values(),
        key=lambda x: (
            x["currency"] or "",
            x["amount"],
        ),
    )

    confirmed_rub = [
        offer for offer in offers
        if offer["currency"] == "RUB"
    ]

    unknown_currency = [
        offer for offer in offers
        if offer["currency"] is None
    ]

    print(
        "    xml=51:",
        f"entries={len(entries)}",
        f"offers={len(offers)}",
        f"RUB={len(confirmed_rub)}",
        f"currency_unknown={len(unknown_currency)}",
    )

    print(
        "    Источники цен:",
        dict(source_counts),
    )

    if rejected:
        print(
            "    Отклонено:",
            dict(rejected),
        )

    if section.get("next_page"):
        print(
            "    ВНИМАНИЕ: next_page; "
            "проверена одна страница"
        )

    for kind, example in diagnostic_examples.items():
        print(
            f"    ДИАГНОСТИКА {kind}:",
            json.dumps(
                example,
                ensure_ascii=False,
            )[:800],
        )

    if unknown_currency:
        print(
            "    ВАЛЮТА НЕ ПОДТВЕРЖДЕНА:",
            f"site_cur={country_currency!r}",
        )

    for offer in (
        confirmed_rub[:1]
        + unknown_currency[:1]
    ):
        currency_label = (
            "RUB"
            if offer["currency"] == "RUB"
            else "валюта не подтверждена"
        )

        print(
            "    ПРИМЕР:",
            offer["hotel"]
            or "[без названия отеля]",
            "|",
            offer["amount"],
            "|",
            currency_label,
            "| поле:",
            offer["source"],
        )

        query = parse_qs(
            urlsplit(
                offer["url"]
            ).query
        )

        print(
            "    В ссылке:",
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
        default=90,
    )

    parser.add_argument(
        "--max-prices",
        type=int,
        default=25,
    )

    parser.add_argument(
        "--cities-per-country",
        type=int,
        default=3,
    )

    args = parser.parse_args()

    max_schedule = max(
        1,
        args.max_schedule,
    )

    max_prices = max(
        0,
        args.max_prices,
    )

    cities_per_country = max(
        1,
        args.cities_per_country,
    )

    print(
        "=== BG: УНИВЕРСАЛЬНАЯ ДИАГНОСТИКА v3 ==="
    )

    countries, cities = load_catalogs()

    print()
    print(
        "Стран с tours=Да:",
        len(countries),
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
        cities_per_country,
    )

    session = requests.Session()
    session.headers.update(
        HEADERS
    )

    schedule_calls = 0
    price_calls = 0

    schedule_countries = set()
    price_countries = set()
    rub_countries = set()
    unknown_currency_countries = set()

    errors = Counter()
    empty_response_countries = set()
    no_town_from = []

    # Each country gets its own list of candidate tasks.
    price_tasks = defaultdict(list)

    print()
    print("=== ЭТАП 1: РАСПИСАНИЯ xml=11 ===")

    for country in countries:
        if schedule_calls >= max_schedule:
            print(
                "\nДостигнут лимит xml=11"
            )
            break

        country_id = str(
            country.get("id")
        )

        country_name = str(
            country.get("title_ru")
            or ""
        )

        city_list = departure_cities(
            country,
            cities,
        )

        print()
        print(
            f"СТРАНА: {country_name} "
            f"({country_id}) "
            f"| городов={len(city_list)}"
        )

        if not city_list:
            no_town_from.append(
                country_name
            )

            print(
                "  Нет городов в town_from"
            )

            continue

        found_schedule = False

        for city_id, city_name in city_list[
            :cities_per_country
        ]:
            if schedule_calls >= max_schedule:
                break

            schedule_calls += 1

            print(
                f"  ВЫЛЕТ: {city_name} "
                f"({city_id})"
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
                message = str(exc)

                print(
                    "    ОШИБКА:",
                    message[:220],
                )

                if "ПУСТОЙ ОТВЕТ" in message:
                    empty_response_countries.add(
                        country_name
                    )
                    errors["пустой HTTP 200"] += 1
                else:
                    errors["ошибка xml=11"] += 1

                continue

            print(
                "    Строк расписания:",
                len(entries),
            )

            if not entries:
                errors["нет строк xml=11"] += 1
                continue

            found_schedule = True
            schedule_countries.add(
                country_name
            )

            candidates, dates = find_candidates(
                entries
            )

            print(
                "    Дат:",
                len(dates),
                "| кандидатов:",
                len(candidates),
            )

            if candidates:
                for item in candidates[:3]:
                    price_tasks[country_name].append({
                        **item,
                        "country_id": country_id,
                        "city_id": city_id,
                        "city_name": city_name,
                        "site_cur": str(
                            country.get("site_cur")
                            or ""
                        ),
                    })

            # Stop after finding a schedule.
            break

        if not found_schedule:
            print(
                "  Расписание не найдено "
                "в проверенных городах"
            )

    print()
    print("=== ЭТАП 2: ЦЕНЫ xml=51 ===")

    # Round-robin across countries.
    # One task per country in each round.
    ordered_tasks = []

    max_rounds = max(
        (len(tasks) for tasks in price_tasks.values()),
        default=0,
    )

    for index in range(max_rounds):
        for country_name, tasks in price_tasks.items():
            if index < len(tasks):
                ordered_tasks.append(
                    (country_name, tasks[index])
                )

    print(
        "Стран с кандидатами:",
        len(price_tasks),
    )

    print(
        "Подготовлено проверок цен:",
        len(ordered_tasks),
    )

    total_offers = 0
    total_rub = 0
    total_unknown = 0

    for country_name, task in ordered_tasks:
        if price_calls >= max_prices:
            print(
                "\nДостигнут лимит xml=51"
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
            "| ДАТА:",
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
            )[:110],
        )

        try:
            offers = get_prices(
                session,
                task["country_id"],
                task["city_id"],
                task["program"],
                task["day"],
                task["nights"],
                task["site_cur"],
            )

        except (
            requests.RequestException,
            ValueError,
            TypeError,
        ) as exc:
            print(
                "    ОШИБКА xml=51:",
                str(exc)[:220],
            )

            errors["ошибка xml=51"] += 1
            continue

        if not offers:
            errors["без предложений"] += 1
            continue

        price_countries.add(
            country_name
        )

        rub_count = sum(
            offer["currency"] == "RUB"
            for offer in offers
        )

        unknown_count = sum(
            offer["currency"] is None
            for offer in offers
        )

        if rub_count:
            rub_countries.add(
                country_name
            )

        if unknown_count:
            unknown_currency_countries.add(
                country_name
            )

        total_offers += len(offers)
        total_rub += rub_count
        total_unknown += unknown_count

    print()
    print("=" * 72)
    print("=== ИТОГИ v3 ===")

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
        "Стран с предложениями:",
        len(price_countries),
    )

    print(
        "Всего предложений:",
        total_offers,
    )

    print(
        "Предложений с полем RUR:",
        total_rub,
    )

    print(
        "Предложений с amount "
        "без подтверждённой валюты:",
        total_unknown,
    )

    print()
    print("СТРАНЫ С ПРЕДЛОЖЕНИЯМИ:")
    for name in sorted(price_countries):
        print(" +", name)

    print()
    print("СТРАНЫ С РУБЛЁВЫМИ ЦЕНАМИ:")
    for name in sorted(rub_countries):
        print(" +", name)

    print()
    print(
        "СТРАНЫ С НЕПОДТВЕРЖДЁННОЙ ВАЛЮТОЙ:"
    )
    for name in sorted(
        unknown_currency_countries
    ):
        print(" ?", name)

    print()
    print(
        "Стран с пустым HTTP 200:",
        len(empty_response_countries),
    )

    print(
        "Стран без town_from:",
        len(no_town_from),
    )

    print(
        "Ошибки и пропуски:",
        dict(errors),
    )

    print()
    print(
        "Важно: отсутствие расписания или цены "
        "в тесте не доказывает отсутствие туров."
    )

    print(
        "amount без подтверждённой валюты "
        "нельзя показывать пользователю как RUB."
    )

    print(
        "Ссылки построены по данным BG, "
        "но оформление бронирования не проверено."
    )

    print()
    print("=== КОНЕЦ ===")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
