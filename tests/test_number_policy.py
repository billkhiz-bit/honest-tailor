"""The number policy: value_supported() in scripts/check_cv.py.

These are the cases any sensible policy must get right. Policy-dependent cases (honest understatements such as
"over 1,000" when the source says 1,200) are measured by the benchmark instead, because a strict and a lenient
policy disagree on them by design.
"""
from check_cv import Num, value_supported


def n(value, unit="", qualifier=""):
    return Num(value, unit, qualifier, str(value))


def test_exact_match_is_supported():
    assert value_supported(n(1200), [n(45), n(1200)])


def test_same_hedge_same_value_is_supported():
    assert value_supported(n(15, qualifier="approx"), [n(15, qualifier="approx")])
    assert value_supported(n(30, qualifier="at_most"), [n(30, qualifier="at_most")])


def test_no_candidates_is_unsupported():
    assert not value_supported(n(1200), [])


def test_inflation_above_every_source_is_unsupported():
    assert not value_supported(n(2000), [n(1200), n(45)])
    assert not value_supported(n(18, "%"), [n(12, "%")])


def test_a_hedge_does_not_excuse_inflation():
    assert not value_supported(n(60, qualifier="at_least"), [n(45)])
    assert not value_supported(n(2500, qualifier="approx"), [n(250, qualifier="approx")])


def test_a_large_unrelated_source_number_does_not_back_a_claim():
    # "over 60 stores" must not pass just because the sources mention 30,000 SKUs elsewhere
    assert not value_supported(n(60, qualifier="at_least"), [n(45), n(30000)])
