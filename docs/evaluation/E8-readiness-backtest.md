# Backtest Daily Health (2026-11-13)

## Kịch bản mô phỏng (dữ liệu tổng hợp, nhãn do bộ sinh đặt)

| Kịch bản | Ngày | Trạng thái | Báo nhầm (ngày bình thường) | Bắt ngày căng | Bắt ngày ốm (review/recover) | Thiếu dữ liệu → insufficient | Cảnh báo chỉ số/tuần | Theo mức độ |
|---|---|---|---|---|---|---|---|---|
| baseline_normal | 55 | ease_off 6, ready 48, steady 1 | 11% | — | — | — | 0.0 | {} |
| overreaching | 55 | ease_off 4, needs_review 1, ready 43, recover 4, steady 3 | 8% | 100% | — | — | 0.0 | {} |
| illness_onset | 55 | ease_off 6, needs_review 3, ready 43, steady 3 | 12% | — | 100% | — | 0.0 | {} |
| poor_sleep_week | 55 | ease_off 6, ready 43, recover 6 | 10% | 100% | — | — | 0.25 | {'info': 0.25} |
| irregular_sleep | 55 | ease_off 7, ready 43, steady 5 | 13% | — | — | — | 0.0 | {} |
| improving | 55 | ease_off 6, ready 47, steady 2 | 11% | — | — | — | 0.0 | {} |
| missing_data | 55 | ease_off 7, insufficient_data 6, ready 39, recover 2, steady 1 | 18% | — | — | 100% | 0.0 | {} |
| manual_sleep_only | 55 | ready 50, steady 5 | 0% | — | — | — | 0.0 | {} |
| new_user | 55 | insufficient_data 52, ready 3 | 0% | — | — | 100% | 0.13 | {'info': 0.13} |


