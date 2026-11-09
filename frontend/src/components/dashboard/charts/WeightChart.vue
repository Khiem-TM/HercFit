<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { ddmm, signed, vn, WEEKDAY_LONG, weekday } from '../format'

/**
 * Cân nặng theo ngày đo, kiểu biểu đồ chứng khoán: đường nối các ngày có đo, hoặc nến tuần (mở, cao, thấp,
 * đóng) khi khoảng từ 28 ngày. Tăng/giảm không được tô màu tốt/xấu.
 */
const props = defineProps<{ days: string[]; values: (number | null)[] }>()

const mode = shallowRef<'line' | 'candle'>('line')
const hover = shallowRef(-1)
const week = shallowRef(-1)
watch(() => props.days, () => { hover.value = -1; week.value = -1 })

const n = computed(() => props.days.length)
const points = computed(() => props.values.flatMap((value, index) => (value == null ? [] : [{ index, value }])))
const first = computed(() => points.value[0])
const last = computed(() => points.value[points.value.length - 1])
const high = computed(() => points.value.reduce((a, b) => (b.value > a.value ? b : a), points.value[0]))
const low = computed(() => points.value.reduce((a, b) => (b.value < a.value ? b : a), points.value[0]))
const lo = computed(() => Math.floor((low.value.value - 0.3) * 2) / 2)
const hi = computed(() => Math.ceil((high.value.value + 0.3) * 2) / 2)
const candleOk = computed(() => n.value >= 28)
const shownMode = computed(() => (mode.value === 'candle' && candleOk.value ? 'candle' : 'line'))

const X = (i: number) => ((i + 0.5) / n.value) * 1000
const Y = (v: number) => 300 - ((v - lo.value) / (hi.value - lo.value)) * 300
const xp = (i: number) => `${(((i + 0.5) / n.value) * 100).toFixed(2)}%`
const bp = (v: number) => `${(((v - lo.value) / (hi.value - lo.value)) * 100).toFixed(2)}%`
const tp = (v: number) => `${(100 - ((v - lo.value) / (hi.value - lo.value)) * 100).toFixed(2)}%`

const grid = computed(() => {
  const step = hi.value - lo.value > 4 ? 1 : 0.5
  const lines = []
  for (let v = lo.value; v <= hi.value + 1e-9; v += step) lines.push(v)
  return lines
})
const line = computed(() => `M${points.value.map(p => `${X(p.index).toFixed(1)} ${Y(p.value).toFixed(1)}`).join(' L')}`)
const area = computed(() => `${line.value} L${X(last.value.index).toFixed(1)} 300 L${X(first.value.index).toFixed(1)} 300 Z`)
const change = computed(() => Math.round((last.value.value - first.value.value) * 10) / 10)
const changePct = computed(() => Math.round(((change.value / first.value.value) * 100) * 10) / 10)
const label = (i: number) => `${WEEKDAY_LONG[weekday(props.days[i])]}, ${ddmm(props.days[i])}`

const candles = computed(() => {
  const groups = new Map<number, number[]>()
  props.days.forEach((day, index) => {
    const start = index - ((weekday(day) + 6) % 7)
    groups.set(start, [...(groups.get(start) ?? []), index])
  })
  return [...groups.values()].flatMap(indices => {
    const measured = indices.filter(i => props.values[i] != null)
    if (!measured.length) return []
    const vals = measured.map(i => props.values[i] as number)
    const open = vals[0]
    const close = vals[vals.length - 1]
    const a = indices[0]
    const b = indices[indices.length - 1]
    return [{ open, close, high: Math.max(...vals), low: Math.min(...vals), count: vals.length,
              center: (a + b) / 2, width: Math.max(1, b - a + 1), title: `Tuần ${ddmm(props.days[a])}–${ddmm(props.days[b])}` }]
  })
})

const info = computed(() => {
  if (shownMode.value === 'candle' && week.value >= 0) {
    const c = candles.value[week.value]
    return `${c.title} · Mở ${vn(c.open, 1)} · Cao ${vn(c.high, 1)} · Thấp ${vn(c.low, 1)} · Đóng ${vn(c.close, 1)} kg · ${c.count} lần đo`
  }
  if (shownMode.value === 'line' && hover.value >= 0) {
    const value = props.values[hover.value]
    return value == null ? `${label(hover.value)} · không có lần đo`
      : `${label(hover.value)} · ${vn(value, 1)} kg · so với đầu kỳ ${signed(Math.round((value - first.value.value) * 10) / 10)} kg`
  }
  return `Mới nhất ${label(last.value.index).toLowerCase()} · ${vn(last.value.value, 1)} kg`
})
const hoverY = computed(() => {
  if (shownMode.value === 'candle') return week.value >= 0 ? candles.value[week.value].close : null
  return hover.value >= 0 ? props.values[hover.value] : null
})
const xLabels = computed(() => {
  const step = n.value <= 7 ? 1 : n.value <= 31 ? 2 : 10
  const labels = []
  for (let i = n.value - 1; i >= 0; i -= step) labels.push({ i, label: ddmm(props.days[i]) })
  return labels
})
</script>

<template>
  <div class="wchart">
    <div class="hf-hd top">
      <div>
        <div class="head"><span class="hf-dg" style="font-size: 52px">{{ vn(last.value, 1) }}</span><span class="hf-mut unit">kg</span>
          <span class="chg">{{ change < 0 ? '▼ ' : change > 0 ? '▲ ' : '' }}{{ signed(change) }} kg ({{ signed(changePct) }}%)</span></div>
        <div class="hf-mono hf-mut ohlc">Đầu kỳ {{ vn(first.value, 1) }} · Cao {{ vn(high.value, 1) }} · Thấp {{ vn(low.value, 1) }} · Cuối kỳ {{ vn(last.value, 1) }}</div>
      </div>
      <div class="hf-seg soft" role="group" aria-label="Kiểu biểu đồ cân nặng">
        <button type="button" :aria-pressed="shownMode === 'line'" @click="mode = 'line'">Đường</button>
        <button type="button" :aria-pressed="shownMode === 'candle'" :disabled="!candleOk" :title="candleOk ? 'Nến tuần' : 'Cần khoảng từ 28 ngày'"
                @click="mode = 'candle'">Nến tuần</button>
      </div>
    </div>
    <div class="hf-mono info" aria-live="polite">{{ info }}</div>
    <div class="skw" @mouseleave="hover = -1; week = -1">
      <div class="skp">
        <div v-for="value in grid" :key="value" class="gline" :style="{ bottom: bp(value) }" />
        <div class="lastline" :style="{ bottom: bp(last.value) }" />
        <template v-if="shownMode === 'line'">
          <svg viewBox="0 0 1000 300" preserveAspectRatio="none" aria-hidden="true">
            <defs><linearGradient id="weight-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" class="fill-top" /><stop offset="1" class="fill-bottom" /></linearGradient></defs>
            <path :d="area" fill="url(#weight-fill)" />
            <path :d="line" class="stroke" vector-effect="non-scaling-stroke" />
          </svg>
          <span v-for="p in points" :key="p.index" class="pt" :class="{ on: hover === p.index }" :style="{ left: xp(p.index), top: tp(p.value) }" />
          <span class="hl" :style="{ left: xp(high.index), top: tp(high.value) }">Cao {{ vn(high.value, 1) }}</span>
          <span class="hl dn" :style="{ left: xp(low.index), top: tp(low.value) }">Thấp {{ vn(low.value, 1) }}</span>
          <div class="cols">
            <button v-for="(day, index) in days" :key="day" type="button" class="c"
                    :aria-label="`${label(index)}: ${values[index] != null ? `${vn(values[index], 1)} kg` : 'không có lần đo'}`"
                    @mouseenter="hover = index" @focus="hover = index" @click="hover = index" />
          </div>
          <div v-if="hover >= 0" class="vx" :style="{ left: xp(hover) }" />
        </template>
        <template v-else>
          <button v-for="(c, index) in candles" :key="c.title" type="button" class="cd" :class="{ on: week === index }"
                  :style="{ left: `${(((c.center + 0.5) / n) * 100).toFixed(2)}%`, width: `${((c.width / n) * 62).toFixed(2)}%` }"
                  :aria-label="`${c.title}: mở ${vn(c.open, 1)}, cao ${vn(c.high, 1)}, thấp ${vn(c.low, 1)}, đóng ${vn(c.close, 1)} kg`"
                  @mouseenter="week = index" @focus="week = index" @click="week = index">
            <span class="wick" :style="{ top: tp(c.high), height: `${(((c.high - c.low) / (hi - lo)) * 100).toFixed(2)}%` }" />
            <span class="cbody" :class="c.close > c.open ? 'up' : 'dn'"
                  :style="{ top: tp(Math.max(c.open, c.close)), height: `${Math.max(0.8, (Math.abs(c.open - c.close) / (hi - lo)) * 100).toFixed(2)}%` }" />
          </button>
        </template>
        <div v-if="hoverY != null" class="hy" :style="{ bottom: bp(hoverY) }" />
      </div>
      <div class="ska" aria-hidden="true">
        <span v-for="value in grid" :key="value" class="hf-mono" :style="{ bottom: bp(value) }">{{ vn(value, 1) }}</span>
        <span class="tag last hf-mono" :style="{ bottom: bp(last.value) }">{{ vn(last.value, 1) }}</span>
        <span v-if="hoverY != null" class="tag now hf-mono" :style="{ bottom: bp(hoverY) }">{{ vn(hoverY, 1) }}</span>
      </div>
    </div>
    <div class="xl" aria-hidden="true">
      <span v-for="item in xLabels" :key="item.i" class="hf-mono" :style="{ left: xp(item.i) }">{{ item.label }}</span>
    </div>
    <div class="hf-lg">
      <template v-if="shownMode === 'line'">
        <span><i class="lnb" />Cân nặng (kg) — nối các ngày có đo</span><span><i class="ptb" />Ngày có đo</span>
        <span>Tăng/giảm không được tô tốt/xấu</span>
      </template>
      <template v-else>
        <span><i class="cup" />Nến rỗng: cuối tuần cao hơn đầu tuần</span><span><i class="cdn" />Nến đặc: cuối tuần thấp hơn hoặc bằng</span>
        <span>Râu nến = cao nhất/thấp nhất trong tuần</span>
      </template>
    </div>
  </div>
</template>

<style scoped>
.wchart { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.top { align-items: flex-end; }
.head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.unit { font-size: 16px; font-weight: 600; }
.chg { display: inline-flex; align-items: center; gap: 4px; border-radius: 999px; background: var(--hf-ink); color: var(--hf-on-ink); font-size: 13px; font-weight: 600; padding: 4px 10px; white-space: nowrap; }
.ohlc { font-size: 12px; margin-top: 8px; }
.info { font-size: 13px; font-weight: 600; min-height: 22px; }
.skw { display: grid; grid-template-columns: minmax(0, 1fr) 60px; gap: 6px; }
.skp { position: relative; height: 280px; border-bottom: 1px solid var(--hf-press); }
.skp svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
.fill-top { stop-color: var(--hf-blue); stop-opacity: .22; }
.fill-bottom { stop-color: var(--hf-blue); stop-opacity: 0; }
.stroke { fill: none; stroke: var(--hf-blue); stroke-width: 2.2; stroke-linejoin: round; }
.gline { position: absolute; left: 0; right: 0; border-top: 1px solid var(--hf-line-2); }
.lastline { position: absolute; left: 0; right: 0; border-top: 1px dotted var(--hf-blue); pointer-events: none; }
.pt { position: absolute; width: 7px; height: 7px; border-radius: 50%; background: var(--hf-card); border: 2px solid var(--hf-blue); transform: translate(-50%, -50%); pointer-events: none; }
.pt.on { width: 12px; height: 12px; background: var(--hf-blue); box-shadow: 0 0 0 5px rgba(37, 99, 235, .18); z-index: 2; }
.hl { position: absolute; transform: translate(-50%, -170%); font-size: 10px; font-weight: 600; background: var(--hf-card); border: 1px solid var(--hf-press); border-radius: 6px; padding: 1px 6px; white-space: nowrap; pointer-events: none; }
.hl.dn { transform: translate(-50%, 60%); }
.cols { position: absolute; inset: 0; display: flex; }
.c { flex: 1; min-width: 0; height: 100%; border: 0; background: transparent; padding: 0; margin: 0; cursor: crosshair; }
.vx { position: absolute; top: 0; bottom: 0; border-left: 1px dashed var(--hf-ink); pointer-events: none; }
.hy { position: absolute; left: 0; right: 0; border-top: 1px dashed var(--hf-ink); pointer-events: none; }
.cd { position: absolute; top: 0; bottom: 0; transform: translateX(-50%); border: 0; background: transparent; padding: 0; margin: 0; border-radius: 6px; }
.cd.on { background: rgba(20, 20, 22, .06); }
.wick { position: absolute; left: 50%; width: 1.5px; margin-left: -.75px; background: var(--hf-ink); }
.cbody { position: absolute; left: 14%; right: 14%; border: 1.5px solid var(--hf-ink); border-radius: 2px; min-height: 2px; }
.cbody.up { background: var(--hf-card); } .cbody.dn { background: var(--hf-ink); }
.ska { position: relative; height: 280px; }
.ska span { position: absolute; left: 4px; transform: translateY(50%); font-size: 11px; color: var(--hf-muted); white-space: nowrap; }
.ska .tag { left: 0; font-weight: 700; border-radius: 6px; padding: 2px 6px; color: #fff; }
.tag.last { background: var(--hf-blue); } .tag.now { background: #141416; z-index: 2; }
.xl { position: relative; height: 20px; margin-right: 66px; font-size: 11px; color: var(--hf-muted); }
.xl span { position: absolute; top: 0; transform: translateX(-50%); white-space: nowrap; }
.hf-lg i.lnb { width: 18px; height: 0; border-radius: 0; border-top: 2.5px solid var(--hf-blue); }
.hf-lg i.ptb { width: 9px; height: 9px; border: 2px solid var(--hf-blue); background: var(--hf-card); }
.hf-lg i.cup { width: 10px; height: 14px; border-radius: 2px; border: 1.5px solid var(--hf-ink); background: var(--hf-card); }
.hf-lg i.cdn { width: 10px; height: 14px; border-radius: 2px; background: var(--hf-ink); }
</style>
