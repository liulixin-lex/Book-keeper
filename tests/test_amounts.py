import pytest

from app.amounts import (
    convert_cny_e8,
    convert_e8,
    from_e8,
    from_e12,
    to_e8,
    to_e12,
)


def test_fixed_point_amount_round_trip() -> None:
    assert to_e8("1281.92745212") == 128_192_745_212
    assert from_e8(128_192_745_212) == "1281.92745212"
    assert from_e8(to_e8("10")) == "10.00"


def test_fx_conversion_is_decimal_exact() -> None:
    rate = to_e12("6.7811")
    assert from_e12(rate) == "6.7811"
    assert from_e8(convert_e8(to_e8("14.5"), rate)) == "98.33"


def test_cny_display_conversion_divides_and_rounds_half_up() -> None:
    rate = to_e12("7.2")
    assert from_e8(convert_cny_e8(to_e8("100"), rate)) == "13.89"
    assert from_e8(convert_cny_e8(to_e8("-100"), rate)) == "-13.89"
    with pytest.raises(ValueError, match="positive"):
        convert_cny_e8(to_e8("100"), 0)
