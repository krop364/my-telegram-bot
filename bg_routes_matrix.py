
"""
BG REAL SEARCH TEST
===================

Проверка поиска Библио-Глобуса через GitHub Actions.

Файлы:
    bg_routes_matrix.py
    bg_countries.json
    bg_departures.json

Workflow менять не нужно:
    python bg_routes_matrix.py

По умолчанию проверяются:
    Египет, Казань, 20.11.2026, 7 ночей
    2 взрослых
    2 взрослых + ребёнок 8 лет

Можно передать параметры через командную строку:

python bg_routes_matrix.py \
    --country "Таиланд" \
    --city "Екатеринбург" \
    --date 2026-11-20 \
    --nights 7 \
    --adults 2 \
    --children 8

Для нескольких возрастов:
    --children 5 8

Важно:
- Все страны из каталога доступны для выбора.
- Нет ограничения на число программ.
- Нет ограничения на число найденных предложений.
- Нет ограничения на количество проверяемых стран
  внутри каталога.
- Составы туристов, кроме ранее проверенных,
  считаются экспериментальными.
- Неизвестная пагинация не скрывается.
"""

import argparse
import json
import re
import sys
import time

from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import requests


BASE = "https://www.bgoperator.ru"
API = BASE + "/site"
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
    "Referer": BASE + "/",
}

COUNTRY_FALLBACK = {
    "египет": "100410000047",
    "турция": "100411293179",
    "таиланд": "100410000051",
}

CITY_FALLBACK = {
    "казань": "100510345650",
    "москва": "100510000863",
    "екатеринбург": "100510000892",
}


def normalize(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip().casefold().replace("ё", "е"),
    )


def read_catalog(filename):
    path = ROOT / filename

    if not path.exists():
        raise RuntimeError(
            f"Не найден файл {filename}"
        )

    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise RuntimeError(
            f"{filename}: ожидался JSON-список"
        )

    return [
        row for row in data
        if isinstance(row, dict)
    ]


def resolve_route(country_name, city_name):
    countries = read_catalog("bg_countries.json")
    cities = read_catalog("bg_departures.json")

    country = next(
        (
            row for row in countries
            if normalize(row.get("title_ru"))
            == normalize(country_name)
        ),
        None,
    )

    city_matches = [
        row for row in cities
        if normalize(row.get("title_ru"))
        == normalize(city_name)
        and str(row.get("id", "")).startswith("1005")
    ]

    country_id = (
        str(country["id"])
        if country
        else COUNTRY_FALLBACK.get(normalize(country_name))
    )

    # Prefer a departure city explicitly listed by the country.
    allowed = set()

    if country:
        allowed = {
            item.strip()
            for item in str(
                country.get("town_from") or ""
            ).split("#")
            if item.strip()
        }

    city_matches.sort(
        key=lambda row: (
            0 if str(row.get("id")) in allowed else 1,
            str(row.get("id")),
        )
    )

    city_id = (
        str(city_matches[0]["id"])
        if city_matches
        else CITY_FALLBACK.get(normalize(city_name))
    )

    if not country_id:
        raise RuntimeError(
            f"Страна не найдена: {country_name}"
        )

    if not city_id:
        raise RuntimeError(
            f"Город вылета не найден: {city_name}"
        )

    if allowed and city_id not in allowed:
        print(
            "ВНИМАНИЕ: город отсутствует в town_from."
        )
        print(
            "Это не доказательство отсутствия туров."
        )

    return country_id, city_id


def bg_request(session, params):
    response = session.get(
        API,
        params=params,
        timeout=TIMEOUT,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"HTTP {response.status_code}; "
            f"body={response.text[:150]!r}"
        )

    if not response.content.strip():
        raise RuntimeError(
            "BG вернул пустой HTTP 200"
        )

    try:
        result = response.json()
    except ValueError:
        raise RuntimeError(
            "BG вернул не JSON: "
            + response.text[:150]
        )

    if not isinstance(result, dict):
        raise RuntimeError(
            "BG вернул неожиданный JSON"
        )

    if result.get("ERROR"):
        raise RuntimeError(
            "BG ERROR: "
            + str(result["ERROR"])[:200]
        )

    return result


def schedule_request(session, country_id, city_id):
    data = bg_request(
        session,
        [
            ("action", "files"),
            ("flt", country_id),
            ("flt2", city_id),
            ("xml", "11"),
        ],
    )

    entries = data.get("entries") or []

    if not isinstance(entries, list):
        raise RuntimeError(
            "xml=11: entries не список"
        )

    return [
        item for item in entries
        if isinstance(item, dict)
    ]


def parse_nights(value):
    return {
        int(number)
        for number in re.findall(
            r"\d+",
            str(value or ""),
        )
    }


def find_programs(entries, requested_date, nights):
    """
    Collect all matching programs.

    No first-three-programs restriction.
    """

    day = requested_date.strftime("%d.%m.%Y")
    programs = {}

    for entry in entries:
        entry_date = str(entry.get("date") or "")
        program = str(entry.get("id_price") or "")

        if entry_date != day:
            continue

        if not program.isdigit():
            continue

        durations = parse_nights(
            entry.get("duration")
        )

        if nights not in durations:
            continue

        key = (program, day, nights)

        if key not in programs:
            programs[key] = {
                "program": program,
                "date": day,
                "nights": nights,
                "route": str(
                    entry.get("route") or ""
                ),
            }

    return list(programs.values())


def passenger_code(day, adults, child_ages):
    """
    Construct a candidate BG passenger code.

    Verified examples:
      20.11.2026, 2 adults:
        0201019900.0201019900

      20.11.2026, 2 adults + child aged 8:
        0201019900.0201019900.0201020180

    Other dates/compositions are experimental.
    """

    prefix = f"{day.day:03d}"

    adult_part = prefix + "1019900"

    parts = [
        adult_part
        for _ in range(adults)
    ]

    for age in child_ages:
        if day == date(2026, 11, 20) and age == 8:
            child_part = "0201020180"
        else:
            raise ValueError(
                f"Код ребёнка {age} лет на дату "
                f"{day.strftime('%d.%m.%Y')} пока не подтверждён"
            )

        parts.append(child_part)

    verified = (
        day == date(2026, 11, 20)
        and adults == 2
        and child_ages in ([], [8])
    )

    return ".".join(parts), verified


def positive_price(value):
    if isinstance(value, bool):
        return None

    raw = str(value or "").strip()

    if not re.fullmatch(
        r"\d[\d\s\u00a0\u202f]*",
        raw,
    ):
        return None

    number = int(
        re.sub(r"\s+", "", raw)
    )

    return number if number > 0 else None


def extract_price(price):
    rub = positive_price(
        price.get("RUR")
    )

    if rub is not None:
        return rub, "RUR"

    amount = positive_price(
        price.get("amount")
    )

    if amount is not None:
        return amount, "amount"

    return None, None


def create_booking_url(
    section,
    entry,
    price,
    program,
    persons,
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

    if not href0 or not href1:
        return None

    url = (
        urljoin(BASE, href0)
        + href1
        + "&p="
        + persons
        + href2
    )

    parsed = urlsplit(url)

    if parsed.scheme != "https":
        return None

    if parsed.hostname not in (
        "www.bgoperator.ru",
        "bgoperator.ru",
    ):
        return None

    if parsed.path != "/zaya":
        return None

    query = parse_qs(
        parsed.query
    )

    if query.get("templ", [""])[0] != program:
        return None

    if query.get("p", [""])[0] != persons:
        return None

    # Do not compare dt/kol with the package date/nights.
    # Combined tours may contain segment-specific values.
    return url


def price_request(
    session,
    country_id,
    city_id,
    program,
    requested_date,
    nights,
    adults,
    child_ages,
):
    day = requested_date.strftime("%d.%m.%Y")

    persons, code_verified = passenger_code(
        requested_date,
        adults,
        child_ages,
    )

    params = [
        ("xml", "51"),
        ("action", "price"),
        ("id_price", program),
        ("flt2", city_id),
    ]

    for meal in (
        "BB",
        "HB",
        "FB",
        "AI",
        "AO",
    ):
        params.append(
            ("f8", meal)
        )

    params.extend([
        ("entr", "-100"),
        ("data", day),
        ("f7", str(nights)),
        ("flt", country_id),
        ("p", persons),
    ])

    data = bg_request(
        session,
        params,
    )

    section = (
        data.get("PRICE_SECTION")
        or {}
    )

    if not isinstance(section, dict):
        raise RuntimeError(
            "xml=51: PRICE_SECTION не объект"
        )

    entries = (
        section.get("entries")
        or []
    )

    if not isinstance(entries, list):
        raise RuntimeError(
            "xml=51: entries не список"
        )

    filters = data.get("FILTER") or {}
    hotels = {}

    if isinstance(filters, dict):
        hotel_rows = (
            filters.get("HOTELS")
            or []
        )

        if isinstance(hotel_rows, list):
            for hotel in hotel_rows:
                if isinstance(hotel, dict):
                    hotels[
                        str(hotel.get("ID"))
                    ] = str(
                        hotel.get("TITLE") or ""
                    )

    offers = {}
    stats = Counter()

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        if str(entry.get("tour_date")) != day:
            stats["другая дата"] += 1
            continue

        if str(entry.get("duration")) != str(nights):
            stats["другая длительность"] += 1
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

            amount, price_field = extract_price(
                price
            )

            if amount is None:
                stats["без цены"] += 1
                continue

            url = create_booking_url(
                section,
                entry,
                price,
                program,
                persons,
            )

            if not url:
                stats["некорректная ссылка"] += 1
                continue

            hotel_id = str(
                entry.get("id_hotel")
                or ""
            )

            item = {
                "operator": "Библио-Глобус",
                "hotel": hotels.get(
                    hotel_id,
                    "",
                ),
                "hotel_id": hotel_id,
                "date": requested_date.isoformat(),
                "nights": nights,
                "adults": adults,
                "children": len(child_ages),
                "child_ages": list(child_ages),
                "price_rub": amount,
                "price_field": price_field,
                "source": url,
                "program": program,
                "passenger_code_verified": code_verified,
            }

            # Preserve different offers and booking links.
            if url not in offers:
                offers[url] = item

    pagination = section.get("next_page")

    return {
        "offers": list(offers.values()),
        "entry_count": len(entries),
        "stats": dict(stats),
        "next_page": pagination,
        "passenger_code": persons,
        "passenger_code_verified": code_verified,
    }


def search(
    session,
    country_name,
    city_name,
    requested_date,
    nights,
    adults,
    child_ages,
    max_requests=0,
):
    country_id, city_id = resolve_route(
        country_name,
        city_name,
    )

    print()
    print("=" * 70)
    print("ПОИСК BG")
    print("=" * 70)

    print("Страна:", country_name, country_id)
    print("Город вылета:", city_name, city_id)
    print("Дата:", requested_date.isoformat())
    print("Ночей:", nights)
    print("Взрослых:", adults)
    print("Дети, возраст:", child_ages)

    persons, verified = passenger_code(
        requested_date,
        adults,
        child_ages,
    )

    print("Код пассажиров:", persons)
    print(
        "Формат кода:",
        "ранее проверен"
        if verified
        else "ЭКСПЕРИМЕНТАЛЬНЫЙ",
    )

    print()
    print("ШАГ 1: xml=11 — расписание")

    try:
        schedule = schedule_request(
            session,
            country_id,
            city_id,
        )
    except (requests.RequestException, RuntimeError) as exc:
        print("ОШИБКА расписания:", exc)
        return {
            "status": "schedule_error",
            "offers": [],
            "complete": False,
        }

    print(
        "Строк расписания:",
        len(schedule),
    )
    print("ПРИМЕРЫ СТРОК xml=11:")
    for row in schedule[:5]:
        print(json.dumps(row, ensure_ascii=False)[:1200])
    
    print("ДАТЫ В РАСПИСАНИИ:")
    dates = sorted({
        str(row.get("date") or "")
        for row in schedule
        if row.get("date")
    })
    print(dates[:40])
    
    print("СТРОК НА 20.11.2026:")
    target = [
        row for row in schedule
        if str(row.get("date") or "") == "20.11.2026"
    ]
    print(len(target))
    for row in target[:5]:
        print(json.dumps(row, ensure_ascii=False)[:1200])
    programs = find_programs(
        schedule,
        requested_date,
        nights,
    )

    print(
        "Подходящих программ:",
        len(programs),
    )

    if not programs:
        print(
            "Для этой даты и длительности "
            "программы не найдены."
        )

        return {
            "status": "no_programs",
            "offers": [],
            "complete": True,
        }

    print()
    print("ШАГ 2: xml=51 — предложения")

    all_offers = {}
    errors = []
    pagination_pending = 0
    requests_done = 0
    total_entries = 0

    for index, program in enumerate(programs, 1):
        if max_requests and requests_done >= max_requests:
            print(
                "Достигнут пользовательский лимит запросов."
            )
            break

        requests_done += 1

        print()
        print(
            f"Программа {index}/{len(programs)}:",
            program["program"],
        )

        try:
            result = price_request(
                session,
                country_id,
                city_id,
                program["program"],
                requested_date,
                nights,
                adults,
                child_ages,
            )
        except (requests.RequestException, RuntimeError) as exc:
            print(
                "  ОШИБКА:",
                str(exc)[:200],
            )

            errors.append({
                "program": program["program"],
                "error": str(exc)[:200],
            })

            continue

        total_entries += result["entry_count"]

        print(
            "  Строк BG:",
            result["entry_count"],
        )

        print(
            "  Предложений:",
            len(result["offers"]),
        )

        if result["stats"]:
            print(
                "  Отбор:",
                result["stats"],
            )

        if result["next_page"]:
            pagination_pending += 1

            print(
                "  ВНИМАНИЕ: BG указал next_page:",
                str(result["next_page"])[:100],
            )

        for offer in result["offers"]:
            all_offers.setdefault(
                offer["source"],
                offer,
            )

    offers = sorted(
        all_offers.values(),
        key=lambda item: item["price_rub"],
    )

    incomplete_limit = (
        bool(max_requests)
        and requests_done < len(programs)
    )

    complete = (
        not errors
        and pagination_pending == 0
        and not incomplete_limit
    )

    print()
    print("=" * 70)
    print("ИТОГИ ПОИСКА")
    print("=" * 70)

    print(
        "Программ в расписании:",
        len(programs),
    )

    print(
        "Программ проверено:",
        requests_done,
    )

    print(
        "Строк предложений BG:",
        total_entries,
    )

    print(
        "Уникальных предложений:",
        len(offers),
    )

    print(
        "Ошибок программ:",
        len(errors),
    )

    print(
        "Программ с next_page:",
        pagination_pending,
    )

    print(
        "Все страницы и программы обработаны:",
        "ДА" if complete else "НЕТ",
    )

    print(
        "Код пассажиров подтверждён:",
        "ДА" if verified else "НЕТ",
    )

    print()
    print("ПЕРВЫЕ 10 ПРЕДЛОЖЕНИЙ ПО ЦЕНЕ:")

    for index, offer in enumerate(
        offers[:10],
        1,
    ):
        print()
        print(
            f"{index}.",
            offer["hotel"] or "[отель без названия]",
        )

        print(
            "   Цена:",
            f"{offer['price_rub']:,}".replace(",", " "),
            "руб.",
        )

        print(
            "   Дата:",
            offer["date"],
            "| ночей:",
            offer["nights"],
        )

        print(
            "   Программа:",
            offer["program"],
        )

        print(
            "   Поле цены:",
            offer["price_field"],
        )

        print(
            "   Ссылка:",
            offer["source"],
        )

    if errors:
        print()
        print("ОШИБКИ:")

        for error in errors[:20]:
            print(
                " !",
                error["program"],
                error["error"],
            )

    print()
    print("ВАЖНО:")

    if not verified:
        print(
            "Состав туристов экспериментальный. "
            "Найденные предложения пока нельзя "
            "считать подтверждёнными для этого состава."
        )

    if pagination_pending:
        print(
            "BG сообщил о дополнительных страницах. "
            "Поиск пока неполный."
        )

    if errors:
        print(
            "Некоторые программы не удалось проверить. "
            "Поиск пока неполный."
        )

    print(
        "Цены получены из BG; фактическое "
        "бронирование не проверялось."
    )

    return {
        "status": "ok" if complete else "incomplete",
        "offers": offers,
        "complete": complete,
        "passenger_code_verified": verified,
        "programs_found": len(programs),
        "programs_checked": requests_done,
        "pagination_pending": pagination_pending,
        "errors": errors,
    }


def run_case(
    session,
    country,
    city,
    day,
    nights,
    adults,
    children,
    max_requests,
):
    requested_date = date.fromisoformat(day)

    return search(
        session=session,
        country_name=country,
        city_name=city,
        requested_date=requested_date,
        nights=nights,
        adults=adults,
        child_ages=children,
        max_requests=max_requests,
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--country",
        default=None,
    )

    parser.add_argument(
        "--city",
        default=None,
    )

    parser.add_argument(
        "--date",
        default="2026-11-20",
    )

    parser.add_argument(
        "--nights",
        type=int,
        default=7,
    )

    parser.add_argument(
        "--adults",
        type=int,
        default=2,
    )

    parser.add_argument(
        "--children",
        type=int,
        nargs="*",
        default=[],
    )

    parser.add_argument(
        "--max-requests",
        type=int,
        default=0,
        help="0 means no artificial request cap",
    )

    args = parser.parse_args()

    if args.adults < 1 or args.nights < 1:
        parser.error(
            "Adults and nights must be positive"
        )

    if any(
        age < 0 or age > 17
        for age in args.children
    ):
        parser.error(
            "Child ages must be between 0 and 17"
        )

    print(
        "=== BG REAL SEARCH TEST ==="
    )

    print(
        "Время запуска:",
        datetime.now().isoformat(
            timespec="seconds"
        ),
    )

    print(
        "Лимит программ:",
        "НЕТ"
        if args.max_requests == 0
        else args.max_requests,
    )

    session = requests.Session()
    session.headers.update(HEADERS)

    if args.country or args.city:
        if not args.country or not args.city:
            parser.error(
                "--country and --city must be used together"
            )

        result = run_case(
            session,
            args.country,
            args.city,
            args.date,
            args.nights,
            args.adults,
            args.children,
            args.max_requests,
        )

        print()
        print(
            "РЕЗУЛЬТАТ:",
            result["status"],
        )

        if result["status"] == "schedule_error":
            sys.exit(1)

        return

    # Default workflow tests.
    # Both use the same verified date.
    cases = [
        {
            "name": "2 взрослых",
            "country": "Египет",
            "city": "Казань",
            "day": "2026-11-20",
            "nights": 5,
            "adults": 2,
            "children": [],
        },
        {
            "name": "2 взрослых + ребёнок 8 лет",
            "country": "Египет",
            "city": "Казань",
            "day": "2026-11-20",
            "nights": 5,
            "adults": 2,
            "children": [8],
        },
    ]

    results = []

    for case in cases:
        print()
        print("#" * 70)
        print("ТЕСТ:", case["name"])
        print("#" * 70)

        result = run_case(
            session=session,
            country=case["country"],
            city=case["city"],
            day=case["day"],
            nights=case["nights"],
            adults=case["adults"],
            children=case["children"],
            max_requests=args.max_requests,
        )

        results.append(
            (case["name"], result)
        )

    print()
    print("=" * 70)
    print("ОБЩИЙ РЕЗУЛЬТАТ")
    print("=" * 70)

    for name, result in results:
        print()
        print("Тест:", name)
        print("Статус:", result["status"])
        print(
            "Предложений:",
            len(result["offers"]),
        )
        print(
            "Программ:",
            result.get("programs_found", 0),
        )
        print(
            "Проверено:",
            result.get("programs_checked", 0),
        )
        print(
            "Код пассажиров подтверждён:",
            result.get(
                "passenger_code_verified",
                False,
            ),
        )

    print()
    print("=== КОНЕЦ ===")

    if any(
        result["status"] == "schedule_error"
        for _, result in results
    ):
        sys.exit(1)


if __name__ == "__main__":
    main()
