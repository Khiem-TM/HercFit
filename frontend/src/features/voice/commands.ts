/** Lệnh nói khi thẻ xác nhận đang mở: khớp bằng code, không qua model. */

// Từ khoá xuất hiện trong câu duyệt; nhận dạng giọng nói hay nghe sai phần còn lại ("lưu giúp" → "lưu rung",
// "xác nhận" → "sao nhận"), nên chỉ cần câu ngắn có chứa một từ khoá.
const APPROVE = ['đồng ý', 'xác nhận', 'nhận lưu', 'lưu', 'ok', 'oke', 'okay']
// "huỷ" và "hủy" là hai cách đặt dấu của cùng một từ.
const REJECT = ['huỷ', 'hủy']
const REJECT_EXACT = new Set(['không', 'thôi', 'không lưu', 'đừng lưu', 'thôi khỏi', 'bỏ đi'])
// Có các từ này thì câu không còn là một lệnh duyệt đơn thuần: để chat xử lý.
const NEGATION = ['không', 'đừng', 'chưa', 'khoan', 'thôi']
const EDIT = ['nhưng', 'đổi', 'sửa', 'thêm', 'bớt', 'thành', 'là']
const MAX_WORDS = 6

/**
 * 'approve' / 'reject' khi câu nói là một lệnh ngắn ("Xác nhận.", "ok mình đồng ý", "huỷ nhé");
 * câu dài, câu hỏi, câu có phủ định, số hoặc yêu cầu sửa trả về null và đi vào chat như một tin nhắn thường.
 */
export function voiceDecision(spoken: string): 'approve' | 'reject' | null {
  const raw = spoken.normalize('NFC').toLowerCase()
  // Nhận dạng hay nghe "xác nhận" thành "xác nhậm", "sác nhận" (lần thử 15/11).
  const command = raw.replace(/[.,!?…]/g, ' ').replace(/(^|\s)[xs]ác nh\S*/g, '$1xác nhận').replace(/\s+/g, ' ').trim()
  const words = command.split(' ')
  const has = (phrase: string) => ` ${command} `.includes(` ${phrase} `)
  if (!command || words.length > MAX_WORDS || raw.includes('?') || /\d/.test(command) || EDIT.some(has)) return null
  if (REJECT.some(has) || REJECT_EXACT.has(command.replace(/ (nhé|nha|ạ|đi)$/, ''))) return 'reject'
  if (NEGATION.some(has)) return null
  return APPROVE.some(has) ? 'approve' : null
}
