from app.amounts import convert_e8, from_e8, from_e12, to_e8, to_e12


def test_fixed_point_amount_round_trip() -> None:
    assert to_e8("1281.92745212") == 128_192_745_212
    assert from_e8(128_192_745_212) == "1281.92745212"
    assert from_e8(to_e8("10")) == "10.00"


def test_fx_conversion_is_decimal_exact() -> None:
    rate = to_e12("6.7811")
    assert from_e12(rate) == "6.7811"
    assert from_e8(convert_e8(to_e8("14.5"), rate)) == "98.33"
