<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { motion } from 'motion-v'
import { indicatorTransition } from '@/motion'
import { num } from '@/components/knowledge/health/healthFormat'
import BarChart, { type BarColumn } from './charts/BarChart.vue'
import DotChart, { type DotColumn } from './charts/DotChart.vue'
import WeightChart from './charts/WeightChart.vue'
import { ddmm, hoursMinutes, localDate, shift, signed, vn, WEEKDAY_LONG, weekday } from './format'
import type { DashboardData } from './useDashboardData'

/** Xu hướng theo khoảng 7 / 28 / 90 ngày. Ngày không có dữ liệu là trống, không bao giờ là 0. */
const props = defineProps<{ data: DashboardData }>()
const emit = defineEmits<{ settings: [tab: 'profile' | 'integrations' | 'notifications']; prefill: [text: string]; 'create-plan': [] }>()

type Topic = 'body' | 'nutrition' | 'activity' | 'recovery'
const TOPICS: [Topic, string][] = [['body', 'Cơ thể'], ['nutrition', 'Dinh dưỡng'], ['activity', 'Vận động'], ['recovery', 'Phục hồi']]
const RANGES = [7, 28, 90]
const RECOVERY: ['sleep' | 'hrv' | 'rhr', string][] = [['sleep', 'Giấc ngủ'], ['hrv', 'HRV'], ['rhr', 'Nhịp tim nghỉ']]
const MACRO = { p: 'var(--hf-blue)', c: 'var(--hf-green)', f: 'var(--hf-amber)' }
const STAGE = { deep: 'var(--hf-blue)', light: 'var(--hf-green)', rem: 'var(--hf-violet)', awake: 'var(--hf-orange)' }

const topic = shallowRef<Topic>('body')
const range = shallowRef(28)
const recovery = shallowRef<'sleep' | 'hrv' | 'rhr'>('sleep')
const hover = shallowRef(-1)

const today = props.data.today
const days = computed(() => Array.from({ length: range.value }, (_, index) => shift(today, index - range.value + 1)))
const label = (iso: string) => `${WEEKDAY_LONG[weekday(iso)]}, ${ddmm(iso)}`
const readout = (iso: string, text: string | null) => `${label(iso)} · ${text ?? 'Không có dữ liệu'}`
const rangeText = computed(() => `${ddmm(days.value[0])} – ${ddmm(today)}/${today.slice(0, 4)}`)
const xLabels = computed<[string, string, string]>(() => [ddmm(days.value[0]), ddmm(days.value[Math.floor(days.value.length / 2)]), ddmm(today)])
const avg = (values: number[]) => (values.length ? values.reduce((a, b) => a + b, 0) / values.length : null)
const health = computed(() => props.data.health.value)
const hasDevice = computed(() => {
  const status = health.value?.connection?.status
  return status === 'ACTIVE' || status === 'NEEDS_REAUTH' || !!health.value?.daily.length
})
const daily = computed(() => new Map((health.value?.daily ?? []).map(row => [row.local_date, row])))
const baselineOf = (metric: string) => health.value?.assessment?.metrics.find(item => item.metric === metric)

/* ---------------------------------------------------------------- cơ thể */
const weightByDay = computed(() => {
  const map = new Map<string, { value: number; at: string; source: string }>()
  for (const metric of props.data.metrics.value) {
    const value = num(metric.weight_kg)
    if (value == null) continue
    const day = localDate(metric.recorded_at)
    const known = map.get(day)
    if (!known || known.at < metric.recorded_at) map.set(day, { value, at: metric.recorded_at, source: metric.source ?? 'MANUAL' })
  }
  return map
})
const weights = computed(() => days.value.map(day => weightByDay.value.get(day)?.value ?? null))
const latestOf = (field: 'body_fat_pct' | 'waist_cm') => [...props.data.metrics.value]
  .sort((a, b) => b.recorded_at.localeCompare(a.recorded_at)).find(metric => num(metric[field] as number | string | null) != null)

/* ---------------------------------------------------------------- dinh dưỡng */
const progressByDay = computed(() => new Map((health.value?.progress ?? []).map(row => [row.date, row])))
const mealsByDay = computed(() => {
  const map = new Map<string, { kcal: number; p: number; c: number; f: number; count: number }>()
  for (const meal of props.data.meals.value) {
    const day = localDate(meal.consumed_at)
    const row = map.get(day) ?? { kcal: 0, p: 0, c: 0, f: 0, count: 0 }
    row.kcal += num(meal.energy_kcal) ?? 0
    row.p += num(meal.protein_g) ?? 0
    row.c += num(meal.carbohydrate_g) ?? 0
    row.f += num(meal.fat_g) ?? 0
    row.count += 1
    map.set(day, row)
  }
  return map
})
const intake = (day: string): number | null => {
  const progress = progressByDay.value.get(day)
  if (progress && progress.meal_count > 0) return num(progress.calories_in.actual)
  return mealsByDay.value.get(day)?.kcal ?? null
}
const target = computed(() => (props.data.targets.value?.status === 'ok' ? num(props.data.targets.value.target_kcal) : null))

/* ---------------------------------------------------------------- vận động */
const trainingsIn = computed(() => props.data.trainings.value
  .filter(item => localDate(item.started_at) >= days.value[0]).sort((a, b) => b.started_at.localeCompare(a.started_at)))
const steps = computed(() => days.value.map(day => daily.value.get(day)?.steps ?? null))

/* ---------------------------------------------------------------- phục hồi */
const sleepByDay = computed(() => {
  const map = new Map<string, NonNullable<typeof health.value>['sleep'][number]>()
  for (const session of health.value?.sleep ?? []) {
    if (session.is_nap) continue
    const known = map.get(session.local_date)
    if (!known || (session.minutes_asleep ?? 0) > (known.minutes_asleep ?? 0)) map.set(session.local_date, session)
  }
  return map
})
const sleepMinutes = (day: string) => daily.value.get(day)?.sleep_minutes ?? sleepByDay.value.get(day)?.minutes_asleep ?? null

/* ---------------------------------------------------------------- mô hình theo chủ đề */
interface Stat { label: string; value: string; unit: string; sub: string; small?: boolean }
interface View {
  empty?: { title: string; body: string; cta: string; act: () => void }
  stats: Stat[]
  title: string
  sub: string
  details: { label: string; sub: string; value: string }[]
  chart: 'weight' | 'dots' | 'bars' | 'none'
  chartEmpty?: string
  dots?: { columns: DotColumn[]; type: 'bar' | 'dot'; min: number; max: number; rows: number; yTop: string; yBottom: string; legend: string; target?: { value: number; label: string } | null }
  bars?: { columns: BarColumn[]; max: number; grid: { value: number; label: string }[]; legend: { color: string; label: string; kind: 'sq' | 'band' | 'ln' }[]; band?: { from: number; to: number } | null; base?: { value: number; label: string } | null }
}

const view = computed<View>(() => {
  const r = range.value
  if (topic.value === 'body') {
    const measured = days.value.flatMap(day => (weightByDay.value.has(day) ? [{ day, ...weightByDay.value.get(day)! }] : []))
    const fat = latestOf('body_fat_pct')
    const waist = latestOf('waist_cm')
    const extra = [
      ...(fat ? [{ label: 'Mỡ cơ thể', sub: `${ddmm(localDate(fat.recorded_at))} · ${fat.source === 'GOOGLE_HEALTH' ? 'Thiết bị' : 'Khai báo'}`, value: `${vn(fat.body_fat_pct, 1)} %` }] : []),
      ...(waist ? [{ label: 'Vòng eo', sub: `${ddmm(localDate(waist.recorded_at))} · Khai báo`, value: `${vn(waist.waist_cm, 1)} cm` }] : []),
    ]
    if (!measured.length) {
      return { stats: [], title: '', sub: '', details: extra, chart: 'none', empty: weightByDay.value.size ? undefined : {
        title: 'Chưa có dữ liệu cân nặng', body: 'Khai báo cân nặng với trợ lý hoặc kết nối thiết bị có cân để theo dõi thay đổi theo thời gian.',
        cta: 'Khai báo với trợ lý', act: () => emit('prefill', 'Cân nặng hôm nay của mình là ') }, chartEmpty: `Không có lần cân nào trong ${r} ngày gần nhất.` }
    }
    const first = measured[0]
    const last = measured[measured.length - 1]
    const delta = Math.round((last.value - first.value) * 10) / 10
    return {
      stats: [
        { label: 'Cân nặng gần nhất', value: vn(last.value, 1), unit: 'kg', sub: `Đo ${label(last.day).toLowerCase()} · ${last.source === 'GOOGLE_HEALTH' ? 'Thiết bị' : 'Khai báo'}` },
        { label: 'Thay đổi trong kỳ', value: signed(delta), unit: 'kg', sub: `Từ ${vn(first.value, 1)} kg (${ddmm(first.day)}) đến ${vn(last.value, 1)} kg (${ddmm(last.day)})` },
        { label: 'Số ngày có đo', value: String(measured.length), unit: 'ngày', sub: `trong ${r} ngày gần nhất` },
      ],
      title: 'Cân nặng theo ngày đo', sub: `Đơn vị kg · ${rangeText.value}`, chart: 'weight',
      details: [...extra, ...measured.slice(-4).reverse().map(item => ({ label: label(item.day), sub: item.source === 'GOOGLE_HEALTH' ? 'Thiết bị' : 'Khai báo', value: `${vn(item.value, 1)} kg` }))],
    }
  }
  if (topic.value === 'nutrition') {
    const past = days.value.slice(0, -1)
    const logged = past.filter(day => intake(day) != null)
    const both = logged.filter(day => num(progressByDay.value.get(day)?.calories_out_actual) != null)
    const diff = avg(both.map(day => (intake(day) as number) - (num(progressByDay.value.get(day)?.calories_out_actual) as number)))
    const canDiff = hasDevice.value && both.length >= 3
    const todayKcal = intake(today)
    const max = Math.max(2600, Math.ceil(Math.max(...days.value.map(day => intake(day) ?? 0), target.value ?? 0) / 200) * 200)
    if (!logged.length && todayKcal == null) {
      return { stats: [], title: '', sub: '', details: [], chart: 'none', empty: { title: 'Chưa có bữa ăn nào được ghi',
        body: 'Khi bạn ghi bữa ăn, năng lượng nạp theo ngày sẽ hiển thị ở đây.', cta: 'Ghi bữa ăn', act: () => emit('prefill', 'Ghi bữa ăn: ') } }
    }
    const protein = num(props.data.targets.value?.today.protein_g)
    const proteinTarget = num(props.data.targets.value?.macros?.protein_g)
    return {
      stats: [
        { label: 'Năng lượng nạp trung bình', value: vn(avg(logged.map(day => intake(day) as number))), unit: 'kcal/ngày', sub: `${logged.length}/${past.length} ngày có ghi nhận · không tính hôm nay` },
        { label: 'Chênh lệch nạp – tiêu hao', value: canDiff && diff != null ? signed(Math.round(diff), 0) : '—', unit: canDiff ? 'kcal/ngày' : '',
          sub: canDiff ? `Trung bình ${both.length} ngày đủ cả hai dữ liệu` : 'Chưa đủ dữ liệu tiêu hao từ thiết bị' },
        { label: 'Mục tiêu năng lượng', value: target.value ? vn(target.value) : '—', unit: target.value ? 'kcal/ngày' : '', sub: target.value ? 'Hệ thống tính từ hồ sơ' : 'Cần hoàn thiện hồ sơ' },
      ],
      title: 'Năng lượng nạp theo ngày', sub: `Đơn vị kcal · ${rangeText.value}`, chart: 'dots',
      dots: {
        type: 'bar', min: 0, max, rows: 10, yTop: vn(max), yBottom: '0', legend: 'Năng lượng đã ghi nhận (kcal)',
        target: target.value ? { value: target.value, label: `Mục tiêu ${vn(target.value)} kcal` } : null,
        columns: days.value.map(day => {
          const kcal = intake(day)
          return { value: kcal, readout: readout(day, kcal != null ? `${vn(kcal)} kcal${day === today ? ' (hôm nay, chưa hết ngày)' : ''}` : null) }
        }),
      },
      details: [
        { label: 'Ngày có ghi nhận', sub: 'không tính hôm nay', value: `${logged.length} / ${past.length}` },
        { label: 'Ngày đủ cả nạp và tiêu hao', sub: 'dùng để tính chênh lệch', value: String(hasDevice.value ? both.length : 0) },
        { label: 'Hôm nay', sub: `${props.data.targets.value?.today.meal_count ?? 0} bữa đã ghi`, value: todayKcal != null ? `${vn(todayKcal)} kcal` : '—' },
        { label: 'Protein hôm nay', sub: 'đã ghi / mục tiêu', value: `${vn(protein ?? 0)}${proteinTarget ? ` / ${vn(proteinTarget)}` : ''} g` },
      ],
    }
  }
  if (topic.value === 'activity') {
    const sessions = trainingsIn.value
    const minutes = sessions.reduce((sum, item) => sum + (item.duration_seconds ?? 0) / 60, 0)
    const last7 = Array.from({ length: 7 }, (_, index) => daily.value.get(shift(today, -1 - index))?.steps ?? null).filter((v): v is number => v != null)
    const stepAvg = avg(last7)
    if (!sessions.length && !steps.value.some(value => value != null) && !hasDevice.value) {
      return { stats: [], title: '', sub: '', details: [], chart: 'none', empty: { title: 'Chưa có buổi vận động nào',
        body: 'Lập lịch tập hoặc kết nối thiết bị để theo dõi buổi tập, thời gian tập và bước chân.', cta: 'Lập lịch với trợ lý', act: () => emit('create-plan') } }
    }
    const max = Math.max(12000, Math.ceil(Math.max(...steps.value.map(v => v ?? 0)) / 3000) * 3000)
    const blue = 'var(--hf-blue)'
    return {
      stats: [
        { label: 'Số buổi tập', value: String(sessions.length), unit: 'buổi', sub: `Đã ghi nhận trong ${r} ngày` },
        { label: 'Tổng thời gian tập', value: minutes ? hoursMinutes(minutes).replace(' phút', 'p').replace(' giờ ', 'g ') : '0', unit: '', sub: `${hoursMinutes(minutes)} trong ${r} ngày`, small: true },
        { label: 'Bước chân TB · 7 ngày', value: stepAvg != null ? vn(stepAvg) : '—', unit: stepAvg != null ? 'bước/ngày' : '',
          sub: stepAvg != null ? 'Cố định 7 ngày gần nhất, không tính hôm nay' : 'Cần kết nối thiết bị' },
      ],
      title: 'Bước chân theo ngày', sub: `Đơn vị bước · ${rangeText.value}`,
      chart: hasDevice.value ? 'bars' : 'none',
      chartEmpty: 'Bước chân cần dữ liệu từ thiết bị. Kết nối Google Health để xem biểu đồ.',
      bars: {
        max, legend: [{ color: blue, label: 'Bước chân', kind: 'sq' }],
        grid: [0, max / 4, max / 2, (3 * max) / 4, max].map(value => ({ value, label: value ? `${vn(value / 1000, 1)}k` : '0' })),
        columns: days.value.map((day, index) => {
          const value = steps.value[index]
          return value != null
            ? { segments: [{ value, color: blue }], title: label(day), aria: `${ddmm(day)}: ${vn(value)} bước`,
                rows: [{ color: blue, value: vn(value), label: day === today ? 'bước · hôm nay, chưa hết ngày' : 'bước' }] }
            : { segments: [], title: label(day), aria: `${ddmm(day)}: không có dữ liệu`, rows: [] }
        }),
      },
      details: sessions.slice(0, 5).map(item => ({ label: item.name, sub: label(localDate(item.started_at)),
        value: item.duration_seconds ? `${Math.round(item.duration_seconds / 60)} phút` : '—' })),
    }
  }
  // Phục hồi
  if (!hasDevice.value) {
    return { stats: [], title: '', sub: '', details: [], chart: 'none', empty: { title: 'Chưa có dữ liệu phục hồi',
      body: 'Giấc ngủ, HRV và nhịp tim nghỉ được đồng bộ từ thiết bị. Kết nối Google Health để theo dõi.', cta: 'Kết nối dữ liệu',
      act: () => emit('settings', 'integrations') } }
  }
  const sleeps = days.value.map(sleepMinutes)
  const hrvs = days.value.map(day => num(daily.value.get(day)?.hrv_ms))
  const rhrs = days.value.map(day => daily.value.get(day)?.resting_hr_bpm ?? null)
  const known = <T,>(values: (T | null)[]) => values.filter((v): v is T => v != null)
  const base = (metric: string, unit: string) => {
    const reading = baselineOf(metric)
    return { label: { sleep_minutes: 'Mức nền giấc ngủ', hrv_ms: 'Mức nền HRV', resting_hr_bpm: 'Mức nền nhịp tim nghỉ' }[metric] as string,
      sub: `28 ngày · ${reading?.baseline_n ?? 0} ngày có dữ liệu`,
      value: reading?.baseline == null ? '—' : unit === 'min' ? hoursMinutes(reading.baseline) : `${vn(reading.baseline)} ${unit}` }
  }
  const common = {
    stats: [
      { label: 'Thời lượng ngủ trung bình', value: hoursMinutes(avg(known(sleeps))), unit: '', sub: `${known(sleeps).length} / ${r} đêm có dữ liệu`, small: true },
      { label: 'HRV trung bình', value: vn(avg(known(hrvs))), unit: 'ms', sub: `${known(hrvs).length} / ${r} ngày có dữ liệu` },
      { label: 'Nhịp tim nghỉ trung bình', value: vn(avg(known(rhrs))), unit: 'bpm', sub: `${known(rhrs).length} / ${r} ngày có dữ liệu` },
    ],
    details: [base('sleep_minutes', 'min'), base('hrv_ms', 'ms'), base('resting_hr_bpm', 'bpm'), { label: 'Nguồn', sub: 'Google Health', value: 'Thiết bị' }],
  }
  if (recovery.value === 'sleep') {
    return {
      ...common, title: 'Giấc ngủ theo đêm', sub: `Đơn vị giờ · ${rangeText.value}`, chart: 'bars',
      bars: {
        max: 600, band: { from: 420, to: 540 },
        grid: [0, 120, 240, 360, 480, 600].map(value => ({ value, label: String(value / 60) })),
        legend: [{ color: STAGE.deep, label: 'Ngủ sâu', kind: 'sq' }, { color: STAGE.light, label: 'Ngủ nhẹ', kind: 'sq' },
                 { color: STAGE.rem, label: 'REM', kind: 'sq' }, { color: STAGE.awake, label: 'Thức giấc', kind: 'sq' },
                 { color: '', label: 'Khuyến nghị 7–9 giờ', kind: 'band' }],
        columns: days.value.map((day, index) => {
          const session = sleepByDay.value.get(day)
          const asleep = sleeps[index]
          const night = `Đêm ${ddmm(shift(day, -1))} → ${ddmm(day)}`
          if (asleep == null) return { segments: [], title: night, aria: `${night}: không có dữ liệu`, rows: [] }
          const staged = session && (session.deep_minutes || session.light_minutes || session.rem_minutes)
          const awake = session?.awake_minutes ?? session?.minutes_awake ?? 0
          const segments = staged
            ? [{ value: session.deep_minutes ?? 0, color: STAGE.deep }, { value: session.light_minutes ?? 0, color: STAGE.light },
               { value: session.rem_minutes ?? 0, color: STAGE.rem }, { value: awake, color: STAGE.awake }]
            : [{ value: asleep, color: STAGE.light }]
          const rows = staged
            ? [{ color: STAGE.deep, value: hoursMinutes(session.deep_minutes), label: 'Ngủ sâu' }, { color: STAGE.light, value: hoursMinutes(session.light_minutes), label: 'Ngủ nhẹ' },
               { color: STAGE.rem, value: hoursMinutes(session.rem_minutes), label: 'REM' }, { color: STAGE.awake, value: hoursMinutes(awake), label: 'Thức giấc' }]
            : [{ color: STAGE.light, value: hoursMinutes(asleep), label: 'Ngủ (không có giai đoạn)' }]
          return { segments, title: night, aria: `${night}: ngủ ${hoursMinutes(asleep)}`, rows, total: staged ? hoursMinutes(asleep + awake) : undefined }
        }),
      },
    }
  }
  if (recovery.value === 'hrv') {
    const violet = 'var(--hf-violet)'
    const baseline = baselineOf('hrv_ms')?.baseline
    const max = Math.max(80, Math.ceil(Math.max(...known(hrvs), baseline ?? 0) / 20) * 20)
    return {
      ...common, title: 'HRV theo ngày', sub: `Đơn vị ms · ${rangeText.value}`, chart: 'bars',
      bars: {
        max, grid: Array.from({ length: max / 20 + 1 }, (_, i) => ({ value: i * 20, label: String(i * 20) })),
        legend: [{ color: violet, label: 'HRV (ms)', kind: 'sq' }, ...(baseline != null ? [{ color: '', label: 'Mức nền 28 ngày', kind: 'ln' as const }] : [])],
        base: baseline != null ? { value: baseline, label: `Mức nền ${vn(baseline)} ms` } : null,
        columns: days.value.map((day, index) => {
          const value = hrvs[index]
          return value != null
            ? { segments: [{ value, color: violet }], title: label(day), aria: `${ddmm(day)}: HRV ${vn(value)} ms`, rows: [{ color: violet, value: `${vn(value)} ms`, label: 'HRV' }] }
            : { segments: [], title: label(day), aria: `${ddmm(day)}: không có dữ liệu`, rows: [] }
        }),
      },
    }
  }
  const values = known(rhrs)
  const min = values.length ? Math.floor(Math.min(...values) / 5) * 5 - 5 : 50
  const max = values.length ? Math.ceil(Math.max(...values) / 5) * 5 + 5 : 70
  return {
    ...common, title: 'Nhịp tim nghỉ theo ngày', sub: `Đơn vị bpm · ${rangeText.value}`, chart: 'dots',
    dots: {
      type: 'dot', min, max, rows: 11, yTop: `${max} bpm`, yBottom: `${min} bpm`, legend: 'Nhịp tim nghỉ (bpm)',
      columns: days.value.map((day, index) => ({ value: rhrs[index], readout: readout(day, rhrs[index] != null ? `${rhrs[index]} bpm` : null) })),
    },
  }
})

/* ---------------------------------------------------------------- donut macro của ngày đang chọn */
const donut = computed(() => {
  if (topic.value !== 'nutrition') return null
  const index = hover.value >= 0 ? hover.value : days.value.length - 1
  const day = days.value[index]
  const meals = mealsByDay.value.get(day)
  const kcal = intake(day)
  const title = `${label(day)}${day === today ? ' · hôm nay' : ''}`
  if (!meals || !(meals.p || meals.c || meals.f)) {
    return { title, sub: kcal != null ? 'Chưa có đủ chi tiết macro cho ngày này' : 'Không có bữa ăn được ghi trong ngày này', has: false, kcal: '', segs: [], rows: [] }
  }
  const kp = meals.p * 4
  const kc = meals.c * 4
  const kf = meals.f * 9
  const total = kp + kc + kf
  const circ = 2 * Math.PI * 46
  let acc = 0
  const segs = [[kp, MACRO.p], [kc, MACRO.c], [kf, MACRO.f]].map(([value, color]) => {
    const len = ((value as number) / total) * circ
    const seg = { color: color as string, dash: `${Math.max(0, len - 2).toFixed(2)} ${(circ - Math.max(0, len - 2)).toFixed(2)}`, offset: (-acc).toFixed(2) }
    acc += len
    return seg
  })
  const macros = props.data.targets.value?.macros
  const rows = ([['Protein', meals.p, kp, macros?.protein_g, MACRO.p], ['Carb', meals.c, kc, macros?.carbohydrate_g, MACRO.c],
                 ['Chất béo', meals.f, kf, macros?.fat_g, MACRO.f]] as [string, number, number, number | undefined, string][])
    .map(([name, grams, energy, goal, color]) => ({ name, color, pct: `${Math.round((energy / total) * 100)}%`, text: `${vn(grams)}${goal ? ` / ${vn(goal)}` : ''} g` }))
  return { title, sub: day === today ? 'Đã ghi nhận đến hiện tại, chưa hết ngày' : 'Phân bổ năng lượng theo macro',
           has: true, kcal: vn(kcal ?? meals.kcal), segs, rows }
})

const barX = computed(() => {
  const n = days.value.length
  const step = n <= 7 ? 1 : n <= 31 ? 2 : 10
  const labels = []
  for (let i = n - 1; i >= 0; i -= step) labels.push({ index: i, label: ddmm(days.value[i]) })
  return labels
})
const sleepSummary = computed(() => {
  if (topic.value !== 'recovery' || recovery.value !== 'sleep') return null
  const pick = hover.value >= 0 ? days.value[hover.value]
    : [...days.value].reverse().find(day => sleepByDay.value.has(day))
  const session = pick ? sleepByDay.value.get(pick) : undefined
  if (!pick || !session) return null
  const parts = [`ngủ ${hoursMinutes(session.minutes_asleep)}`]
  if (session.minutes_to_fall_asleep != null) parts.push(`chờ ngủ ${session.minutes_to_fall_asleep} phút`)
  if (session.minutes_awake != null) parts.push(`thức ${session.minutes_awake} phút`)
  if (num(session.efficiency_pct) != null) parts.push(`hiệu quả ${vn(session.efficiency_pct, 1)}%`)
  return { label: `${pick === today ? 'Đêm gần nhất · ' : 'Đêm '}${ddmm(shift(pick, -1))}`,
           time: `${clockOf(session.start_at)} → ${clockOf(session.end_at)}`, rest: `· ${parts.join(' · ')}` }
})
function clockOf(iso: string) {
  return new Intl.DateTimeFormat('vi-VN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Ho_Chi_Minh' }).format(new Date(iso))
}
function choose(next: Topic) { topic.value = next; hover.value = -1 }
</script>

<template>
  <div class="progress">
    <div class="filters">
      <div class="hf-seg live" role="group" aria-label="Chủ đề">
        <button v-for="[id, name] in TOPICS" :key="id" type="button" :aria-pressed="topic === id" @click="choose(id)">
          <motion.span v-if="topic === id" layout-id="progress-topic" class="hf-seg-ind" :transition="indicatorTransition" />
          <span>{{ name }}</span>
        </button>
      </div>
      <div class="hf-seg live" role="group" aria-label="Khoảng thời gian">
        <button v-for="span in RANGES" :key="span" type="button" :aria-pressed="range === span" @click="range = span; hover = -1">
          <motion.span v-if="range === span" layout-id="progress-range" class="hf-seg-ind" :transition="indicatorTransition" />
          <span>{{ span }} ngày</span>
        </button>
      </div>
    </div>

    <div v-if="view.empty" class="hf-card empty">
      <div class="empty-title">{{ view.empty.title }}</div>
      <p class="hf-mut">{{ view.empty.body }}</p>
      <button type="button" class="hf-btn pri" @click="view.empty.act()">{{ view.empty.cta }}</button>
    </div>

    <div v-else class="hf-grid hf-stagger">
      <div v-for="stat in view.stats" :key="stat.label" class="hf-card hf-c4 stat">
        <div class="hf-lbl">{{ stat.label }}</div>
        <div class="stat-row"><span :class="stat.small ? 'hf-sv2' : 'hf-sv'">{{ stat.value }}</span><span class="hf-mut stat-unit">{{ stat.unit }}</span></div>
        <div class="hf-mut small">{{ stat.sub }}</div>
      </div>

      <div class="hf-card hf-c8">
        <div class="hf-hd">
          <div><h2 class="chart-title">{{ view.title || 'Biểu đồ' }}</h2><div class="hf-mut small" style="margin-top: 4px">{{ view.sub }}</div></div>
          <div v-if="topic === 'recovery'" class="hf-seg soft" role="group" aria-label="Chỉ số phục hồi">
            <button v-for="[id, name] in RECOVERY" :key="id" type="button" :aria-pressed="recovery === id" @click="recovery = id; hover = -1">{{ name }}</button>
          </div>
        </div>
        <div v-if="view.chart === 'none'" class="hf-info centered">{{ view.chartEmpty }}</div>
        <WeightChart v-else-if="view.chart === 'weight'" :days="days" :values="weights" />
        <div v-else-if="view.chart === 'dots' && view.dots" class="dots-row">
          <DotChart class="dots-main" v-bind="view.dots" :x-labels="xLabels" @hover="hover = $event" />
          <div v-if="donut" class="donutp" aria-live="polite">
            <div><div class="donut-title">{{ donut.title }}</div><div class="hf-mut tiny">{{ donut.sub }}</div></div>
            <template v-if="donut.has">
              <div class="donut">
                <svg viewBox="0 0 120 120" width="150" height="150" role="img" aria-label="Tỷ lệ năng lượng từ protein, carb và chất béo">
                  <circle cx="60" cy="60" r="46" fill="none" class="track" stroke-width="16" />
                  <circle v-for="seg in donut.segs" :key="seg.color" cx="60" cy="60" r="46" fill="none" :stroke="seg.color" stroke-width="16"
                          :stroke-dasharray="seg.dash" :stroke-dashoffset="seg.offset" transform="rotate(-90 60 60)" />
                </svg>
                <div class="donut-center"><span>{{ donut.kcal }}</span><span class="hf-mut tiny">kcal</span></div>
              </div>
              <div class="mrows">
                <div v-for="row in donut.rows" :key="row.name" class="mrow"><i :style="{ background: row.color }" />
                  <span><b>{{ row.name }}</b> <span class="hf-mut">· {{ row.pct }}</span></span><span class="hf-mono tiny">{{ row.text }}</span></div>
              </div>
              <div class="hf-mut tiny">Gram đã ghi / mục tiêu ngày · % theo năng lượng</div>
            </template>
            <div v-else class="donut-none" />
          </div>
        </div>
        <BarChart v-else-if="view.chart === 'bars' && view.bars" v-bind="view.bars" :x-labels="barX" @hover="hover = $event">
          <div v-if="sleepSummary" class="sum">
            <span class="hf-mut small">{{ sleepSummary.label }}</span>
            <div class="sum-line"><b>{{ sleepSummary.time }}</b> <span class="hf-mut">{{ sleepSummary.rest }}</span></div>
          </div>
        </BarChart>
      </div>

      <div class="hf-card hf-c4 details">
        <h3 class="hf-h3" style="margin-bottom: 6px">Chi tiết</h3>
        <div v-for="row in view.details" :key="row.label + row.sub" class="hf-kv">
          <div><b>{{ row.label }}</b><br><span>{{ row.sub }}</span></div><div class="v">{{ row.value }}</div>
        </div>
        <p v-if="!view.details.length" class="hf-mut small">Chưa có mục nào trong khoảng này.</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.progress { display: flex; flex-direction: column; gap: 16px; }
.filters { display: flex; gap: 12px; flex-wrap: wrap; justify-content: space-between; }
.empty { align-items: flex-start; padding: 40px; }
.empty-title { font-size: 26px; font-weight: 700; }
.empty p { margin: 0; font-size: 15px; max-width: 560px; line-height: 1.55; }
.stat { gap: 10px; }
.stat-row { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.stat-unit { font-size: 15px; font-weight: 600; }
.small { font-size: 13px; }
.tiny { font-size: 11px; }
.chart-title { margin: 0; font-size: 18px; font-weight: 700; }
.centered { padding: 24px; justify-content: center; }
.dots-row { display: flex; gap: 20px; flex-wrap: wrap; align-items: flex-start; }
.dots-main { flex: 999 1 420px; }
.donutp { flex: 1 1 230px; max-width: 300px; background: var(--hf-fill-2); border-radius: 18px; padding: 16px; display: flex; flex-direction: column; gap: 12px; align-self: stretch; }
.donut-title { font-size: 14px; font-weight: 700; }
.donut { position: relative; width: 150px; height: 150px; align-self: center; }
.track { stroke: var(--hf-press); }
.donut-center { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.donut-center span:first-child { font-size: 22px; font-weight: 700; }
.donut-none { width: 150px; height: 150px; border-radius: 50%; border: 16px solid var(--hf-press); align-self: center; }
.mrows { display: flex; flex-direction: column; gap: 8px; }
.mrow { display: grid; grid-template-columns: 10px minmax(0, 1fr) auto; gap: 8px; align-items: center; font-size: 13px; }
.mrow i { width: 10px; height: 10px; border-radius: 3px; }
.sum { border-top: 1px solid var(--hf-line-2); padding-top: 14px; margin-top: 6px; display: flex; flex-direction: column; gap: 6px; }
.sum-line { font-size: 15px; line-height: 1.5; }
.sum-line b { font-size: 17px; }
.details { gap: 4px; }
</style>
