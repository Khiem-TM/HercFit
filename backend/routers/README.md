# API hồ sơ, chỉ số cơ thể và mục tiêu

Tài liệu đầy đủ cho **70 thao tác backend**: [API.md](../API.md).
Cách chạy CRUD độc lập với Agent: [README](../README.md).

Prefix: `/api`. Các endpoint bên dưới yêu cầu `Authorization: Bearer <access_token>`
từ luồng Google OAuth hiện có. Người dùng được xác định từ JWT và phải còn hoạt
động trong database; không nhận `user_id` từ body hoặc `X-User-Id` để chọn chủ sở hữu.

## Endpoints

| Method | Path | Chức năng |
| --- | --- | --- |
| GET | `/profile` | Xem hồ sơ hiện tại |
| PATCH | `/profile` | Ghi nhận/cập nhật các trường hồ sơ được gửi |
| PATCH | `/profile/personal-info` | Merge các nhóm cấp đầu của `personal_info` |
| POST | `/profile/onboarding` | Lưu hồ sơ, chỉ số ban đầu và xác nhận goal trong một transaction |
| DELETE | `/profile` | Vô hiệu hoá tài khoản, thu hồi refresh sessions, xoá cookie đăng nhập |
| POST | `/body-metrics` | Ghi nhận chỉ số, trả `201` |
| GET | `/body-metrics` | Xem lịch sử có phân trang và lọc thời gian |
| GET | `/body-metrics/latest` | Xem bản ghi đang hoạt động mới nhất theo `recorded_at` |
| GET | `/body-metrics/{metric_id}` | Xem một bản ghi |
| PUT | `/body-metrics/{metric_id}` | Thay thế bằng snapshot mới, trả ID mới |
| DELETE | `/body-metrics/{metric_id}` | Xoá mềm một bản ghi |
| POST | `/goals/confirm` | Lưu goal đã xác nhận với trạng thái `IN_PROGRESS`, trả `201` |
| GET | `/goals` | Xem lịch sử goals có phân trang |
| GET | `/goals/current` | Xem goal đang thực hiện |
| GET | `/goals/{goal_id}` | Xem chi tiết goal |
| PATCH | `/goals/{goal_id}` | Sửa goal đang thực hiện, bắt buộc `expected_version_id` |
| POST | `/goals/{goal_id}/complete` | Đánh dấu hoàn thành |
| POST | `/goals/{goal_id}/cancel` | Huỷ goal |
| DELETE | `/goals/{goal_id}` | Xoá mềm goal; giải phóng vị trí goal hiện tại |

Các thao tác DELETE trả `204` không có body. DELETE body metric/goal đã xoá vẫn
trả `204` nếu thuộc cùng người dùng. Sau DELETE profile, JWT cũ bị từ chối do tài
khoản không còn hoạt động; dữ liệu lịch sử vẫn được giữ. Đây là thao tác vô hiệu
hoá tài khoản, không chỉ xoá các trường thông tin cá nhân.

Danh sách trả JSON array, hỗ trợ `offset=0`, `limit=50` (tối đa 200),
`include_inactive=false`. Body metrics thêm `recorded_from`, `recorded_to` dạng
ISO 8601 có múi giờ, với hai biên được tính bao gồm. Danh sách metrics sắp xếp
`recorded_at DESC, id DESC`; goals sắp xếp `created_at DESC, id DESC`.
Chi tiết, latest và current chỉ trả dữ liệu còn hoạt động; xem bản ghi đã xoá
qua danh sách với `include_inactive=true`.

## Hợp đồng dữ liệu

OAuth đã tạo bản ghi User. Dùng PATCH profile để ghi nhận thêm thông tin hoặc
POST onboarding để lưu đồng thời các phần liên quan. Không có API tạo tài khoản
bằng email tuỳ ý. Body metric và goal trong onboarding là tuỳ chọn; gửi `null`
cho hai trường này bị từ chối.

```json
{
  "fullname": "Nguyen An",
  "age": 28,
  "personal_info": {"activity": {"level": "moderate"}},
  "body_metric": {"weight_kg": 70.5, "height_cm": 175},
  "goal": {
    "title": "Chạy đều đặn",
    "start_date": "2026-10-17",
    "target_date": "2026-12-31",
    "goal_types": ["running_distance"],
    "targets": {
      "weekly_distance": {"operator": "gte", "unit": "km", "value": 15}
    }
  }
}
```

Goal chưa xác nhận được giữ ở client. POST `/goals/confirm` nhận trực tiếp object
`goal` như ví dụ trên. Mỗi người dùng chỉ có một goal `IN_PROGRESS` còn hoạt động;
cần complete, cancel hoặc delete goal hiện tại trước khi xác nhận goal khác.
Xác nhận lại khi đã có goal hiện tại trả `409`, không tự tạo thêm goal.

PATCH goal gửi `expected_version_id` lấy từ response gần nhất:

```json
{"title": "Chạy đều mỗi tuần", "expected_version_id": 1}
```

Trường bị bỏ qua trong PATCH được giữ nguyên. JSON object được gửi trong PATCH
thay thế toàn bộ giá trị cũ. Riêng `/profile/personal-info` merge ở cấp đầu,
không merge đệ quy. `null` chỉ được chấp nhận ở trường nullable. Payload không
được tự thay đổi ID, chủ sở hữu, lifecycle hoặc email xác thực.

Body metrics là snapshot bất biến. PUT yêu cầu `weight_kg`; các trường tuỳ chọn
không gửi sẽ về mặc định của snapshot mới. `recorded_at` được giữ từ snapshot cũ
nếu không gửi. Bản cũ được xoá mềm và response trả bản mới. Số đo Decimal được
serialize thành JSON string để giữ độ chính xác.

`404`: không tồn tại, đã xoá, hoặc thuộc người dùng khác; latest/current cũng trả
`404` khi chưa có dữ liệu. `409`: goal hiện tại đã tồn tại, version cũ, hoặc thao
tác không hợp lệ trên goal đã kết thúc. `422`: dữ liệu không hợp lệ, bao gồm PATCH
ngày không khớp với ngày còn lại trong DB. Complete/cancel cùng trạng thái có thể
lặp lại; không thể đổi một goal đã hoàn thành sang cancelled hoặc ngược lại.

## Database và kiểm thử

Các API dùng model hiện tại trong `backend/models`. Chuỗi migration hiện có
`0001_initial_schema` (legacy), `0002_current_baseline` (profile/auth/goal/foods)
và `0003_plans_and_journals` (plans, lịch và nhật ký). Chạy preflight và nâng cấp
theo [hướng dẫn migration](../MIGRATIONS.md); dữ liệu legacy cần mapping đầy đủ.
API không tự thay đổi schema khi khởi động.

`body_metrics.height_cm` là tuỳ chọn theo schema đầu vào; model đã được đồng bộ
thành nullable. Với DB đã có đủ schema hiện tại nhưng cột này còn NOT NULL, thay
đổi tương ứng là:

```sql
ALTER TABLE body_metrics ALTER COLUMN height_cm DROP NOT NULL;
```

Đã kiểm thử API qua HTTP ASGI với JWT thật và PostgreSQL riêng, tạo schema từ
metadata hiện tại: CRUD, validation, quyền sở hữu, phân trang, thời gian, lịch sử
snapshot, vòng đời goal, version conflict, rollback onboarding, thu hồi session
và các yêu cầu đồng thời. Bộ kiểm thử backend hiện có cũng đã chạy qua. Script
kiểm thử API và PostgreSQL tạm được dọn sau khi chạy; không thay đổi DB ứng dụng.
