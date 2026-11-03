
def search_bg_tours(
    city,
    destination,
    date,
    nights,
    adults=2,
    children_ages=None,
    end_date=None,
    id_price=None,
    passenger_code=None,
):
    country_id, city_id = resolve_route(
        city, destination
    )

    if children_ages is None:
        children_ages = []

    if not passenger_code:
        if adults != 2 or children_ages:
            raise ValueError(
                "Для этого состава туристов "
                "пока нужен код p с сайта BG"
            )
        day = date[:2]
        passenger_code = (
            f"0{day}1019900.0{day}1019900"
        )

    if isinstance(nights, int):
        nights = [nights]

    # Список пар сохраняет повторяющиеся f7.
    params = [
        ("action", "price"),
        ("tid", "211"),
        ("idt", ""),
        ("flt2", city_id),
        ("bfr", "1"),
        ("id_price", id_price or ""),
        ("data", date),
        ("d2", end_date or date),
    ]

    for value in nights:
        params.append(("f7", str(value)))

    params.extend([
        ("f3", ""),
        ("f8", ""),
        ("ho", "0"),
        ("ins", ""),
        ("flt", country_id),
        ("p", passenger_code),
    ])

    response = requests.get(
        "https://www.bgoperator.ru/price.shtml",
        params=params,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "ru-RU,ru;q=0.9",
        },
        timeout=90,
    )
    response.raise_for_status()

    offers = parse_offers(response.text)

    # Диапазон дат: не отбрасываем другие
    # даты внутри выбранного периода.
    offers.sort(key=lambda x: x["price_rub"])

    return {
        "country_id": country_id,
        "city_id": city_id,
        "http": response.status_code,
        "html_size": len(response.content),
        "total": len(offers),
        "nights_found": dict(Counter(
            offer["nights"] for offer in offers
        )),
        "offers": offers,
    }


def main():
    cases = [
        {
            "city": "Екатеринбург",
            "destination": "Таиланд",
            "date": "15.11.2026",
            "end_date": "22.11.2026",
            "nights": [11, 13],
            "id_price": "121163457355",
        },
        {
            "city": "Екатеринбург",
            "destination": "Таиланд",
            "date": "15.11.2026",
            "end_date": "22.11.2026",
            "nights": [11, 13],
            "id_price": "121166921602",
        },
        {
            "city": "Москва",
            "destination": "Турция",
            "date": "20.11.2026",
            "nights": [7],
            "adults": 2,
            "children_ages": [8],
            "id_price": "121110183689",
            "passenger_code": (
                "0201019900.0201019900.0201020180"
            ),
        },
    ]

    print("=== BG: МАРШРУТЫ И СОСТАВ ТУРИСТОВ ===")

    for case in cases:
        print("\n" + "=" * 50)
        print(
            case["city"], "→",
            case["destination"],
            "| шаблон:", case["id_price"]
        )

        try:
            result = search_bg_tours(**case)

            print("HTTP:", result["http"])
            print("HTML байт:", result["html_size"])
            print("Всего предложений:", result["total"])
            print("Ночей:", result["nights_found"])

            for offer in result["offers"][:3]:
                print(
                    "\nОтель:", offer["hotel"],
                    "\nДата:", offer["date"],
                    "\nНочей:", offer["nights"],
                    "\nЦена:", offer["price_rub"], "₽",
                    "\nСсылка:", offer["url"],
                )

            if not result["offers"]:
                print(
                    "Предложений не извлечено. "
                    "Нужно проверить ответ BG."
                )

        except Exception as exc:
            print(
                "ERROR:",
                type(exc).__name__,
                str(exc)[:400],
            )

    print("\n=== ГОТОВО ===")


if __name__ == "__main__":
    main()
