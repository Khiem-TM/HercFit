"""Mục tiêu năng lượng tất định (domains/nutrition/services/energy.py)."""
from datetime import date

import pytest

from domains.nutrition.services.energy import EnergyInputs, energy_targets, mifflin_st_jeor


@pytest.mark.parametrize(("sex", "expected"), [("MALE", 1648.75), ("FEMALE", 1482.75), (None, 1565.75)])
def test_mifflin_st_jeor_by_sex(sex, expected):
    # 10×70 + 6.25×175 − 5×30 = 1643.75, rồi +5 (nam), −161 (nữ), −78 (không rõ giới).
    assert mifflin_st_jeor(70, 175, 30, sex) == pytest.approx(expected)


def test_fat_loss_never_goes_below_sex_floor():
    result = energy_targets(EnergyInputs(weight_kg=45, height_cm=150, age=40, sex="FEMALE",
                                         activity_level="sedentary", goal_type="fat_loss"))
    # BMR 1026.5 × 1.2 = 1231.8; trừ 0,5%/tuần còn ~984 kcal, dưới sàn nữ 1200.
    assert result.status == "ok"
    assert result.target_kcal == 1200
    assert "intake_floor_applied" in result.warnings


def test_aggressive_deadline_is_capped_at_one_percent_per_week():
    result = energy_targets(EnergyInputs(weight_kg=100, height_cm=180, age=30, sex="MALE",
                                         activity_level="very_active", goal_type="fat_loss", target_weight_kg=80,
                                         target_date=date(2026, 2, 1), today=date(2026, 1, 4)))
    # Cần 5 kg/tuần, bị chặn ở 1% × 100 kg = 1 kg/tuần: TDEE 3762 − 1100 = 2662 kcal.
    assert "target_date_too_aggressive_rate_capped" in result.warnings
    assert result.weekly_change_kg == -1.0
    assert result.target_kcal == 2662
    assert "intake_floor_applied" not in result.warnings


def test_missing_profile_fields_are_listed():
    result = energy_targets(EnergyInputs(weight_kg=None, height_cm=170, age=None))
    assert result.status == "incomplete_profile"
    assert result.missing == ["weight_kg", "age"]
    assert result.target_kcal is None
