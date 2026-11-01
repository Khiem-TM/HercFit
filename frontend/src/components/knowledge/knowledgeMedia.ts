export type MediaKind = 'meals' | 'trainings' | 'foods' | 'exercises'

export interface MediaTarget {
  kind: MediaKind
  id: string
  /** Một khẩu phần hiển thị ảnh của bữa ăn hoặc buổi tập chứa nó. */
  inherited: boolean
}

const KINDS: Record<string, MediaKind> = { Meal: 'meals', Training: 'trainings', Food: 'foods', Exercise: 'exercises' }
const KEY = /^backend:(Meal|Training|Food|Exercise):([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(:item:[^:]+)?$/i

/** Id trên bản đồ là khoá phép chiếu, ví dụ `backend:Meal:<uuid>` hoặc `backend:Meal:<uuid>:item:0`. */
export function mediaTarget(id: string): MediaTarget | null {
  const match = KEY.exec(id)
  return match ? { kind: KINDS[match[1]], id: match[2].toLowerCase(), inherited: Boolean(match[3]) } : null
}

export const mediaCaption: Record<MediaKind, string> = {
  meals: 'Ảnh bữa ăn', trainings: 'Ảnh buổi tập', foods: 'Ảnh món ăn', exercises: 'Ảnh bài tập',
}

/** Cloudinary trả bản đã thu nhỏ theo yêu cầu; host khác được dùng nguyên trạng. */
export function sizedImage(url: string, width: number): string {
  return url.replace(/^(https:\/\/res\.cloudinary\.com\/[^/]+\/image\/upload\/)(?![a-z]_)/, `$1c_limit,w_${width},q_auto,f_auto/`)
}
