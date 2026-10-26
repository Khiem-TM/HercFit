export type MediaKind = 'meals' | 'trainings' | 'foods' | 'exercises'

export interface MediaTarget {
  kind: MediaKind
  id: string
  /** A portion shows the picture of the meal or training it belongs to. */
  inherited: boolean
}

const KINDS: Record<string, MediaKind> = { Meal: 'meals', Training: 'trainings', Food: 'foods', Exercise: 'exercises' }
const KEY = /^backend:(Meal|Training|Food|Exercise):([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(:item:[^:]+)?$/i

/** Map ids are projection keys, e.g. `backend:Meal:<uuid>` or `backend:Meal:<uuid>:item:0`. */
export function mediaTarget(id: string): MediaTarget | null {
  const match = KEY.exec(id)
  return match ? { kind: KINDS[match[1]], id: match[2].toLowerCase(), inherited: Boolean(match[3]) } : null
}

export const mediaCaption: Record<MediaKind, string> = {
  meals: 'Ảnh bữa ăn', trainings: 'Ảnh buổi tập', foods: 'Ảnh món ăn', exercises: 'Ảnh bài tập',
}

/** Cloudinary serves a resized copy on request; other hosts are used as they are. */
export function sizedImage(url: string, width: number): string {
  return url.replace(/^(https:\/\/res\.cloudinary\.com\/[^/]+\/image\/upload\/)(?![a-z]_)/, `$1c_limit,w_${width},q_auto,f_auto/`)
}
