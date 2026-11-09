"""Nguồn và ngưỡng của bộ luật chỉ số sức khoẻ.

Thứ tự ưu tiên nguồn: Bộ Y tế Việt Nam → WHO → hội chuyên môn/cơ quan y tế khác, chỉ khi cấp trên không có
con số cho chỉ số đó. `verified` = con số đã được đối chiếu với văn bản (hoặc bản sao văn bản) ngày `checked`.

Các con số đã đối chiếu (2026-11-09):
* QĐ 2892/QĐ-BYT (22/10/2022), Hướng dẫn chẩn đoán và điều trị bệnh béo phì: bảng BMI theo WHO cho người châu Á
  (< 18,5 thiếu cân; 18,5–22,9 bình thường; 23–24,9 thừa cân; 25–29,9 béo phì độ I; ≥ 30 độ II); vòng bụng
  ≥ 90 cm nam, ≥ 80 cm nữ; "giảm cân từ từ khoảng 2–3 kg/tháng"; lipid < 30% tổng năng lượng; chất xơ 20–30 g;
  vận động cường độ trung bình ít nhất 150 phút mỗi tuần.
* WHO, Oxygen therapy for children (2016): SpO2 bình thường 97–99%, giới hạn dưới 94%; WHO định nghĩa thiếu
  oxy máu là SpO2 < 90%.
* AHA: nhịp tim nghỉ bình thường của người lớn 60–100 lần/phút; người tập luyện có thể thấp tới khoảng 40.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Tier = Literal["byt", "who", "professional"]
Severity = Literal["info", "warn", "urgent"]
Group = Literal["heart", "oxygen", "sleep", "weight", "nutrition", "activity"]
GROUPS: tuple[Group, ...] = ("heart", "oxygen", "sleep", "weight", "nutrition", "activity")
SEVERITY_RANK = {"info": 1, "warn": 2, "urgent": 3}


@dataclass(frozen=True)
class Source:
    key: str
    org: str
    title: str
    year: int
    url: str
    tier: Tier
    verified: bool = False
    checked: str = "2026-11-09"


_SOURCES = (
    Source("byt_2892", "Bộ Y tế", "Quyết định 2892/QĐ-BYT – Hướng dẫn chẩn đoán và điều trị bệnh béo phì", 2022,
           "https://luatvietnam.vn/y-te/quyet-dinh-2892-qd-byt-bo-y-te-232375-d1.html", "byt", verified=True),
    Source("who_activity_2020", "WHO", "WHO guidelines on physical activity and sedentary behaviour", 2020,
           "https://www.who.int/publications/i/item/9789240015128", "who"),
    Source("who_oxygen_2016", "WHO", "Oxygen therapy for children (SpO2 bình thường 97–99%, giới hạn dưới 94%)", 2016,
           "https://www.who.int/publications/i/item/9789241549554", "who", verified=True),
    Source("who_fao_protein_2007", "WHO/FAO/UNU", "Protein and amino acid requirements in human nutrition (TRS 935)",
           2007, "https://www.who.int/publications/i/item/9789241209359", "who"),
    Source("aha_heart_rate", "American Heart Association", "All About Heart Rate (Pulse)", 2024,
           "https://www.heart.org/en/health-topics/high-blood-pressure/the-facts-about-high-blood-pressure/"
           "all-about-heart-rate-pulse", "professional", verified=True),
    Source("nsf_sleep_2015", "National Sleep Foundation", "Hirshkowitz và cs., Sleep duration recommendations",
           2015, "https://doi.org/10.1016/j.sleh.2014.12.010", "professional"),
    Source("nhlbi_1998", "NIH/NHLBI", "Clinical Guidelines on the Identification, Evaluation, and Treatment of "
           "Overweight and Obesity in Adults", 1998, "https://www.ncbi.nlm.nih.gov/books/NBK2003/", "professional"),
    Source("issn_protein_2017", "ISSN", "Jäger và cs., Position Stand: Protein and exercise", 2017,
           "https://doi.org/10.1186/s12970-017-0177-8", "professional"),
    Source("iraki_2019", "Sports (MDPI)", "Iraki và cs., Nutrition Recommendations for Bodybuilders in the "
           "Off-Season", 2019, "https://doi.org/10.3390/sports7070154", "professional"),
    Source("tudor_locke_2013", "Appl Physiol Nutr Metab", "Tudor-Locke và cs., A step-defined sedentary lifestyle "
           "index: < 5000 steps/day", 2013, "https://doi.org/10.1139/apnm-2012-0235", "professional"),
)
SOURCES = {source.key: source for source in _SOURCES}


@dataclass(frozen=True)
class Rule:
    id: str
    group: Group
    metric: str
    unit: str
    sources: tuple[str, ...]
    # Không báo lại cùng luật trong chừng này ngày, trừ khi mức độ tăng lên.
    cooldown_days: int
    # Người dưới 18 tuổi: chỉ các luật có ngưỡng riêng cho lứa tuổi đó.
    minors: bool = False


RULES = {rule.id: rule for rule in (
    Rule("rhr_high", "heart", "Nhịp tim nghỉ", "bpm", ("aha_heart_rate",), 3),
    Rule("rhr_low", "heart", "Nhịp tim nghỉ", "bpm", ("aha_heart_rate",), 3),
    Rule("spo2_low", "oxygen", "SpO2 trung bình khi ngủ", "%", ("who_oxygen_2016",), 2),
    Rule("sleep_short", "sleep", "Thời gian ngủ", "giờ", ("nsf_sleep_2015",), 4, minors=True),
    Rule("weight_loss_fast", "weight", "Tốc độ giảm cân", "kg/tháng", ("byt_2892",), 7),
    Rule("weight_gain_fast", "weight", "Tốc độ tăng cân", "%/tuần", ("iraki_2019",), 7),
    Rule("bmi_band", "weight", "BMI", "kg/m²", ("byt_2892",), 0),
    Rule("waist_high", "weight", "Vòng bụng", "cm", ("byt_2892",), 30),
    Rule("intake_low", "nutrition", "Năng lượng ăn vào", "kcal", ("nhlbi_1998",), 2),
    Rule("intake_off_target", "nutrition", "Năng lượng ăn vào so với mục tiêu", "kcal", ("byt_2892",), 4),
    Rule("deficit_aggressive", "nutrition", "Thâm hụt năng lượng", "kcal/ngày", ("nhlbi_1998",), 3),
    Rule("protein_low", "nutrition", "Đạm", "g/kg", ("who_fao_protein_2007", "issn_protein_2017"), 4),
    Rule("fat_high", "nutrition", "Năng lượng từ chất béo", "%", ("byt_2892",), 7),
    Rule("fiber_low", "nutrition", "Chất xơ", "g", ("byt_2892",), 7),
    Rule("activity_low", "activity", "Phút vận động vừa–mạnh", "phút/tuần", ("byt_2892", "who_activity_2020"), 6,
         minors=True),
    Rule("steps_low", "activity", "Bước chân", "bước", ("tudor_locke_2013",), 4),
)}

# ---------------------------------------------------------------------------- ngưỡng
RHR_HIGH_BPM = 100                 # AHA: trên 100 lần/phút lúc nghỉ là nhịp nhanh
RHR_LOW_BPM = 50                   # dưới 60 là nhịp chậm (AHA); 50 để tránh báo nhầm người khoẻ mạnh
RHR_LOW_TRAINED_BPM = 40           # người tập luyện thường xuyên có thể ở 40–60
SPO2_LOW_PCT = 94                  # WHO: giới hạn dưới của bình thường
SPO2_URGENT_PCT = 90               # WHO: thiếu oxy máu khi SpO2 < 90%
SLEEP_SHORT_NIGHTS = (3, 4)        # 3 trong 4 đêm gần nhất dưới mức khuyến nghị theo tuổi
WEIGHT_LOSS_KG_PER_MONTH = 3.0     # BYT 2892: giảm từ từ khoảng 2–3 kg/tháng
WEIGHT_GAIN_PCT_PER_WEEK = 0.5     # Iraki 2019: tăng 0,25–0,5% cân nặng/tuần khi tăng cơ
WEIGHT_WINDOW_MIN_DAYS = 14
WEIGHT_MIN_WEIGHINS = 4
BMI_BANDS = ((18.5, "Thiếu cân"), (23.0, "Bình thường"), (25.0, "Thừa cân"), (30.0, "Béo phì độ I"),
             (float("inf"), "Béo phì độ II"))
WAIST_HIGH_CM = {"MALE": 90.0, "FEMALE": 80.0}
INTAKE_FLOOR_KCAL = {"FEMALE": 1200.0, "MALE": 1500.0, None: 1350.0}  # như energy.SEX_FLOOR_KCAL
OFF_TARGET_FRACTION = 0.15
OFF_TARGET_DAYS = (3, 4)
DEFICIT_MAX_KCAL = 1000.0          # NHLBI: thâm hụt 500–1.000 kcal/ngày
DEFICIT_DAYS = 3
PROTEIN_MIN_G_PER_KG = 0.8         # WHO/FAO/UNU: mức an toàn 0,83 g/kg/ngày
PROTEIN_TRAINED_G_PER_KG = 1.4     # ISSN: 1,4–2,0 g/kg cho người tập
PROTEIN_DAYS = (3, 4)
FAT_MAX_ENERGY_PCT = 30.0          # BYT 2892: lipid < 30% tổng năng lượng
FAT_MIN_DAYS = 4
FIBER_MIN_G = 20.0                 # BYT 2892: chất xơ 20–30 g/ngày
FIBER_DAYS = (3, 4)
ACTIVITY_MIN_PER_WEEK = 150        # BYT 2892, WHO 2020: ít nhất 150 phút cường độ trung bình mỗi tuần
ACTIVITY_MINOR_MIN_PER_WEEK = 420  # WHO 2020: trẻ 5–17 tuổi trung bình 60 phút/ngày
ACTIVITY_MIN_WORN_DAYS = 5
STEPS_LOW = 5000                   # Tudor-Locke 2013: < 5.000 bước/ngày là lối sống tĩnh tại
STEPS_DAYS = 3

DISCLAIMER = "Thông tin tham khảo, không thay thế chẩn đoán của bác sĩ."
URGENT_NOTE = ("Nếu kèm khó thở, đau ngực, chóng mặt hoặc ngất, hãy liên hệ cơ sở y tế ngay.")


def bmi_band(bmi: float) -> str:
    return next(label for upper, label in BMI_BANDS if bmi < upper)
