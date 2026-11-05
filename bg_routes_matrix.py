
import argparse
import calendar
import html
import json
import re
import sys
import time

from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import (
    parse_qs,
    parse_qsl,
    urljoin,
    urlsplit,
)

import requests


BASE = "https://www.bgoperator.ru"
API = BASE + "/site"
ROOT = Path(__file__).resolve().parent
TIMEOUT = 35

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 Chrome/125.0 Safari/537.36"
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
        r"\s+", " ",
        str(value or "").strip().casefold().replace("ё", "е")
    )


def read_catalog(filename):
    path = ROOT / filename
    with path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"{filename}: ожидался список")

    return [x for x in data if isinstance(x, dict)]


def resolve_route(country_name, city_name):
    countries = read_catalog("bg_countries.json")
    cities = read_catalog("bg_departures.json")

    country = next(
        (
            x for x in countries
            if normalize(x.get("title_ru")) == normalize(country_name)
        ),
        None,
    )

    country_id = (
        str(country["id"]) if country
        else COUNTRY_FALLBACK.get(normalize(country_name))
    )

    allowed = set()
    if country:
        allowed = {
            x.strip()
            for x in str(country.get("town_from") or "").split("#")
            if x.strip()
        }

    matches = [
        x for x in cities
        if normalize(x.get("title_ru")) == normalize(city_name)
        and str(x.get("id", "")).startswith("1005")
    ]

    matches.sort(
        key=lambda x: (
            0 if str(x.get("id")) in allowed else 1,
            str(x.get("id")),
        )
    )

    city_id = (
        str(matches[0]["id"]) if matches
        else CITY_FALLBACK.get(normalize(city_name))
    )

    if not country_id:
        raise ValueError(f"Страна не найдена: {country_name}")

    if not city_id:
        raise ValueError(f"Город не найден: {city_name}")

    return country_id, city_id


def bg_request(session, params):
    last_error = None

    for attempt in range(3):
        try:
            response = session.get(
                API,
                params=params,
                timeout=TIMEOUT,
            )
            response.raise_for_status()

            if not response.content.strip():
                raise ValueError("Пустой ответ BG")

            data = response.json()

            if not isinstance(data, dict):
                raise ValueError("BG вернул не объект JSON")

            if data.get("ERROR"):
                raise ValueError(f"BG ERROR: {data['ERROR']}")

            return data

        except (
            requests.RequestException,
            ValueError,
        ) as exc:
            last_error = exc

            if attempt < 2:
                time.sleep(attempt + 1)

    raise RuntimeError(str(last_error))


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
        raise ValueError("xml=11: entries не список")

    return [x for x in entries if isinstance(x, dict)]


def parse_nights(value):
    return {
        int(x)
        for x in re.findall(r"\d+", str(value or ""))
    }


def dates_between(start, end):
    current = start

    while current <= end:
        yield current
        current += timedelta(days=1)


def find_programs(entries, start_date, end_date, nights_min, nights_max):
    programs = {}
    requested_dates = {
        d.strftime("%d.%m.%Y"): d
        for d in dates_between(start_date, end_date)
    }

    for entry in entries:
        day_text = str(entry.get("date") or "")
        program = str(entry.get("id_price") or "")

        if day_text not in requested_dates or not program.isdigit():
            continue

        for nights in sorted(parse_nights(entry.get("duration"))):
            if not nights_min <= nights <= nights_max:
                continue

            key = (program, day_text, nights)

            programs[key] = {
                "program": program,
                "date": requested_dates[day_text],
                "nights": nights,
                "route": str(entry.get("route") or ""),
                "cn": str(entry.get("cn") or ""),
                "description": str(entry.get("descr") or ""),
            }

    return sorted(
        programs.values(),
        key=lambda x: (x["date"], x["nights"], x["program"]),
    )


def birthday_for_age(travel_date, age):
    """
    Условная дата рождения, обеспечивающая указанный
    возраст именно на дату вылета.

    Выбираем предыдущий календарный месяц.
    Для января это декабрь предыдущего года.

    На 20.11.2026, возраст 8:
        20.10.2018

    На 20.01.2027, возраст 8:
        20.12.2018
    """
    if not 0 <= age <= 17:
        raise ValueError(f"Недопустимый возраст ребёнка: {age}")

    month = travel_date.month - 1
    year = travel_date.year

    if month == 0:
        month = 12
        year -= 1

    birth_year = year - age

    # Для января предыдущий месяц относится к прошлому году,
    # поэтому возраст на январскую дату уже на год больше
    # разницы между календарными годами.
    if travel_date.month == 1:
        birth_year = travel_date.year - age - 1

    day = min(
        travel_date.day,
        calendar.monthrange(birth_year, month)[1],
    )

    birthday = date(birth_year, month, day)

    actual_age = travel_date.year - birthday.year - (
        (travel_date.month, travel_date.day)
        < (birthday.month, birthday.day)
    )

    if actual_age != age:
        raise ValueError(
            f"Ошибка вычисления возраста: {actual_age} вместо {age}"
        )

    return birthday


def encode_person(birthday):
    """
    Формат: 0DDMMYYYYS

    S = 0 для используемого нами формата туриста.
    """
    return "0" + birthday.strftime("%d%m%Y") + "0"


def passenger_code(travel_date, adults, child_ages):
    if adults < 1:
        raise ValueError("Нужен хотя бы один взрослый")

    # Проверенный взрослый код соответствует 20.10.1990
    # для теста 20.11.2026. Для других дат используем
    # условную дату рождения взрослого 1990 года.
    adult_birthday = date(
        1990,
        travel_date.month,
        min(
            travel_date.day,
            calendar.monthrange(1990, travel_date.month)[1],
        ),
    )

    # Чтобы сохранить точное совпадение с успешным тестом,
    # используем предыдущий месяц и для взрослых.
    previous_month = travel_date.month - 1
    previous_year = 1990

    if previous_month == 0:
        previous_month = 12
        previous_year = 1989

    adult_birthday = date(
        previous_year,
        previous_month,
        min(
            travel_date.day,
            calendar.monthrange(
                previous_year, previous_month
            )[1],
        ),
    )

    parts = [
        encode_person(adult_birthday)
        for _ in range(adults)
    ]

    for age in child_ages:
        parts.append(
            encode_person(birthday_for_age(travel_date, age))
        )

    return ".".join(parts)


def positive_price(value):
    if isinstance(value, bool):
        return None

    raw = str(value or "").strip()

    if not re.fullmatch(r"\d[\d\s\u00a0\u202f]*", raw):
        return None

    number = int(re.sub(r"\s+", "", raw))
    return number if number > 0 else None


def extract_price(price):
    rub = positive_price(price.get("RUR"))

    if rub is not None:
        return rub, "RUR"

    amount = positive_price(price.get("amount"))

    if amount is not None:
        return amount, "amount"

    return None, None


def clean_text(value):
    return re.sub(
        r"\s+",
        " ",
        html.unescape(
            re.sub(r"<[^>]+>", " ", str(value or ""))
        ),
    ).strip()


def create_booking_url(section, entry, price, program, persons):
    href0 = str(section.get("href0") or "")
    href1 = str(entry.get("href1") or "")
    href2 = str(price.get("href2") or "")

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

    if parsed.hostname not in ("www.bgoperator.ru", "bgoperator.ru"):
        return None

    if parsed.path != "/zaya":
        return None

    query = parse_qs(parsed.query)

    if query.get("templ", [""])[0] != program:
        return None

    if query.get("p", [""])[0] != persons:
        return None

    return url


def build_price_params(
    country_id, city_id, program, travel_date, nights, persons
):
    params = [
        ("xml", "51"),
        ("action", "price"),
        ("id_price", program),
        ("flt2", city_id),
    ]

    for meal in ("BB", "HB", "FB", "AI", "AO"):
        params.append(("f8", meal))

    params.extend([
        ("entr", "-100"),
        ("data", travel_date.strftime("%d.%m.%Y")),
        ("f7", str(nights)),
        ("flt", country_id),
        ("p", persons),
    ])

    return params


def next_page_params(next_page, current_params):
    """
    Поддержка явных параметров следующей страницы.

    Не придумываем параметр page, если BG его не сообщил.
    """
    if not next_page:
        return None

    if isinstance(next_page, dict):
        if "url" in next_page:
            return next_page_params(next_page["url"], current_params)

        if "params" in next_page:
            extra = next_page["params"]

            if isinstance(extra, dict):
                result = list(current_params)

                for key, value in extra.items():
                    result = [
                        (k, v) for k, v in result if k != str(key)
                    ]
                    result.append((str(key), str(value)))

                return result

        return None

    if not isinstance(next_page, str):
        return None

    value = next_page.strip()

    if not value:
        return None

    if value.startswith(("http://", "https://", "?", "&")):
        parsed = urlsplit(
            urljoin(API, value.lstrip("&"))
        )

        if parsed.hostname not in (
            "www.bgoperator.ru", "bgoperator.ru"
        ):
            return None

        if parsed.path != "/site":
            return None

        extra = parse_qsl(parsed.query, keep_blank_values=True)

        if not extra:
            return None

        keys = {k for k, _ in extra}

        if {"xml", "action", "id_price"}.issubset(keys):
            return extra

        result = [(k, v) for k, v in current_params if k not in keys]
        result.extend(extra)

        return result

    return None


def hotel_names_from_filters(data):
    filters = data.get("FILTER") or {}
    hotels = {}

    if not isinstance(filters, dict):
        return hotels

    rows = filters.get("HOTELS") or []

    if not isinstance(rows, list):
        return hotels

    for hotel in rows:
        if isinstance(hotel, dict):
            hotels[str(hotel.get("ID"))] = str(
                hotel.get("TITLE") or ""
            )

    return hotels


def parse_offers(
    data, program_info, country_name, city_name,
    adults, child_ages, persons
):
    section = data.get("PRICE_SECTION") or {}

    if not isinstance(section, dict):
        raise ValueError("xml=51: PRICE_SECTION не объект")

    entries = section.get("entries") or []

    if not isinstance(entries, list):
        raise ValueError("xml=51: entries не список")

    hotels = hotel_names_from_filters(data)
    offers = {}

    travel_date = program_info["date"]
    day = travel_date.strftime("%d.%m.%Y")
    nights = program_info["nights"]
    program = program_info["program"]

    route = clean_text(program_info["route"])
    resort = clean_text(program_info["cn"])

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        if str(entry.get("tour_date")) != day:
            continue

        if str(entry.get("duration")) != str(nights):
            continue

        hotel_id = str(entry.get("id_hotel") or "")
        prices = entry.get("prices") or []

        if not isinstance(prices, list):
            continue

        for price in prices:
            if not isinstance(price, dict):
                continue

            amount, price_field = extract_price(price)

            if amount is None:
                continue

            url = create_booking_url(
                section, entry, price, program, persons
            )

            if not url:
                continue

            hotel = (
                hotels.get(hotel_id)
                or clean_text(entry.get("hotel"))
                or clean_text(entry.get("hotel_name"))
            )

            meal = (
                clean_text(price.get("meal"))
                or clean_text(entry.get("meal"))
                or clean_text(entry.get("f8"))
            )

            offers[url] = {
                "operator": "Библио-Глобус",
                "country": country_name,
                "departure_city": city_name,
                "resort": resort,
                "hotel": hotel,
                "hotel_id": hotel_id,
                "meal": meal,
                "date": travel_date.isoformat(),
                "nights": nights,
                "adults": adults,
                "children": len(child_ages),
                "child_ages": list(child_ages),
                "price_rub": amount,
                "price_field": price_field,
                "program": program,
                "route": route,
                "source": url,
            }

    return {
        "offers": list(offers.values()),
        "entries": len(entries),
        "next_page": (
            section.get("next_page")
            or data.get("next_page")
        ),
    }


def search_bg(
    country_name,
    city_name,
    start_date,
    end_date,
    nights_min,
    nights_max,
    adults,
    child_ages,
):
    country_id, city_id = resolve_route(
        country_name, city_name
    )

    session = requests.Session()
    session.headers.update(HEADERS)

    schedule = schedule_request(
        session, country_id, city_id
    )

    programs = find_programs(
        schedule,
        start_date,
        end_date,
        nights_min,
        nights_max,
    )

    print("Строк расписания:", len(schedule))
    print("Подходящих программ:", len(programs))

    all_offers = {}
    errors = []
    incomplete_pages = []
    requests_count = 0
    total_entries = 0

    for index, program_info in enumerate(programs, 1):
        travel_date = program_info["date"]
        nights = program_info["nights"]
        program = program_info["program"]

        persons = passenger_code(
            travel_date, adults, child_ages
        )

        params = build_price_params(
            country_id,
            city_id,
            program,
            travel_date,
            nights,
            persons,
        )

        seen_pages = set()
        page_number = 0

        while params is not None:
            page_key = tuple(params)

            if page_key in seen_pages:
                incomplete_pages.append({
                    "program": program,
                    "reason": "Повтор страницы",
                })
                break

            seen_pages.add(page_key)
            page_number += 1
            requests_count += 1

            try:
                data = bg_request(session, params)

                result = parse_offers(
                    data,
                    program_info,
                    country_name,
                    city_name,
                    adults,
                    child_ages,
                    persons,
                )

            except Exception as exc:
                errors.append({
                    "program": program,
                    "date": travel_date.isoformat(),
                    "nights": nights,
                    "page": page_number,
                    "error": str(exc),
                })
                print("ОШИБКА:", program, str(exc)[:150])
                break

            total_entries += result["entries"]

            for offer in result["offers"]:
                all_offers.setdefault(offer["source"], offer)

            print(
                f"[{index}/{len(programs)}] "
                f"{travel_date} | {nights} ночей | "
                f"программа {program} | "
                f"страница {page_number} | "
                f"предложений {len(result['offers'])}"
            )

            next_page = result["next_page"]

            if not next_page:
                break

            next_params = next_page_params(
                next_page, params
            )

            if next_params is None:
                incomplete_pages.append({
                    "program": program,
                    "date": travel_date.isoformat(),
                    "nights": nights,
                    "next_page": str(next_page)[:300],
                })
                print(
                    "ВНИМАНИЕ: неизвестный формат next_page:",
                    str(next_page)[:150],
                )
                break

            params = next_params

    offers = sorted(
        all_offers.values(),
        key=lambda x: x["price_rub"],
    )

    complete = not errors and not incomplete_pages

    return {
        "status": "ok" if complete else "incomplete",
        "complete": complete,
        "country": country_name,
        "departure_city": city_name,
        "date_from": start_date.isoformat(),
        "date_to": end_date.isoformat(),
        "nights_min": nights_min,
        "nights_max": nights_max,
        "adults": adults,
        "child_ages": list(child_ages),
        "programs_found": len(programs),
        "requests_count": requests_count,
        "entries_count": total_entries,
        "offers": offers,
        "errors": errors,
        "incomplete_pages": incomplete_pages,
    }


def print_result(result):
    print()
    print("=" * 65)
    print("РЕЗУЛЬТАТ ПОИСКА BG")
    print("=" * 65)

    print("Статус:", result["status"])
    print("Программ:", result["programs_found"])
    print("Запросов цен:", result["requests_count"])
    print("Строк BG:", result["entries_count"])
    print("Предложений:", len(result["offers"]))
    print("Ошибок:", len(result["errors"]))
    print(
        "Необработанных страниц:",
        len(result["incomplete_pages"]),
    )

    print()
    print("10 САМЫХ ДЕШЁВЫХ ПРЕДЛОЖЕНИЙ:")

    for index, offer in enumerate(result["offers"][:10], 1):
        print()
        print(f"{index}. {offer['hotel'] or '[отель]'}")
        print("Курорт:", offer["resort"])
        print("Питание:", offer["meal"] or "не указано")
        print("Дата:", offer["date"])
        print("Ночей:", offer["nights"])
        print(
            "Цена:",
            f"{offer['price_rub']:,}".replace(",", " "),
            "руб.",
        )
        print("Ссылка:", offer["source"])

    if result["errors"]:
        print()
        print("ОШИБКИ:")
        for item in result["errors"]:
            print(json.dumps(item, ensure_ascii=False))

    if result["incomplete_pages"]:
        print()
        print("НЕОБРАБОТАННЫЕ СТРАНИЦЫ:")
        for item in result["incomplete_pages"]:
            print(json.dumps(item, ensure_ascii=False))

    print()
    print(
        "Цены получены из BG. "
        "Бронирование на сайте не проверялось."
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--country", default="Египет")
    parser.add_argument("--city", default="Казань")
    parser.add_argument("--date", default="2026-11-20")
    parser.add_argument("--date-end", default=None)
    parser.add_argument("--nights", type=int, default=5)
    parser.add_argument("--nights-max", type=int, default=None)
    parser.add_argument("--adults", type=int, default=2)
    parser.add_argument(
        "--children",
        type=int,
        nargs="*",
        default=[8],
    )

    args = parser.parse_args()

    start_date = date.fromisoformat(args.date)
    end_date = (
        date.fromisoformat(args.date_end)
        if args.date_end else start_date
    )

    nights_max = (
        args.nights_max
        if args.nights_max is not None
        else args.nights
    )

    if end_date < start_date:
        parser.error("Конечная дата раньше начальной")

    if args.nights < 1 or nights_max < args.nights:
        parser.error("Неверный диапазон ночей")

    if args.adults < 1:
        parser.error("Количество взрослых должно быть >= 1")

    if any(age < 0 or age > 17 for age in args.children):
        parser.error("Возраст детей должен быть от 0 до 17")

    print("=== BG FULL SEARCH ===")
    print("Запуск:", datetime.now().isoformat(timespec="seconds"))
    print("Страна:", args.country)
    print("Город:", args.city)
    print("Даты:", start_date, "—", end_date)
    print("Ночи:", args.nights, "—", nights_max)
    print("Взрослые:", args.adults)
    print("Дети:", args.children)

    print(
        "Код пассажиров на начальную дату:",
        passenger_code(start_date, args.adults, args.children),
    )

    result = search_bg(
        country_name=args.country,
        city_name=args.city,
        start_date=start_date,
        end_date=end_date,
        nights_min=args.nights,
        nights_max=nights_max,
        adults=args.adults,
        child_ages=args.children,
    )

    print_result(result)

    if result["status"] != "ok":
        sys.exit(1)


if __name__ == "__main__":
    main()
