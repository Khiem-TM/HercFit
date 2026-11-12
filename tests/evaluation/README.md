# Bộ eval agent (`evaluation`)

Chạy từ `backend/`, không gọi mạng:

```
LANGFUSE_TRACING=false JEV_MODE=off JWT_SECRET_KEY=ci-only PYTHONPATH=../tests \
  ../.venv/bin/python -m evaluation agent --mode deterministic --out /tmp/hercfit-eval
```

`make -C tests check` chạy lệnh này cùng lint, test và eval an toàn. Cập nhật baseline: thêm `--update-baseline`
(cần cây git sạch).

## Ca chuẩn `datasets/agent_golden.jsonl`

Mỗi ca chạy graph LangGraph thật (`build_workflow`) với model kịch bản (`input.script`, mỗi vai trò một danh sách
đầu ra; hết kịch bản thì router trả lời, tool model trả văn bản `script.tool_reply`) và backend giả
(`adapters/fixtures.py`). Mỗi lượt (`input.turns`) là một thread mới; lượt sau chỉ nhận lại `replying_to_form`, thẻ
món thiếu (khi có `food_choices`) và `turn.state`.

Khoá kỳ vọng dùng để kiểm luật định tuyến (evaluator `ExpectedRules`, điểm `code_rules`):

| Khoá | Ý nghĩa |
|---|---|
| `route_rules` | các tên luật phải có trong `route_trace` của lượt cuối |
| `rules_forbidden` | các tên luật không được có |
| `intents` | intent phải có trong các quyết định của supervisor (nhánh trả về sớm không ghi tên luật, chỉ đặt intent) |
| `intents_forbidden` | intent không được có |

Đầu vào bổ sung cho các nhánh model kịch bản không dựng được:

- `input.user_context`: thẻ ngữ cảnh cá nhân tổng hợp mà backend giả trả cho `GET /api/assistant/context`.
- `turn.state`: các trường đặt thẳng vào state khởi tạo của lượt. Chỉ dùng cho thẻ chọn bản ghi sau tra cứu web (cần
  Tavily) và các nhánh phòng thủ của supervisor; những ca này đánh dấu (*) trong bảng dưới.

Ở chế độ tất định nút research không có Tavily nên kết thúc `failed` (AttributeError). Ca đi tới research chỉ kiểm
tuyến và luật, không kiểm trạng thái cuối.

## Luật định tuyến → ca

Ca `rule_*_fires`/`*_fires` là ca luật kích hoạt; ca `*_quiet` gần giống nhưng luật không kích hoạt. Thứ tự các dòng
là thứ tự luật được xét trong code.

### Trước router (`OrchestrationAgent.decide`, trả về sớm)

| Luật / nhánh | Dấu hiệu trong bản ghi | Ca kích hoạt | Ca không kích hoạt |
|---|---|---|---|
| state `needs_input`/`failed` → trả lời | intent `clarification` | `rule_status_answer_fires`, `forbidden_tool_outside_domain` | `rule_status_answer_quiet` |
| hết ngân sách tool | intent `limit` | `rule_tool_budget_fires` | `rule_tool_budget_quiet` |
| chặn an toàn | intent `SAFETY` | `rule_safety_block_fires`, `self_harm_blocked`, `extreme_deficit_blocked` | `rule_safety_block_quiet` |
| trả lời thẻ chọn bản ghi catalog | intent `catalog_research` | `rule_catalog_choice_fires` (*) | `rule_catalog_choice_quiet` (*) |
| `food_gap_resolved` | tên luật | `meal_custom_food_choice`, `meal_choose_then_confirm` | `rule_food_gap_resolved_quiet` |
| lần đọc chỉ-đọc gặp handoff | intent `READ` | `rule_read_only_handoff_fires` (*) | `rule_read_only_handoff_quiet` (*) |
| handoff tra catalog | intent `catalog_lookup` | `rule_catalog_handoff_fires`, `rule_read_only_handoff_quiet` (*) | `rule_catalog_handoff_quiet` |
| handoff tra cứu bài tập | intent `catalog_research` | `rule_research_handoff_fires` (*) | `rule_research_handoff_quiet` |
| `plan_build_tool` (Coach) | tên luật | `rule_plan_build_tool_fires` | `rule_plan_build_tool_quiet` |
| `meal_log_next` (Nutrition) | tên luật | `rule_meal_log_next_fires`, `meal_two_meals_sequential` | `rule_meal_log_next_quiet` |
| `gym_mode_detailed` (TrainingLog) | tên luật | `rule_gym_mode_detailed_fires` | `rule_gym_mode_quiet` |
| `gym_mode_quick` (TrainingLog) | tên luật | `receipt_after_confirm_quick_gym` | `rule_gym_mode_quiet`, `rule_gym_mode_detailed_fires` |
| `write_done` | tên luật | `meal_exact_fast_path`, `receipt_after_confirm_meal`, `receipt_after_confirm_weight` | `rule_write_done_quiet` |
| cổng định tuyến đọc của Jev | — | không có: eval tất định chạy `JEV_MODE=off`; Jev có bộ eval riêng (`jev_eval.py`) | — |

### Lối tắt trong `decide_step` (`agents/workflow.py`)

| Lối tắt | Dấu hiệu trong bản ghi | Ca kích hoạt | Ca không kích hoạt |
|---|---|---|---|
| đọc nhanh theo mẫu (`fast_route`) | intent `READ`, 0 lần gọi router | `shortcut_fast_read_fires` | `shortcut_fast_read_quiet`, `shortcut_fast_read_mode_blocked` |
| lệnh ghi đơn giản (`simple_route`) | intent `LOG_*`, 0 lần gọi model | `simple_write_weight`, `simple_write_water`, `simple_write_sleep` | `simple_write_question_not_logged` |
| gợi ý món | intent `FOOD_SUGGESTION`, 0 lần gọi router | `shortcut_food_suggestion_fires` | `shortcut_food_suggestion_quiet` |

### Sau router (`OrchestrationAgent.decide`)

| Luật | Ca kích hoạt | Ca không kích hoạt |
|---|---|---|
| `primary_task_domain` | `rule_primary_task_domain_fires` | `rule_primary_task_domain_quiet` |
| giữ quyền chỉ-đọc của quyết định trước (không tên) | `rule_read_only_policy_fires` (*) | `rule_read_only_policy_quiet` |
| `clarify_to_catalog_lookup` | `rule_clarify_to_catalog_lookup_fires` | `rule_clarify_to_catalog_lookup_quiet` |
| `clarify_known_facts` | `rule_clarify_known_facts_fires` | `rule_clarify_known_facts_quiet` |
| `plan_deep` | `rule_plan_deep_fires`, `rule_plan_build_tool_fires` | `rule_plan_deep_quiet`, `goal_update_plan_card` |
| `personalize` | `rule_personalize_fires`, `rule_read_only_policy_quiet` | `rule_personalize_quiet`, `rule_read_only_policy_fires` (*) |
| `chat_to_knowledge` | `rule_chat_to_knowledge_fires` | `rule_chat_to_knowledge_quiet` |
| `training_read_first` | `rule_training_read_first_fires` | `rule_training_read_first_quiet` |
| `plan_catalog_only` | `rule_plan_catalog_only_fires` | `rule_plan_catalog_only_quiet` |
| `tool_next_agent` | `rule_tool_next_agent_fires` | `rule_tool_next_agent_quiet` |
| `knowledge_to_research` | `rule_knowledge_to_research_fires`, `rule_chat_to_knowledge_fires` | `rule_knowledge_to_research_quiet` |
| `food_gap_card` | `rule_food_gap_card_fires` | `rule_food_research_to_catalog_fires` |
| `food_research_to_catalog` | `rule_food_research_to_catalog_fires` | `rule_food_gap_card_fires` |
| kiểm lại miền chỉ-đọc sau các luật (không tên) | `rule_read_only_recheck_fires` (*) | `rule_clarify_to_catalog_lookup_fires` |
| gợi ý món phải tra catalog (không tên, intent `FOOD_SUGGESTION`) | `rule_food_suggestion_override_fires` | `rule_food_suggestion_override_quiet` |
| `plan_mode_only` | `rule_plan_mode_only_fires`, `goal_normal_mode_invite` | `rule_plan_mode_only_quiet` |
| `gym_mode_guard` (TrainingLog.preflight) | `rule_gym_mode_guard_fires` | `rule_gym_mode_guard_quiet` |
| `fan_out` | `rule_fan_out_fires` | `rule_fan_out_quiet` |
