
import json
import re
from pathlib import Path
from collections import Counter
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent
BG_URL = "https://www.bgoperator.ru/site"


def read_json(filename):
    return json.loads(
        (BASE / filename).read_text(encoding="utf-8-sig")
    )


def load_departures():
    # Здесь города берём из обычного JSON.
    # BG_FLTX для этого этапа не требуется.
    cities = read_json("bg_departures.json")

    result = {}

    for city in cities:
        name = city.get("title_ru", "").strip()
        city_id = city.get("id")

        if name and city_id:
            result[name.casefold()] = str(city_id)

    return result


COUNTRIES = read_json("bg_countries.json")
DEPARTURES = load_departures()


def resolve_route(city, destination):
    country = next(
        (
            item for item in COUNTRIES
            if item.get("title_ru", "").strip().casefold()
            == destination.strip().casefold()
        ),
        None,
    )

    if not country:
        raise ValueError(
            f"Страна не найдена: {destination}"
        )

    city_id = DEPARTURES.get(city.strip().casefold())

    if not city_id:
        raise ValueError(
            f"Город вылета не найден: {city}"
        )

    allowed = set(filter(
        None,
        country.get("town_from", "").split("#"),
    ))

    if city_id not in allowed:
        raise ValueError(
            f"Направление {city} → {destination} "
            "не найдено в справочнике"
        )

    return str(country["id"]), city_id


def parse_offers(page):
    soup = BeautifulSoup(page, "html.parser")

    offers = []
    hotel = ""
    resort = ""
    departure_date = ""

    for tr in soup.select("tr"):
        if "b-pr_t_hl" in tr.get("class", []):
            hotel = tr.select_one(".c_hl .name a")
            resort_el = tr.select_one(".c_hl .name span")
            date_el = tr.select_one(".c_de b")

            hotel = (
                hotel.get_text(" ", strip=True)
                if hotel else ""
            )
            resort = (
                resort_el.get_text(" ", strip=True)
                if resort_el else ""
            )
            departure_date = (
                date_el.get_text(" ", strip=True)
                if date_el else ""
            )
            continue

        nights_el = tr.select_one("td.c_dn")
        price_el = tr.select_one("td.c_pe b.r")
        room_el = tr.select_one("td.c_ns")

        if not (
            hotel and nights_el
            and price_el and room_el
        ):
            continue

        try:
            nights = int(
                nights_el.get_text(" ", strip=True)
            )
            price = int(re.sub(
                r"\D", "",
                price_el.get_text(" ", strip=True),
            ))
        except ValueError:
            continue

        services = tr.select("td.c_cn li")

        flights = [
            el for el in services
            if "i_ft" in el.get("class", [])
        ]

        accommodation = [
            el for el in services
            if "i_an" in el.get("class", [])
        ]

        if len(flights) < 2 or not accommodation:
            continue

        link = tr.select_one("td.c_pe a[href]")

        offers.append({
            "hotel": hotel,
            "resort": resort,
            "date": departure_date,
            "nights": nights,
            "price_rub": price,
            "airline": (
                tr.select_one("td.c_ar")
                .get_text(" ", strip=True)
                if tr.select_one("td.c_ar") else ""
            ),
            "room": room_el.get_text(" ", strip=True),
            "url": urljoin(
                BG_URL,
                link["href"],
            ) if link else None,
        })

    return offers


def search_bg_tours(
    city,
    destination,
    date,
    nights,
    adults=2,
):
    if adults != 2:
        raise ValueError(
            "Пока проверяем только 2 взрослых"
        )

    country_id, city_id = resolve_route(
        city, destination
    )

    params = {
        "action": "price",
        "tid": "211",
        "flt": country_id,
        "flt2": city_id,
        "bfr": "1",
        "data": date,
        "d2": date,
        "f7": str(nights),
        "ho": "0",
        "ins": "15-40000-USD",
    }

    response = requests.get(
        BG_URL,
        params=params,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "ru-RU,ru;q=0.9",
        },
        timeout=60,
    )
    response.raise_for_status()

    offers = parse_offers(response.text)

    # Не показываем туры с другой датой.
    offers = [
        offer for offer in offers
        if offer["date"] == date
    ]

    exact = [
        offer for offer in offers
        if offer["nights"] == nights
    ]

    exact.sort(key=lambda x: x["price_rub"])

    return {
        "country_id": country_id,
        "city_id": city_id,
        "total": len(offers),
        "nights_found": dict(Counter(
            offer["nights"] for offer in offers
        )),
        "exact": exact,
    }


def main():
    cases = [
        ("Казань", "Египет", "15.11.2026", 8),
        ("Москва", "Турция", "20.11.2026", 7),
        ("Екатеринбург", "Таиланд", "25.11.2026", 9),
    ]

    print("=== BG UNIVERSAL SEARCH TEST ===")

    for city, country, date, nights in cases:
        print(
            f"\n=== {city} → {country} | "
            f"{date} | {nights} ночей ==="
        )

        try:
            result = search_bg_tours(
                city, country, date, nights
            )

            print("flt:", result["country_id"])
            print("flt2:", result["city_id"])
            print("Всего предложений:", result["total"])
            print("Ночи:", result["nights_found"])
            print(
                "Точных совпадений:",
                len(result["exact"]),
            )

            for offer in result["exact"][:3]:
                print(
                    offer["hotel"],
                    "|",
                    offer["nights"],
                    "ночей |",
                    offer["price_rub"],
                    "₽",
                )
                print("Ссылка:", offer["url"])

            if not result["exact"]:
                print(
                    "Точных предложений не найдено. "
                    "Это не ошибка программы."
                )

        except Exception as exc:
            print(
                "ERROR:",
                type(exc).__name__,
                str(exc)[:300],
            )

    print("\n=== ТЕСТ ЗАВЕРШЁН ===")


if __name__ == "__main__":
    main()
