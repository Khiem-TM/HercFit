# HercFit CRUD API

Backend cung cấp **70 thao tác HTTP**: 48 mới và 22 hiện có.
Xem [cách chạy](README.md), OpenAPI trực tiếp tại
/openapi.json và Swagger UI tại /docs.

## Danh sách endpoint

API nghiệp vụ dùng Authorization: Bearer <access_token>. Owner lấy từ JWT,
không nhận từ body. Login dùng Google OAuth/refresh cookie; health không cần JWT.
Danh mục SYSTEM được đọc chung, CUSTOM chỉ thuộc người tạo.

| Method | Đường dẫn | Chức năng |
| --- | --- | --- |
| GET | `/api/auth/login` | Bắt đầu OAuth, nhận callback hoặc xoay refresh token |
| POST | `/api/auth/logout` | Thu hồi refresh session, xoá cookie |
| GET | `/api/profile` | Xem hồ sơ |
| PATCH | `/api/profile` | Sửa các trường được gửi |
| PATCH | `/api/profile/personal-info` | Merge JSON cấp đầu |
| POST | `/api/profile/onboarding` | Lưu profile, metric và goal nguyên tử |
| DELETE | `/api/profile` | Vô hiệu hoá tài khoản, thu hồi refresh sessions |
| POST | `/api/body-metrics` | Ghi snapshot lần đo |
| GET | `/api/body-metrics` | Lịch sử và lọc thời gian |
| GET | `/api/body-metrics/latest` | Lần đo hiện hành mới nhất |
| GET | `/api/body-metrics/{metric_id}` | Chi tiết lần đo |
| PUT | `/api/body-metrics/{metric_id}` | Snapshot thay thế, trả ID mới |
| DELETE | `/api/body-metrics/{metric_id}` | Xoá mềm lần đo |
| POST | `/api/goals/confirm` | Xác nhận goal IN_PROGRESS |
| GET | `/api/goals` | Lịch sử goals |
| GET | `/api/goals/current` | Goal đang thực hiện |
| GET | `/api/goals/{goal_id}` | Chi tiết goal |
| PATCH | `/api/goals/{goal_id}` | Sửa goal với version |
| POST | `/api/goals/{goal_id}/complete` | Hoàn thành goal và kết thúc plans liên quan |
| POST | `/api/goals/{goal_id}/cancel` | Huỷ goal và kết thúc plans liên quan |
| DELETE | `/api/goals/{goal_id}` | Xoá mềm goal, kết thúc plans liên quan |
| POST | `/api/foods` | Tạo thực phẩm/món ăn CUSTOM |
| GET | `/api/foods` | Tìm kiếm, lọc và phân trang danh mục |
| GET | `/api/foods/{food_id}` | Chi tiết thực phẩm/món ăn |
| PATCH | `/api/foods/{food_id}` | Sửa CUSTOM của mình với version |
| DELETE | `/api/foods/{food_id}` | Xoá mềm CUSTOM với version |
| POST | `/api/foods/{food_id}/restore` | Khôi phục CUSTOM với version |
| POST | `/api/exercises` | Tạo bài tập CUSTOM |
| GET | `/api/exercises` | Tìm kiếm, lọc và phân trang danh mục |
| GET | `/api/exercises/{exercise_id}` | Chi tiết bài tập |
| PATCH | `/api/exercises/{exercise_id}` | Sửa CUSTOM của mình với version |
| DELETE | `/api/exercises/{exercise_id}` | Xoá mềm CUSTOM với version |
| POST | `/api/exercises/{exercise_id}/restore` | Khôi phục CUSTOM với version |
| POST | `/api/plans` | Tạo plan tổng quát thủ công |
| GET | `/api/plans` | Lịch sử, lọc goal/trạng thái |
| GET | `/api/plans/current` | Xử lý hết hạn, lấy plan hiện tại |
| GET | `/api/plans/{plan_id}` | Chỉ tiêu và snapshot đầu vào |
| PUT | `/api/plans/{plan_id}` | Thay phiên bản, kết thúc bản cũ cùng lịch con |
| POST | `/api/plans/{plan_id}/end` | Kết thúc plan và lịch con |
| DELETE | `/api/plans/{plan_id}` | Xoá mềm plan, kết thúc lịch con |
| POST | `/api/plans/{plan_id}/meal-plans` | Tạo lịch ăn theo ngày |
| GET | `/api/plans/{plan_id}/meal-plans` | Các phiên bản lịch ăn |
| GET | `/api/plans/{plan_id}/meal-plans/current` | lịch ăn hiện tại sau kiểm tra hết hạn |
| GET | `/api/meal-plans/{meal_plan_id}` | Chi tiết lịch ăn, gồm entry/item |
| GET | `/api/meal-plans/{meal_plan_id}/entries` | Lọc entry theo ngày/khoảng ngày, phân trang |
| PUT | `/api/meal-plans/{meal_plan_id}` | Thay toàn bộ lịch bằng phiên bản mới |
| POST | `/api/meal-plans/{meal_plan_id}/end` | Kết thúc riêng lịch |
| DELETE | `/api/meal-plans/{meal_plan_id}` | Xoá mềm, kết thúc lịch |
| POST | `/api/plans/{plan_id}/training-plans` | Tạo lịch tập theo ngày |
| GET | `/api/plans/{plan_id}/training-plans` | Các phiên bản lịch tập |
| GET | `/api/plans/{plan_id}/training-plans/current` | lịch tập hiện tại sau kiểm tra hết hạn |
| GET | `/api/training-plans/{training_plan_id}` | Chi tiết lịch tập, gồm entry/item |
| GET | `/api/training-plans/{training_plan_id}/entries` | Lọc entry theo ngày/khoảng ngày, phân trang |
| PUT | `/api/training-plans/{training_plan_id}` | Thay toàn bộ lịch bằng phiên bản mới |
| POST | `/api/training-plans/{training_plan_id}/end` | Kết thúc riêng lịch |
| DELETE | `/api/training-plans/{training_plan_id}` | Xoá mềm, kết thúc lịch |
| POST | `/api/meals` | Ghi bữa ăn thực tế gồm nhiều item, trong/ngoài lịch |
| GET | `/api/meals` | Nhật ký, lọc ngày/thời gian và phân trang |
| GET | `/api/meals/{meal_id}` | Snapshot chi tiết và tổng |
| PUT | `/api/meals/{meal_id}` | Thay snapshot, tính lại tổng |
| DELETE | `/api/meals/{meal_id}` | Xoá mềm, loại khỏi tiến độ |
| POST | `/api/trainings` | Ghi buổi tập thực tế gồm nhiều item, trong/ngoài lịch |
| GET | `/api/trainings` | Nhật ký, lọc ngày/thời gian và phân trang |
| GET | `/api/trainings/{training_id}` | Snapshot chi tiết và tổng |
| PUT | `/api/trainings/{training_id}` | Thay snapshot, tính lại tổng |
| DELETE | `/api/trainings/{training_id}` | Xoá mềm, loại khỏi tiến độ |
| GET | `/api/progress` | Tổng thực tế theo ngày, không cần plan |
| GET | `/api/plans/{plan_id}/progress` | Đối chiếu thực tế với chỉ tiêu plan |
| GET | `/health` | Tiến trình hoạt động |
| GET | `/health/ready` | DB truy cập được và revision bằng Alembic head |

Alias tương thích: GET /api/login và POST /api/logout, không tính thêm và không
hiện trong OpenAPI. Entry/item ghi qua aggregate; không có CRUD item riêng.

## Hợp đồng chung

- Create trả 201. Endpoint mới trả Location: /api/<resource>/<id>. PUT plan/lịch/
  nhật ký trả 201 và ID mới; PUT body metric giữ 200. PATCH/end/restore/read trả
  200; DELETE trả 204 không body.
- expected_version_id bắt buộc trong body PATCH/PUT/end/restore mới và query DELETE
  mới. Lấy từ version_id response gần nhất. Goal PATCH giữ version như trước;
  các API profile/body metrics và action goal khác giữ hợp đồng cũ.
- 401: xác thực không hợp lệ/tài khoản bị vô hiệu hoá. 404: không tồn tại, ngoài
  quyền sở hữu hoặc đã xoá. Current/latest chưa có dữ liệu trả 404. 409: version
  cũ, slot ACTIVE đã có hoặc trạng thái không phù hợp. 422: dữ liệu không hợp lệ.
  Validation trả detail array có loc; lỗi nghiệp vụ trả detail string.
- ID, owner, lifecycle, snapshot, totals và nguồn plan do server ghi. Plan input
  không nhận source; server ghi {"type":"USER"}. Decimal serialize thành string;
  so sánh theo giá trị số, không theo chữ số 0. Timestamp có offset; offset khác
  nhau có thể biểu diễn cùng một thời điểm.
- PATCH bỏ qua trường thì giữ nguyên; null chỉ cho trường nullable. JSON gửi
  thay toàn bộ object, ngoại trừ merge cấp đầu personal-info.
- PUT gửi lại aggregate đầy đủ gồm các entry/item cần giữ. Plan cũ ENDED và vẫn
  đọc được; journal cũ is_active=false, bản mới có replaces_id. Meal/Training PUT
  bỏ qua thời điểm thực hiện giữ thời điểm cũ; trường tuỳ chọn khác về mặc định.
- Cập nhật/xoá catalog không sửa snapshot đã lưu. FK catalog nullable; snapshot
  còn đọc được cả khi công cụ nội bộ xoá cứng catalog.
- Mỗi người có một goal IN_PROGRESS và một plan ACTIVE. Mỗi plan tối đa một lịch
  ACTIVE mỗi loại. Lịch phải nằm trong thời hạn plan. Goal hoàn thành/huỷ/xoá kết
  thúc plans; thay/kết thúc/xoá plan kết thúc lịch con. Plan ENDED không được PUT
  để mở lại; tạo mới dùng POST.
- Hết hạn xử lý khi lấy current hoặc tạo/thay kế hoạch; chưa có scheduler. Hết
  hạn vẫn được commit khi current trả 404. List/detail chỉ đọc trạng thái đã lưu.
- DELETE profile vô hiệu hoá tài khoản và giữ lịch sử. JWT cũ bị từ chối; OAuth
  không tự kích hoạt lại tài khoản. Logout thu hồi refresh session; access token
  đã phát vẫn có hạn dùng riêng. Dùng lại refresh đã xoay thu hồi chuỗi kế tiếp.

## Bộ lọc

Danh sách trả array; offset=0, limit=50 (1–200), include_inactive=false.
Detail endpoint mới nhận include_inactive=true nhưng vẫn giới hạn quyền.

| Nhóm | Bộ lọc bổ sung và thứ tự |
| --- | --- |
| Foods | search; source_type SYSTEM/CUSTOM; item_type FOOD/DISH; tên chuẩn hoá, id |
| Exercises | search; source_type; kind STRENGTH/SPORT/ENDURANCE; tên chuẩn hoá, id |
| Plans | status ACTIVE/ENDED, goal_id; created_at DESC, id DESC |
| Phiên bản lịch | Parent trong URL, status; created_at DESC, id DESC |
| Entries | on_date hoặc start_date/end_date; ngày, giờ (null cuối), position, id |
| Meals/Trainings | on_date + timezone hoặc recorded_from/recorded_to; thời điểm DESC, id DESC |
| Body metrics | recorded_from/recorded_to, hai biên bao gồm; recorded_at DESC, id DESC |
| Progress | start_date/end_date bắt buộc, timezone mặc định Asia/Ho_Chi_Minh |
| Plan progress | start_date/end_date tuỳ chọn, mặc định biên plan; timezone của plan |

Ngày nhật ký địa phương chuyển sang khoảng UTC [đầu ngày, đầu ngày kế tiếp).
Không kết hợp on_date với timestamp bounds. Timestamp bounds của nhật ký cũng
loại trừ biên trên. Entries dùng ngày có biên bao gồm, scheduled_time địa phương
không có offset. Các mảng item giữ thứ tự gửi. Progress trả từng ngày, không phân
trang; chọn khoảng cần hiển thị. Khoảng plan progress phải nằm trong plan.
Đồ uống dùng serving_unit ML, item_type theo FOOD/DISH hiện có.

## Payload cho luồng hoàn chỉnh

Thay UUID ví dụ bằng ID response trước đó, chọn ngày áp dụng phù hợp.
OAuth tạo User. Onboarding có thể lưu profile, body_metric và goal đồng thời:
xem [profile API](routers/README.md). Tạo catalog trước khi ghi lịch/log.

### Catalog

POST /api/foods: dinh dưỡng theo serving_size/serving_unit.

~~~json
{"name_vi":"Cơm","serving_size":"100","serving_unit":"G","energy_kcal":"130","protein_g":"2.7","carbohydrate_g":"28","fat_g":"0.3","fiber_g":null}
~~~

POST /api/exercises: định nghĩa bài, mức tạ/reps nằm trong item.

~~~json
{"name_vi":"Squat","kind":"STRENGTH","equipment":["barbell"],"muscle_groups":["quadriceps"],"configuration":{"kind":"STRENGTH"}}
~~~

SPORT configuration: {"kind":"SPORT","sport":"football"}.
ENDURANCE configuration: {"kind":"ENDURANCE","activity":"running"}.

### Plan và lịch dự kiến

POST /api/plans:

~~~json
{
  "goal_id":"00000000-0000-4000-8000-000000000001",
  "name":"Kế hoạch tháng 11","start_date":"2030-11-01","end_date":"2030-11-30",
  "timezone":"Asia/Ho_Chi_Minh",
  "calories_in_kcal":"2000","calories_out_kcal":"2300","exercise_calories_kcal":"300",
  "protein_g":"120","carbohydrate_g":"250","fat_g":"60","fiber_g":"25",
  "note":"Chỉ tiêu do người dùng nhập"
}
~~~

Response có payload cùng id, version_id, is_active, timestamps, user_id,
status=ACTIVE, ended_at/end_reason/replaces_id=null, source={"type":"USER"} và
snapshot profile/body metrics/goal. Body metric snapshot có thể null.

POST /api/plans/{plan_id}/meal-plans:

~~~json
{
  "name":"Lịch ăn","start_date":"2030-11-01","end_date":"2030-11-07",
  "entries":[{
    "scheduled_date":"2030-11-01","scheduled_time":"12:00:00","label":"Bữa trưa","meal_type":"LUNCH",
    "items":[{"food_id":"00000000-0000-4000-8000-000000000002","quantity":"150","unit":"G"}]
  }]
}
~~~

POST /api/plans/{plan_id}/training-plans:

~~~json
{
  "name":"Lịch tập","start_date":"2030-11-01","end_date":"2030-11-07",
  "entries":[
    {"scheduled_date":"2030-11-01","label":"Gym","items":[{
      "exercise_id":"00000000-0000-4000-8000-000000000003",
      "performance":{"kind":"STRENGTH","sets":[{"reps":8,"weight_kg":20,"rpe":7},{"reps":6,"weight_kg":30,"rpe":9}]}
    }]},
    {"scheduled_date":"2030-11-02","label":"Nghỉ","is_rest":true,"items":[]}
  ]
}
~~~

Response lịch có entries[].id, items[].id, position và snapshot danh mục.
Dùng entry ID làm source_entry_id khi ghi thực tế; lập lịch không tạo nhật ký.

### Nhật ký thực tế

POST /api/meals:

~~~json
{
  "name":"Bữa trưa","consumed_at":"2030-11-01T12:10:00+07:00","timezone":"Asia/Ho_Chi_Minh",
  "items":[{"food_id":"00000000-0000-4000-8000-000000000002","quantity":"150","unit":"G"}]
}
~~~

Với food ví dụ, response có energy_kcal="195.000000", fiber_g=null,
nutrition_incomplete=true. Totals do server cộng, không nhận từ client.
SERVING là số khẩu phần; G/ML phải khớp catalog, không tự suy diễn mật độ.
Nutrient đã biết cần serving basis đã biết.

POST /api/trainings dùng name, started_at, ended_at hoặc duration_seconds,
timezone, note, source_entry_id tuỳ chọn và items. Mỗi item gồm exercise_id và
performance đúng loại. STRENGTH dùng set như ví dụ lịch, hỗ trợ
EXTERNAL/BODYWEIGHT/ASSISTED, hold/rest/tempo/RPE/RIR/note. Ví dụ các loại còn lại:

~~~json
{"kind":"SPORT","duration_seconds":3600,"intensity":"MODERATE","met":6,"weight_kg":70}
~~~

~~~json
{"kind":"ENDURANCE","duration_seconds":1800,"distance_meters":5000,"weight_kg":70,"elevation_gain_meters":50,"terrain":"road"}
~~~

ENDURANCE response có pace_seconds_per_km=360; không nhận pace từ input.
Nếu biết calories, item có thể thêm:

~~~json
{"calorie_estimate":{"kcal":"300","source":"USER","method":"MANUAL","method_version":"1","inputs":{"device":"watch"}}}
~~~

Không gửi thì calories null; backend không chạy công thức ước tính. Nếu cung
cấp start/end và duration thì chúng phải khớp. Không liên kết log tập vào ngày
nghỉ. Log mới cần ít nhất một item.

### Điều chỉnh và tiến độ

PUT gửi payload tạo đầy đủ cộng expected_version_id, dùng ID mới cho lần sửa
tiếp theo. POST /{id}/end gửi {"expected_version_id":1,"reason":"USER_ENDED"}.
DELETE mới dùng ?expected_version_id=1; restore catalog gửi
{"expected_version_id":2}.

GET /api/progress?start_date=2030-11-01&end_date=2030-11-07 trả
{timezone,start_date,end_date,days:[...]}; plan progress thêm plan_id.
Mỗi ngày có counts, calories_in, exercise_calories, protein/carbohydrate/fat/fiber,
calories_out_target và calories_out_actual. Ví dụ một metric:

~~~json
{"target":"2000","actual":null,"known_total":"195","missing_count":1}
~~~

actual=null khi thiếu dữ liệu; known_total giữ phần đã biết, missing_count đếm
nhật ký thiếu metric đó. Không có nhật ký thì tổng đã ghi là 0, không có nghĩa
người dùng đã ghi đủ hoạt động. Progress độc lập có target=null; plan progress
dùng chỉ tiêu plan và toàn bộ nhật ký trong khoảng, kể cả ngoài lịch.
Calories Out thực tế vẫn null khi chỉ có nhật ký tập luyện. Chỉ snapshot đang
hoạt động được tính; legacy AGGREGATE_ONLY giữ totals gốc, items rỗng, không được
tạo qua HTTP.

## Ranh giới

Chưa có AI, scheduler, Habits, admin/SYSTEM writes, nhập catalog hoặc frontend.
Services/models có thể được Agent tái sử dụng sau. Kiểm thử trên PostgreSQL riêng,
mô phỏng Google ở biên mạng, dùng JWT thật; không thử trên dữ liệu ứng dụng.

