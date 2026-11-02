
import re
import html
import requests
from html.parser import HTMLParser
from collections import Counter

URL = "https://www.bgoperator.ru/site"

PARAMS = {
    "action": "price",
    "tid": "211",
    "flt": "100410000047",
    "flt2": "100510345650",
    "bfr": "1",
    "data": "15.11.2026",
    "d2": "15.11.2026",
    "f7": "8",
    "ho": "0",
    "ins": "15-40000-USD",
}


class BGRowParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.row = None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "tr":
            if self.row is None:
                self.row = {
                    "text": [],
                    "html": [],
                    "attrs": attrs,
                }
                self.depth = 1
            else:
                self.depth += 1

        if self.row is not None:
            self.row["html"].append(
                self.get_starttag_text() or ""
            )

    def handle_endtag(self, tag):
        if self.row is None:
            return

        self.row["html"].append(f"</{tag}>")

        if tag == "tr":
            self.depth -= 1

            if self.depth == 0:
                self.rows.append(self.row)
                self.row = None

    def handle_data(self, data):
        if self.row is not None:
            value = data.strip()

            if value:
                self.row["text"].append(value)

            self.row["html"].append(data)


def get_param(source, name):
    match = re.search(
        rf"(?:[?&;]|^){re.escape(name)}=([^&#\s\"'<>]+)",
        source,
        flags=re.IGNORECASE,
    )

    return match.group(1) if match else None


def clean_text(parts):
    return re.sub(
        r"\s+",
        " ",
        html.unescape(" ".join(parts)),
    ).strip()


def main():
    print("=== BG: ОТЕЛИ И ЦЕНЫ ===")

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

    parser = BGRowParser()
    parser.feed(response.text)

    print("Всего HTML-строк:", len(parser.rows))

    offers = []

    for row in parser.rows:
        raw = "".join(row["html"])

        templ = get_param(raw, "templ")
        kol = get_param(raw, "kol")

        if not templ or not kol:
            continue

        offers.append({
            "templ": templ,
            "kol": kol,
            "dt": get_param(raw, "dt"),
            "otn": get_param(raw, "otn"),
            "x": get_param(raw, "x"),
            "text": clean_text(row["text"]),
            "raw": raw,
        })

    print("Строк с параметрами тура:", len(offers))

    nights = Counter(item["kol"] for item in offers)
    print("Ночей:", dict(nights))

    print("\n=== ПЕРВЫЕ 5 ПРЕДЛОЖЕНИЙ ===")

    for index, offer in enumerate(offers[:5], 1):
        print(f"\n--- ПРЕДЛОЖЕНИЕ {index} ---")

        for key in ("templ", "kol", "dt", "otn", "x"):
            print(f"{key}: {offer[key]}")

        print("ТЕКСТ СТРОКИ:")
        print(offer["text"][:1200])

        print("HTML СТРОКИ:")
        print(offer["raw"][:2200])

    print("\n=== ПОИСК ЦЕН В СТРОКАХ ===")

    for index, offer in enumerate(offers[:5], 1):
        raw = offer["raw"]

        candidates = []

        for pattern in (
            r".{0,130}(?:USD|RUB|EUR|₽|\$).{0,130}",
            r".{0,130}(?:price|cost|summa|stoim).{0,130}",
        ):
            for match in re.finditer(
                pattern,
                raw,
                flags=re.IGNORECASE | re.DOTALL,
            ):
                snippet = re.sub(
                    r"\s+",
                    " ",
                    match.group(0),
                )

                if snippet not in candidates:
                    candidates.append(snippet)

                if len(candidates) >= 4:
                    break

            if len(candidates) >= 4:
                break

        print(f"\nПредложение {index}:")
        for snippet in candidates:
            print(snippet[:300])

        if not candidates:
            print("Явные маркеры цены не найдены")

    if not offers:
        print("\nСтроки предложений не обнаружены.")
        print(
            "Возможно, параметры находятся в другом "
            "HTML-элементе, а не в tr."
        )
        print("Пример вокруг templ:")

        match = re.search(
            r"templ=",
            response.text,
            flags=re.IGNORECASE,
        )

        if match:
            start = max(0, match.start() - 700)
            end = match.end() + 1000
            print(response.text[start:end])

    print("\n=== ГОТОВО ===")


if __name__ == "__main__":
    main()
