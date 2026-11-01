/**
 * Màu dữ liệu cho phần sức khoẻ (nền tối #14171d), đã kiểm tra bằng
 * công cụ kiểm định dataviz (validate_palette.js --mode dark --surface "#14171d"):
 * - SERIES: ô phân loại 1, dùng cho mọi biểu đồ một chuỗi.
 * - SLEEP_STAGES: bảng phân loại 4 ô theo thứ tự chồng; ΔE kề nhau kém nhất với người mù màu 17.3, bình thường 20.9.
 * - DIVERGING: hai cực đối lập cho lượng ăn trừ mức tiêu hao; ΔE với người mù màu 26.8, bình thường 31.8.
 * Chữ không bao giờ dùng các màu này; một ô màu hoặc nét chú giải bên cạnh mang nhận diện.
 */
export const SERIES = '#3987e5'
export const SLEEP_STAGES = { DEEP: '#3987e5', LIGHT: '#199e70', REM: '#9085e9', AWAKE: '#d95926' } as const
/** Giấc ngủ không có dữ liệu giai đoạn (theo dõi kiểu cũ): một màu trung tính, không phải sắc thứ năm. */
export const UNSTAGED = '#7d8590'
export const DIVERGING = { negative: '#3987e5', positive: '#d95926' } as const
