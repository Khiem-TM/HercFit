/**
 * Ánh xạ số đo → hình dáng của mô hình cơ thể 3D (hàm thuần, test được không cần WebGL).
 *
 * Mô hình (public/models/body-*.glb, sinh từ Anny/MakeHuman) có 4 morph target: weight_hi/weight_lo (mỡ, khối
 * lượng chung) và muscle_hi/muscle_lo (độ cơ). Tách cân nặng thành hai phần theo tỷ lệ mỡ:
 *   FMI  = BMI × mỡ%        (chỉ số khối mỡ, kg/m²)   → morph mỡ, so với mức tham chiếu theo giới
 *   FFMI = BMI × (1 − mỡ%)  (chỉ số khối không mỡ)    → morph cơ
 * Chưa có % mỡ thì ước tính theo Deurenberg và cs. (1991): mỡ% = 1,2·BMI + 0,23·tuổi − 10,8·(nam) − 5,4.
 * Chiều cao co giãn đều mô hình trong khung nhìn cố định, nên người cao trông cao hơn.
 */
export type BodyModel = 'male' | 'female'

export interface BodyInputs {
  sex: string | null | undefined
  age: number | null | undefined
  heightCm: number | null | undefined
  weightKg: number | null | undefined
  fatPct: number | null | undefined
}

export interface BodyMorph {
  model: BodyModel
  bmi: number
  fatPct: number
  /** % mỡ là ước tính từ BMI (chưa có số đo). */
  estimated: boolean
  /** −1 (gầy) … 1 (nhiều mỡ). */
  weight: number
  /** −1 (ít cơ) … 1 (nhiều cơ). */
  muscle: number
  /** Chiều cao so với chiều cao gốc của mô hình. */
  scale: number
  influences: Record<'weight_hi' | 'weight_lo' | 'muscle_hi' | 'muscle_lo', number>
}

/** Mức tham chiếu ở người trưởng thành khoẻ mạnh (BMI 22: nam ~18% mỡ, nữ ~30%). */
export const REFERENCE: Record<BodyModel, { fmi: number; fmiSpan: number; ffmi: number; ffmiUp: number; ffmiDown: number }> = {
  male: { fmi: 4, fmiSpan: 7, ffmi: 18, ffmiUp: 5, ffmiDown: 3 },
  female: { fmi: 6.6, fmiSpan: 8, ffmi: 15.4, ffmiUp: 4, ffmiDown: 2.5 },
}
const ADULT_AGE = 30

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value))

export function deurenberg(bmi: number, age: number, male: boolean): number {
  return 1.2 * bmi + 0.23 * age - 10.8 * (male ? 1 : 0) - 5.4
}

export function bodyMorph(input: BodyInputs, baseHeightCm: number): BodyMorph | null {
  const height = input.heightCm ?? null
  const weight = input.weightKg ?? null
  if (!height || !weight || height < 50 || weight < 15) return null
  const model: BodyModel = input.sex === 'FEMALE' ? 'female' : 'male'
  const bmi = weight / (height / 100) ** 2
  const measured = input.fatPct != null && input.fatPct > 0
  const fatPct = clamp(measured ? input.fatPct! : deurenberg(bmi, input.age ?? ADULT_AGE, model === 'male'), 3, 60)
  const fmi = bmi * fatPct / 100
  const ffmi = bmi - fmi
  const ref = REFERENCE[model]
  const fat = clamp((fmi - ref.fmi) / ref.fmiSpan, -1, 1)
  let muscle = ffmi >= ref.ffmi ? clamp((ffmi - ref.ffmi) / ref.ffmiUp, 0, 1) : -clamp((ref.ffmi - ffmi) / ref.ffmiDown, 0, 1)
  // Lớp mỡ dày che bớt đường nét cơ: giảm morph cơ khi morph mỡ lớn.
  if (fat > 0 && muscle > 0) muscle *= 1 - 0.5 * fat
  const round = (value: number) => Math.round(value * 1000) / 1000
  return {
    model, bmi: round(bmi), fatPct: round(fatPct), estimated: !measured, weight: round(fat), muscle: round(muscle),
    scale: round(height / baseHeightCm),
    influences: {
      weight_hi: round(Math.max(0, fat)), weight_lo: round(Math.max(0, -fat)),
      muscle_hi: round(Math.max(0, muscle)), muscle_lo: round(Math.max(0, -muscle)),
    },
  }
}
