import time

import pytest

from bookkeeper.domain.ids import is_valid_id, new_id, ulid, ulid_timestamp_ms


def test_new_id_has_prefix_and_valid_ulid() -> None:
    value = new_id("txn")
    assert value.startswith("txn_")
    assert len(value) == 4 + 26
    assert is_valid_id(value, "txn")
    assert not is_valid_id(value, "acc")


def test_unknown_prefix_rejected() -> None:
    with pytest.raises(ValueError, match="unknown id prefix"):
        new_id("zzz")


def test_ulid_encodes_timestamp() -> None:
    ms = 1_760_000_000_123
    assert ulid_timestamp_ms(ulid(ms)) == ms
    now = int(time.time() * 1000)
    assert abs(ulid_timestamp_ms(new_id("aud")) - now) < 5000


def test_ulids_sort_by_time() -> None:
    assert ulid(1000) < ulid(2000)


@pytest.mark.parametrize(
    "value",
    [
        "txn",
        "txn_",
        "txn_lowercaseulid000000000000",
        "TXN_01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "abc_01ARZ3NDEKTSV4RRFFQ69G5FAV",
    ],
)
def test_invalid_ids(value: str) -> None:
    assert not is_valid_id(value)


def test_timestamp_range_and_bad_ulid() -> None:
    with pytest.raises(ValueError, match="out of range"):
        ulid(2**48)
    with pytest.raises(ValueError, match="not a ULID"):
        ulid_timestamp_ms("txn_not-a-ulid")
