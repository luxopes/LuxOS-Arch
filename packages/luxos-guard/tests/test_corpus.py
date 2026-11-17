"""Lux Guard - heuristika nad sbirkou vzorku (guard_corpus.py): nebezpecne zustavaji kriticke,
bezne skripty a pomocnici balicku nejsou kriticke (F-13: falesne poplachy na vlastnim repozitari)."""
import pytest

import luxos_guard_rules as R
from guard_corpus import BAD, GOOD


@pytest.mark.parametrize("name", sorted(BAD))
def test_bad_samples_stay_critical(name):
    fname, text, reason = BAD[name]
    v = R.classify(text.encode(), fname)
    assert v is not None and v.critical, (name, v)
    assert reason in v.reasons, (name, v.reasons)


@pytest.mark.parametrize("name", sorted(GOOD))
def test_good_samples_not_critical(name):
    fname, text = GOOD[name]
    v = R.classify(text.encode(), fname)
    assert v is None or not v.critical, (name, v.reasons)
