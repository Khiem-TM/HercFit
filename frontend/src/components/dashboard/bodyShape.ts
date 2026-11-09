/**
 * Bóng dáng cơ thể theo BMI (SVG 220×432): vai, ngực, eo, hông nở dần khi BMI tăng; dáng nữ hẹp vai, rộng
 * hông hơn. Chỉ là hình minh hoạ cho con số BMI, không phải ảnh quét hay ước tính thành phần cơ thể.
 */
export interface BodyShape {
  torso: string
  armL: string
  armR: string
  headRx: number
  shadow: number
  /** Toạ độ x hai mép ngực / eo / hông, để kẻ đường chú thích số đo. */
  chest: [number, number]
  waist: [number, number]
  hip: [number, number]
}

type Point = [number, number]

/** Đường cong Catmull-Rom (đi qua mọi điểm) dạng lệnh Bézier của SVG. */
export function smooth(points: Point[]): string {
  const r = (value: number) => value.toFixed(1)
  let d = `M${r(points[0][0])} ${r(points[0][1])}`
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[i - 1] ?? points[i]
    const p1 = points[i]
    const p2 = points[i + 1]
    const p3 = points[i + 2] ?? p2
    d += ` C${r(p1[0] + (p2[0] - p0[0]) / 6)} ${r(p1[1] + (p2[1] - p0[1]) / 6)} ${r(p2[0] - (p3[0] - p1[0]) / 6)} `
      + `${r(p2[1] - (p3[1] - p1[1]) / 6)} ${r(p2[0])} ${r(p2[1])}`
  }
  return d
}

export function bodyShape(bmi: number | null, female = false): BodyShape {
  const f = Math.max(0, Math.min(1, ((bmi ?? 22) - 17) / 19))
  const S = 40 + 7 * f - (female ? 5 : 0)
  const C = 35 + 11 * f - (female ? 3 : 0)
  const W = 25 + 20 * f - (female ? 4 : 0)
  const H = 31 + 15 * f + (female ? 4 : 0)
  const K = 21 + 5 * f
  const Cv = 19 + 5 * f
  const A = 12 + f
  const cx = 110
  const half: Point[] = [[9, 62], [12, 80], [S - 9, 88], [S, 101], [C, 130], [(C + W) / 2 + 1, 163], [W, 192], [H, 228],
    [H - 1, 250], [H - 4, 276], [K, 332], [Cv, 366], [A, 402], [17, 416], [5, 416], [6, 402], [4 + f, 366],
    [5 + 2 * f, 332], [3 + 3 * f, 276], [0, 257]]
  const right = half.map(([x, y]): Point => [cx + x, y])
  const left = half.slice(0, -1).reverse().map(([x, y]): Point => [cx - x, y])
  const arm: Point[] = [[S - 1, 99], [S + 7 + 3 * f, 128], [S + 9 + 4 * f, 165], [S + 12 + 4 * f, 204], [S + 13 + 4 * f, 228],
    [S + 15 + 4 * f, 250], [S + 11 + 4 * f, 258], [S + 7 + 3 * f, 252], [S + 5 + 3 * f, 230], [S + 2 + 2 * f, 202],
    [S - 3 + 2 * f, 166], [S - 7 + f, 128]]
  return {
    torso: `${smooth([...right, ...left])} Z`,
    armR: `${smooth(arm.map(([x, y]): Point => [cx + x, y]))} Z`,
    armL: `${smooth(arm.map(([x, y]): Point => [cx - x, y]))} Z`,
    headRx: 16 + 2 * f,
    shadow: H + 22,
    chest: [cx - C, cx + C],
    waist: [cx - W, cx + W],
    hip: [cx - H, cx + H],
  }
}

export function bmiOf(heightCm: number | null | undefined, weightKg: number | null | undefined): number | null {
  return heightCm && weightKg && heightCm > 0 && weightKg > 0 ? weightKg / (heightCm / 100) ** 2 : null
}

/** Phân loại BMI cho người châu Á của Bộ Y tế (QĐ 2892/QĐ-BYT, 2022), cùng ngưỡng với bộ luật cảnh báo của backend. */
export function bmiCategory(bmi: number | null): string {
  if (bmi == null) return 'Chưa đủ số đo'
  if (bmi < 18.5) return 'Thiếu cân'
  if (bmi < 23) return 'Bình thường'
  if (bmi < 25) return 'Thừa cân'
  if (bmi < 30) return 'Béo phì độ I'
  return 'Béo phì độ II'
}

/** Vị trí (%) trên thang 15–35 của thanh BMI. */
export function bmiPosition(bmi: number): number {
  return Math.max(1, Math.min(99, ((bmi - 15) / 20) * 100))
}
