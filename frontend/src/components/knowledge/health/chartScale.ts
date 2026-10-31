/** Clean axis bounds and ticks; `fromZero` keeps magnitude charts anchored at zero. */
export function niceScale(values: (number | null | undefined)[], fromZero: boolean, count = 4, fixedStep?: number) {
  const known = values.filter((value): value is number => value != null && Number.isFinite(value))
  let lo = known.length ? Math.min(...known) : 0
  let hi = known.length ? Math.max(...known) : 1
  if (fromZero) { lo = Math.min(0, lo); hi = Math.max(0, hi) }
  if (hi === lo) { hi += 1; lo -= fromZero ? 0 : 1 }
  if (!fromZero) { const pad = (hi - lo) * .15; lo -= pad; hi += pad }
  const raw = (hi - lo) / count
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const step = fixedStep ?? [1, 2, 2.5, 5, 10].map(n => n * magnitude).find(candidate => candidate >= raw) ?? 10 * magnitude
  lo = Math.floor(lo / step) * step
  hi = Math.ceil(hi / step) * step
  const ticks: number[] = []
  for (let tick = lo; tick <= hi + step / 2; tick += step) ticks.push(Math.round(tick * 1000) / 1000)
  return { lo, hi, ticks }
}

/** Axis ticks: compact from ten thousand up (12k), otherwise grouped digits. */
export function tickText(value: number): string {
  if (Math.abs(value) >= 10000) return `${Math.round(value / 100) / 10}k`.replace('.', ',')
  return new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 }).format(value)
}
