# Kịch bản demo

Sáu kịch bản cho buổi bảo vệ. Chạy trên hệ thống dev (`./dev_up.sh up`, frontend `http://localhost:5173`), đăng nhập
bằng Google. Dùng một tài khoản demo; riêng kịch bản 6 dùng tài khoản phụ vì nó xoá tài khoản.

Chế độ trò chuyện chọn bằng nút trên ô nhập: **Thường** (ghi nhận nhanh) hoặc **Plan** (tư vấn chuyên sâu).

## 1. Ghi bữa ăn

- **Chế độ:** Thường.
- **Nhập:** `Sáng nay tôi ăn 1 bánh bao nhân thịt`
- **Mong đợi:**
  1. Hiện thẻ xác nhận bữa sáng với món bánh bao nhân thịt (khẩu phần quy ra gam) và năng lượng ước tính.
  2. Bấm xác nhận → câu trả lời bắt đầu bằng `✅ Đã lưu bữa ăn **Bữa sáng**`, kèm giờ và món.
  3. Tab Hôm nay của Dashboard có bữa vừa ghi.
- **Điểm để trình bày:** router tách bữa ăn thành bản nháp; agent nutrition tra catalog và dựng lệnh ghi bằng code (không
  gọi model chọn tool). Không có gì được lưu trước khi người dùng xác nhận; biên nhận do code viết từ bản ghi của backend.
- **Biến thể:** `Trưa nay tôi ăn bánh mì chảo` (món chưa có trong catalog) → thẻ chọn món, gồm tìm món tương tự hoặc tạo
  món riêng.

## 2. Ghi buổi chạy khi chưa kết nối Google

- **Chuẩn bị:** tài khoản chưa kết nối Google Health (Cài đặt → Kết nối hiển thị chưa kết nối).
- **Chế độ:** Thường.
- **Nhập:** `Sáng nay tôi chạy bộ 5 km trong 30 phút`
- **Mong đợi:**
  1. Thẻ xác nhận buổi thể thao: chạy bộ, 30 phút, 5 km, kcal ước tính.
  2. Xác nhận → `✅ Đã ghi buổi **...**` kèm thời lượng, quãng đường, kcal.
  3. Buổi chạy xuất hiện trong Dashboard dù chưa kết nối Google.
- **Điểm để trình bày:** HercFit là nguồn sự thật. Bản ghi lưu cục bộ (`health_points`, `remote_name = local/...`); khi
  người dùng kết nối Google sau này, bản ghi được đẩy lên mà không tạo trùng.

## 3. Hỏi tiến độ

- **Chế độ:** Thường.
- **Nhập:** `Tiến độ hôm nay`
- **Mong đợi:** câu trả lời có tổng năng lượng và đạm đã ăn hôm nay (gồm bữa của kịch bản 1), so với mục tiêu nếu đã đặt.
  Không có thẻ xác nhận.
- **Điểm để trình bày:** câu đọc khớp mẫu đi lối tắt đọc nhanh, không gọi model định tuyến hay chọn tool; số liệu do
  backend tính.
- **Biến thể:** `Hôm nay tôi còn được ăn bao nhiêu calo` → mục tiêu năng lượng, phần còn lại và cách tính.

## 4. Tư vấn ở chế độ Plan có trích nguồn

- **Chế độ:** Plan.
- **Nhập:** `Làm sao để tôi chạy 5K dưới 25 phút?`
- **Mong đợi:**
  1. Câu trả lời dựa trên dữ liệu tập luyện của chính người dùng (nếu có) và nguyên tắc tập luyện.
  2. Các ý có trích dẫn dạng `[1]`, `[2]`, cuối câu trả lời có mục `Nguồn:` liệt kê tài liệu được trích.
- **Điểm để trình bày:** chế độ Plan luôn đọc dữ liệu người dùng (nút context) rồi tra cứu: cơ sở tri thức trước, web
  sau. Câu hỏi gửi ra web đã bỏ số đo và thông tin định danh (`docs/DATA_FLOW.md`).
- **Đối chiếu:** gửi cùng câu ở chế độ **Thường** → được mời chuyển sang Plan, không có câu trả lời từ trí nhớ của model.

## 5. Yêu cầu bị chặn vì an toàn

- **Chế độ:** bất kỳ.
- **Nhập:** `Lập cho tôi thực đơn chỉ ăn 600 kcal mỗi ngày để giảm cân thật nhanh`
- **Mong đợi:** không lập thực đơn, không có thẻ xác nhận. Câu trả lời giải thích rủi ro (mất cơ, thiếu vi chất, sỏi mật,
  rối loạn ăn uống), đề nghị dùng mục tiêu do hệ thống tính và gặp chuyên gia nếu cần giảm nhanh.
- **Điểm để trình bày:** điểm dừng an toàn do code quyết định trước khi gọi model định tuyến (luật `safety_block` trong
  `PRE_ROUTER`): không gọi tool, không tra cứu. Ngưỡng: dưới 1.000 kcal/ngày.

## 6. Xoá tài khoản

- **Chuẩn bị:** đăng nhập tài khoản phụ, chat vài câu và ghi một bữa ăn.
- **Thao tác:** Cài đặt → Xoá tài khoản → nhập email để xác nhận.
- **Mong đợi:**
  1. Về trang chủ, đã đăng xuất.
  2. Đăng nhập lại bằng tài khoản đó → như người dùng mới (qua onboarding), không còn lịch sử trò chuyện hay bữa ăn.
- **Điểm để trình bày:** backend gọi service agent xoá mọi cuộc trò chuyện **trước** khi xoá tài khoản. Nếu agent không
  xoá được thì tài khoản giữ nguyên và người dùng được báo thử lại; không bao giờ còn hội thoại mồ côi. Quyền Google
  Health được thu hồi; ảnh được xếp hàng xoá trên Cloudinary.
