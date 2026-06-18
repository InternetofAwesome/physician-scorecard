"""Weighted scoring engine.

Combines whatever data sources you ran into a single 0-100 net score per
candidate. Two design choices worth knowing before you change anything:

  - Missing data is *penalized* (scored 0), not excluded from the average.
    A candidate with no reviews anywhere scores 0 on every review metric --
    they aren't averaged only over the metrics that do have data. This was
    a deliberate choice (see README) but flip it if you'd rather be lenient
    to thin data.
  - A metric with zero variance across your whole candidate pool (e.g. a
    source nobody has a profile on) doesn't change anyone's *rank* even
    under "penalize" -- it just subtracts the same constant from every
    score. Worth dropping such metrics from the weights config entirely so
    the report doesn't imply they're doing something they aren't.
"""
from datetime import date


def years_in_practice_score(years, buckets):
    """buckets: list of [min_inclusive, max_exclusive, score] triples,
    e.g. [[0,5,50],[5,10,100],[10,20,80],[20,999,30]]. Define your own --
    there's no universally "correct" direction for this metric."""
    if years is None:
        return 0
    for lo, hi, s in buckets:
        if lo <= years < hi:
            return s
    return 0


def recency_score(most_recent_date_str, today, decay_days=730):
    if not most_recent_date_str:
        return 0
    days_old = (today - date.fromisoformat(most_recent_date_str)).days
    return max(0, 100 - (days_old / decay_days * 100))


def capped_linear(value, cap):
    if not value:
        return 0
    return min(value, cap) / cap * 100


def rating_and_count_score(rating, count, rating_max=5, count_cap=30):
    if not rating or not count:
        return 0
    return ((rating / rating_max) * 100 + capped_linear(count, count_cap)) / 2


def num_locations_score(n, penalty_per_extra=30):
    if not n or n < 1:
        return 0
    return max(0, 100 - (n - 1) * penalty_per_extra)


def compute_net_score(component_scores, weights):
    """component_scores, weights: dicts keyed by the same metric names.
    Metrics in weights but missing from component_scores are treated as 0
    (penalized) automatically -- pass an explicit 0 if that's not what you
    want for a given candidate/metric."""
    total_weight = sum(weights.values())
    if total_weight == 0:
        return 0.0
    weighted_sum = sum(component_scores.get(k, 0) * w for k, w in weights.items())
    return round(weighted_sum / total_weight, 1)
