"""BG passenger-code probe. Run: python bg_routes_matrix.py

No requests are sent and no bot files are modified.
"""

from datetime import datetime


KNOWN = {
    ("2026-11-15", 36): "0151019900",
    ("2026-11-15", 7): "0151020190",
    ("2026-11-15", 8): "0151020180",
    ("2026-11-15", 15): "0151020110",
}


def candidate_code(date_iso: str, age: int) -> str:
    """EXPERIMENTAL: derived only from observed November 2026 examples."""

    date = datetime.strptime(date_iso, "%Y-%m-%d")

    if not 0 <= age <= 99:
        raise ValueError("Возраст должен быть от 0 до 99")

    prefix = f"{date.day:03d}"

    if age >= 18:
        return prefix + "1019900"

    return prefix + f"1020{26 - age:02d}0"


def build_p(date_iso: str, ages: list[int]) -> str:
    if not ages:
        raise ValueError("Укажите хотя бы одного туриста")

    return ".".join(
        candidate_code(date_iso, age)
        for age in ages
    )


CASES = [
    (
        "2026-11-15",
        [36, 36],
        "0151019900.0151019900",
    ),
    (
        "2026-11-15",
        [36, 36, 15],
        "0151019900.0151019900.0151020110",
    ),
    (
        "2026-11-15",
        [36, 36, 7],
        "0151019900.0151019900.0151020190",
    ),
    (
        "2026-11-15",
        [36, 36, 8],
        "0151019900.0151019900.0151020180",
    ),
    (
        "2026-11-15",
        [36, 8],
        "0151019900.0151020180",
    ),
]


print("=== VERIFIED AGAINST USER-CAPTURED BG REQUESTS ===")

failures = 0

for day, ages, expected in CASES:
    actual = build_p(day, ages)
    passed = actual == expected

    failures += not passed

    print(
        f"{'PASS' if passed else 'FAIL'} "
        f"date={day} ages={ages} p={actual}"
    )


print("\n=== HYPOTHESES — NOT VALIDATED BY BG ===")

for day, ages in [
    ("2026-11-20", [36, 36, 7]),
    ("2026-11-25", [36, 8, 15]),
    ("2026-12-03", [36, 5]),
    ("2026-11-15", [36, 1]),
    ("2026-11-15", [36, 17]),
]:
    print(
        f"UNVERIFIED "
        f"date={day} "
        f"ages={ages} "
        f"p={build_p(day, ages)}"
    )


print(
    f"\nRESULT: "
    f"{len(CASES) - failures}/{len(CASES)} "
    f"known examples matched"
)

if failures:
    raise SystemExit(1)

print(
    "WARNING: matching examples does NOT validate "
    "arbitrary ages, months, or live prices."
)
