from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from bookkeeper.domain.canonical import canonical_json, chain_hash, genesis_hash


def test_sorted_compact_utf8() -> None:
    assert canonical_json({"b": 1, "a": "账"}) == '{"a":"账","b":1}'


def test_datetimes_normalised_to_utc_microseconds() -> None:
    shanghai = timezone(timedelta(hours=8))
    value = datetime(2026, 10, 18, 8, 0, 0, 5, tzinfo=shanghai)
    assert canonical_json(value) == '"2026-10-18T00:00:00.000005Z"'
    assert canonical_json(date(2026, 10, 18)) == '"2026-10-18"'


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError, match="naive"):
        canonical_json(datetime(2026, 1, 1))  # noqa: DTZ001


def test_decimal_normalised() -> None:
    assert canonical_json(Decimal("1.500")) == '"1.5"'
    assert canonical_json(Decimal("0.00")) == '"0"'


def test_chain_hash_depends_on_prev_and_payload() -> None:
    g = genesis_hash("audit", "bk_x")
    h1 = chain_hash(g, {"a": 1})
    assert chain_hash(g, {"a": 1}) == h1
    assert chain_hash(g, {"a": 2}) != h1
    assert chain_hash(genesis_hash("audit", "bk_y"), {"a": 1}) != h1


json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(),
    lambda children: st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=5), children, max_size=4),
    max_leaves=20,
)


@given(st.dictionaries(st.text(max_size=8), json_values, max_size=6))
def test_canonical_is_order_independent(value: dict) -> None:  # type: ignore[type-arg]
    reordered = dict(reversed(list(value.items())))
    assert canonical_json(value) == canonical_json(reordered)
    assert datetime.now(UTC)  # sanity: module imports


def test_sets_bytes_and_unsupported_types() -> None:
    assert canonical_json({"s": {3, 1, 2}}) == '{"s":[1,2,3]}'
    assert canonical_json(b"\x01\xff") == '"01ff"'
    with pytest.raises(TypeError, match="cannot canonicalise"):
        canonical_json(object())


def test_sha256_hex_accepts_text_and_bytes() -> None:
    from bookkeeper.domain.canonical import sha256_hex

    assert sha256_hex("abc") == sha256_hex(b"abc")
    assert len(sha256_hex("abc")) == 64
