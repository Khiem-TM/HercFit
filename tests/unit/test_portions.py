"""Cộng dinh dưỡng và quy đổi khẩu phần (domains/shared/models/activity.py)."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from domains.shared.models.activity import portion_factor, sum_known


def test_sum_known_unknown_component_makes_total_unknown():
    items = [
        {"energy_kcal": Decimal("100"), "protein_g": Decimal("5")},
        {"energy_kcal": Decimal("50"), "protein_g": None},
    ]
    assert sum_known(items, fields=("energy_kcal", "protein_g")) == {"energy_kcal": Decimal("150"), "protein_g": None}


def _food(unit="g", size=Decimal("100")):
    return SimpleNamespace(serving_unit=unit, serving_size=size, energy_kcal=Decimal("200"), protein_g=None,
                           carbohydrate_g=None, fat_g=None, fiber_g=None)


def test_portion_factor_scales_by_serving_size():
    assert portion_factor(_food(), "g", Decimal("150")) == Decimal("1.5")


def test_portion_factor_rejects_other_unit():
    with pytest.raises(HTTPException) as error:
        portion_factor(_food(unit="g"), "ml", Decimal("150"))
    assert error.value.status_code == 422


def test_portion_factor_requires_basis_when_nutrition_known():
    with pytest.raises(HTTPException) as error:
        portion_factor(_food(size=None), "g", Decimal("150"))
    assert error.value.status_code == 422
