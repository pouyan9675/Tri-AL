import math

import numpy as np
import pytest

from tri_al.stats.methods import (
    confidence,
    excess_p,
    false_discovery,
    kaplan_meier,
    months_before,
    smoothed_ratio,
    standardized_difference,
    two_sided_p,
    weighted_quantile,
)


def binomial_tail(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def test_excess_p_is_the_upper_tail() -> None:
    assert excess_p(3, 3, 0.5) == pytest.approx(0.125)
    assert excess_p(1, 3, 0.5) == 1  # not above the expected number
    for k, n in ((5, 10), (9, 20), (30, 40)):
        assert excess_p(k, n, 0.3) == pytest.approx(binomial_tail(k, n, 0.3), rel=1e-9)


def test_two_sided_p_takes_the_smaller_tail() -> None:
    assert two_sided_p(9, 10, 0.5) == pytest.approx(2 * binomial_tail(9, 10, 0.5))
    assert two_sided_p(1, 10, 0.5) == pytest.approx(2 * binomial_tail(9, 10, 0.5))
    assert two_sided_p(5, 10, 0.5) == 1
    assert two_sided_p(0, 0, 0.5) == 1


def test_false_discovery_and_confidence() -> None:
    assert false_discovery([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.02, 0.04, 0.04, 0.02])
    assert [confidence(q) for q in (0.01, 0.1, 0.5)] == ["high", "medium", "low"]


def test_smoothed_ratio_pulls_small_counts_toward_one() -> None:
    # 3 of 100 against 0 of 10,000: raw, infinite.
    small = smoothed_ratio(3, 0, 100, 10_000, 10)
    large = smoothed_ratio(300, 0, 10_000, 1_000_000, 10)
    assert 1 < small < large
    # The same shares on both sides is no difference, whatever the counts.
    assert smoothed_ratio(10, 100, 100, 1_000, 10) == pytest.approx(1)


def test_standardized_difference() -> None:
    assert standardized_difference(0.5, 0.5, share=True) == 0
    assert standardized_difference(0.6, 0.4, share=True) == pytest.approx(0.2 / math.sqrt(0.24))
    assert standardized_difference(12, 10, sd=4) == 0.5
    assert standardized_difference(12, 10, sd=0) == 0


def test_weighted_quantile() -> None:
    values = np.array([1.0, 2.0, 3.0, 4.0])
    assert weighted_quantile(values, np.ones(4), 0.5) == 2
    assert weighted_quantile(values, np.array([0, 0, 1.0, 3.0]), 0.5) == 4
    assert weighted_quantile(values, np.zeros(4), 0.5) is None


def test_kaplan_meier_counts_censored_subjects_until_they_leave() -> None:
    # Times 1, 2 (censored), 3, 3, 5 (censored): at 1, 4 of 5 remain; at 3, 1 of 3 remain.
    curve = kaplan_meier(np.array([1, 2, 3, 3, 5]), np.array([True, False, True, True, False]))
    assert curve.times == (1.0, 3.0)
    assert curve.survival == pytest.approx((0.8, 0.8 / 3))
    assert curve.at_risk == 5
    assert curve.events == 3
    assert curve.median == 3
    assert curve.at(0.5) == 1
    assert curve.at(2) == pytest.approx(0.8)
    empty = kaplan_meier(np.array([]), np.array([], bool))
    assert (empty.at_risk, empty.median) == (0, None)
    # Fewer than half ever have the event: no median.
    assert kaplan_meier(np.array([1, 2, 3]), np.array([True, False, False])).median is None


def test_months_before() -> None:
    from datetime import date

    assert months_before(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert months_before(date(2026, 10, 16), -24) == date(2028, 10, 16)
