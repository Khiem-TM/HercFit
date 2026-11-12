import type { HeartRateHour } from '@/types/api'
import type { BarColumn } from './charts/BarChart.vue'

/** Nhịp tim theo giờ của một ngày: cột 24 giờ, phân bố số giờ theo nhịp TB và tóm tắt ngày. */
export interface HeartHour { hour: number; avg: number; min: number | null; max: number | null }

const LOW = 'var(--hf-line-3)'
const HIGH = 'var(--hf-ink)'
// Khoảng nhịp TB mỗi giờ (bpm); chỉ là mốc để đếm, không phải ngưỡng y khoa.
export const BANDS = [
  { label: 'Dưới 60', to: 60 }, { label: '60–79', to: 80 }, { label: '80–99', to: 100 },
  { label: '100–119', to: 120 }, { label: '120 trở lên', to: Infinity },
] as const

export function hours(rows: HeartRateHour[]): HeartHour[] {
  return rows.map(row => ({ hour: row.hour, avg: Number(row.bpm_avg), min: row.bpm_min, max: row.bpm_max }))
    .filter(row => Number.isFinite(row.avg))
}

const pad = (hour: number) => `${String(hour).padStart(2, '0')}:00`

/** Cột nổi từ thấp nhất đến cao nhất của từng giờ; ranh giới hai màu là nhịp TB. Trục bắt đầu ở `base`. */
export function chart(rows: HeartHour[]) {
  const lows = rows.map(row => row.min ?? row.avg)
  const highs = rows.map(row => row.max ?? row.avg)
  const base = rows.length ? Math.max(0, Math.floor((Math.min(...lows) - 10) / 20) * 20) : 40
  const top = rows.length ? Math.ceil((Math.max(...highs) + 10) / 20) * 20 : 140
  const byHour = new Map(rows.map(row => [row.hour, row]))
  const columns: BarColumn[] = Array.from({ length: 24 }, (_, hour) => {
    const row = byHour.get(hour)
    const title = `${pad(hour)}–${pad((hour + 1) % 24)}`
    if (!row) return { segments: [], title, aria: `${title}: không có dữ liệu`, rows: [] }
    const low = row.min ?? row.avg
    const high = row.max ?? row.avg
    const avg = Math.round(row.avg)
    return {
      segments: [{ value: low - base, color: 'transparent' }, { value: Math.max(row.avg - low, 0.5), color: LOW },
                 { value: Math.max(high - row.avg, 0.5), color: HIGH }],
      title,
      aria: `${title}: trung bình ${avg}, thấp nhất ${low}, cao nhất ${high} nhịp mỗi phút`,
      rows: [{ color: HIGH, value: `${high} bpm`, label: 'Cao nhất' }, { color: LOW, value: `${avg} bpm`, label: 'Trung bình' },
             { color: 'var(--hf-faint)', value: `${low} bpm`, label: 'Thấp nhất' }],
    }
  })
  const grid = [] as { value: number; label: string }[]
  for (let bpm = base; bpm <= top; bpm += 20) grid.push({ value: bpm - base, label: String(bpm) })
  return {
    columns, max: top - base, grid,
    xLabels: [0, 6, 12, 18, 23].map(index => ({ index, label: pad(index).slice(0, 2) + 'h' })),
    legend: [{ color: LOW, label: 'Thấp nhất → trung bình', kind: 'sq' as const },
             { color: HIGH, label: 'Trung bình → cao nhất', kind: 'sq' as const }],
  }
}

/** Số giờ có dữ liệu rơi vào từng khoảng nhịp TB. */
export function distribution(rows: HeartHour[]) {
  const counts = BANDS.map(band => ({ label: band.label, hours: 0 }))
  for (const row of rows) counts[BANDS.findIndex(band => row.avg < band.to)].hours += 1
  return counts.map(band => ({ ...band, share: rows.length ? band.hours / rows.length : 0 }))
}

export function summary(rows: HeartHour[]) {
  if (!rows.length) return null
  const lowest = rows.reduce((a, b) => ((b.min ?? b.avg) < (a.min ?? a.avg) ? b : a))
  const highest = rows.reduce((a, b) => ((b.max ?? b.avg) > (a.max ?? a.avg) ? b : a))
  return {
    hours: rows.length,
    // Trung bình các giờ (mỗi giờ một trọng số), khác TB ngày của Google vốn tính theo từng mẫu.
    meanOfHours: Math.round(rows.reduce((sum, row) => sum + row.avg, 0) / rows.length),
    low: { bpm: lowest.min ?? Math.round(lowest.avg), at: pad(lowest.hour) },
    high: { bpm: highest.max ?? Math.round(highest.avg), at: pad(highest.hour) },
  }
}
