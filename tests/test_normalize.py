import pytest

from swiss_pantry.pricing.normalize import parse_package_size, price_per_unit, units_compatible


@pytest.mark.parametrize(
    "text, expected",
    [
        ("500g", (500.0, "g")),
        ("1kg", (1000.0, "g")),
        ("1 l", (1000.0, "ml")),
        ("330ml", (330.0, "ml")),
        ("1,5 l", (1500.0, "ml")),
        ("0.75L", (750.0, "ml")),
        ("2x400g", (800.0, "g")),
        ("6 x 125 g", (750.0, "g")),
        ("nature, 310 g", (310.0, "g")),
        ("9 Rollen", (9.0, "roll")),
        ("8 rolls", (8.0, "roll")),
        ("1 roll", (1.0, "roll")),
        ("1 Stk.", (1.0, "piece")),
        ("4 Stück", (4.0, "piece")),
        ("", (None, None)),
        ("ohne Angabe", (None, None)),
    ],
)
def test_parse_package_size(text, expected):
    assert parse_package_size(text) == expected


def test_units_compatible():
    assert units_compatible("g", "g")
    assert units_compatible("piece", "roll")
    assert not units_compatible("g", "ml")
    assert not units_compatible("piece", "ml")
    assert not units_compatible(None, "g")


def test_price_per_unit():
    assert price_per_unit(2.50, 500, "g") == 0.5
    assert price_per_unit(3.00, 6, "roll") == 0.5
    assert price_per_unit(1.0, None, "g") is None
    assert price_per_unit(1.0, 0, "g") is None
