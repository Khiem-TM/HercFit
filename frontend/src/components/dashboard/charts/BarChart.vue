<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'

/**
 * Biểu đồ cột (có thể chồng nhiều phần): lưới, dải khuyến nghị hoặc đường mức nền, và hộp chi tiết khi trỏ
 * hay chọn bằng bàn phím. Cột không có dữ liệu chỉ có gạch nhỏ ở đáy.
 */
export interface BarColumn {
  segments: { value: number; color: string }[]
  title: string
  aria: string
  rows: { color: string; value: string; label: string }[]
  total?: string
}

const props = defineProps<{
  columns: BarColumn[]
  max: number
  grid: { value: number; label: string }[]
  xLabels: { index: number; label: string }[]
  legend: { color: string; label: string; kind: 'sq' | 'band' | 'ln' }[]
  band?: { from: number; to: number } | null
  base?: { value: number; label: string } | null
}>()
const emit = defineEmits<{ hover: [index: number] }>()

const hover = shallowRef(-1)
watch(() => props.columns, () => { hover.value = -1 })
watch(hover, index => emit('hover', index))
const pct = (value: number) => `${Math.min(100, (value / props.max) * 100).toFixed(2)}%`
const n = computed(() => props.columns.length)
const tip = computed(() => (hover.value >= 0 ? props.columns[hover.value] : null))
const tipLeft = computed(() => `${(((hover.value + 0.5) / n.value) * 100).toFixed(2)}%`)
const tipShift = computed(() => (hover.value / n.value > 0.55 ? 'translateX(calc(-100% - 16px))' : 'translateX(16px)'))
</script>

<template>
  <div class="barchart">
    <div class="hf-lg legend">
      <span v-for="item in legend" :key="item.label"><i :class="item.kind" :style="item.kind === 'sq' ? { background: item.color } : undefined" />{{ item.label }}</span>
    </div>
    <div class="bcw" @mouseleave="hover = -1">
      <div class="bcy" aria-hidden="true">
        <span v-for="line in grid" :key="line.value" class="hf-mono" :style="{ bottom: pct(line.value) }">{{ line.label }}</span>
      </div>
      <div class="bcp">
        <div v-for="line in grid" :key="line.value" class="bcg" :style="{ bottom: pct(line.value) }" />
        <div v-if="band" class="bcband" :style="{ bottom: pct(band.from), height: pct(band.to - band.from) }" />
        <div v-if="base" class="bcbase" :style="{ bottom: pct(base.value) }"><span>{{ base.label }}</span></div>
        <div class="bccols">
          <button v-for="(column, index) in columns" :key="index" type="button" class="bcc"
                  :class="{ miss: !column.segments.length, hv: hover === index, dimb: hover >= 0 && hover !== index }"
                  :aria-label="column.aria" @mouseenter="hover = index" @focus="hover = index" @click="hover = index">
            <span class="bcbar">
              <i v-for="(segment, part) in column.segments.filter(item => item.value > 0)" :key="part"
                 :style="{ height: pct(segment.value), background: segment.color }" />
            </span>
          </button>
        </div>
        <div v-if="tip" class="bctip" :style="{ left: tipLeft, transform: tipShift }" role="status">
          <div class="hf-mut tip-title">{{ tip.title }}</div>
          <template v-if="tip.rows.length">
            <div v-for="row in tip.rows" :key="row.label" class="tip-row"><span class="swatch" :style="{ background: row.color }" />
              <b>{{ row.value }}</b><span class="hf-mut">{{ row.label }}</span></div>
          </template>
          <div v-else class="tip-row"><span class="swatch" style="background: var(--hf-line-3)" /><b>—</b><span class="hf-mut">Không có dữ liệu</span></div>
          <div v-if="tip.total" class="tip-row total"><span class="swatch" /><b>{{ tip.total }}</b><span class="hf-mut">Tổng</span></div>
        </div>
      </div>
    </div>
    <div class="bcx" aria-hidden="true">
      <span v-for="label in xLabels" :key="label.index" class="hf-mono" :style="{ left: `${(((label.index + 0.5) / n) * 100).toFixed(2)}%` }">{{ label.label }}</span>
    </div>
    <slot />
  </div>
</template>

<style scoped>
.barchart { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.legend { gap: 8px 18px; font-size: 13px; color: var(--hf-sub); margin-bottom: 6px; }
.legend i.sq { width: 14px; height: 14px; border-radius: 4px; }
.legend i.band { width: 14px; height: 14px; border-radius: 4px; border: 1px dashed var(--hf-ghost); background: rgba(20, 20, 22, .06); }
.legend i.ln { width: 18px; height: 0; border-radius: 0; border-top: 2px dashed var(--hf-ink); }
.bcw { display: grid; grid-template-columns: 34px minmax(0, 1fr); gap: 8px; margin-top: 6px; }
.bcy { position: relative; height: 260px; }
.bcy span { position: absolute; right: 0; transform: translateY(50%); font-size: 11px; color: var(--hf-muted); }
.bcp { position: relative; height: 260px; }
.bcg { position: absolute; left: 0; right: 0; border-top: 1px solid var(--hf-line-2); }
.bcband { position: absolute; left: 0; right: 0; background: rgba(20, 20, 22, .05); border-top: 1px dashed var(--hf-line-3); border-bottom: 1px dashed var(--hf-line-3); }
:root.dark .bcband { background: rgba(255, 255, 255, .05); }
.bcbase { position: absolute; left: 0; right: 0; border-top: 1.5px dashed var(--hf-ink); pointer-events: none; z-index: 1; }
.bcbase span { position: absolute; right: 0; top: -22px; font-size: 11px; background: var(--hf-card); padding: 2px 6px; border-radius: 6px; }
.bccols { position: absolute; inset: 0; display: flex; gap: 2px; }
.bcc { position: relative; flex: 1; min-width: 0; height: 100%; border: 0; background: transparent; padding: 0; margin: 0; border-radius: 6px; }
.bcc.hv { background: rgba(20, 20, 22, .05); }
:root.dark .bcc.hv { background: rgba(255, 255, 255, .06); }
.bcc.miss::after { content: ''; position: absolute; bottom: 0; left: 30%; right: 30%; height: 2px; border-radius: 2px; background: var(--hf-line-3); }
.bcbar { position: absolute; bottom: 0; left: 50%; transform: translateX(-50%); width: min(68%, 26px); height: 100%; display: flex; flex-direction: column-reverse; gap: 2px; transition: opacity .15s; }
.bcbar i { display: block; width: 100%; border-radius: 3px; flex: none; }
.bcc.dimb .bcbar { opacity: .4; }
.bctip { position: absolute; top: 0; z-index: 3; background: var(--hf-card); border: 1px solid var(--hf-press); border-radius: 16px; padding: 14px 16px; box-shadow: 0 14px 36px rgba(0, 0, 0, .14); min-width: 200px; pointer-events: none; white-space: nowrap; }
.tip-title { font-size: 13px; margin-bottom: 10px; }
.tip-row { display: flex; align-items: center; gap: 10px; font-size: 14px; padding: 3px 0; }
.tip-row b { min-width: 64px; }
.tip-row.total { padding-top: 8px; margin-top: 6px; border-top: 1px solid var(--hf-line-2); }
.swatch { width: 14px; height: 3px; border-radius: 2px; flex: none; }
.bcx { position: relative; height: 20px; margin: 8px 0 0 42px; font-size: 11px; color: var(--hf-muted); }
.bcx span { position: absolute; top: 0; transform: translateX(-50%); white-space: nowrap; }
@media (max-width: 760px) { .bcy, .bcp { height: 210px; } .bctip { min-width: 170px; padding: 10px 12px; } }
</style>
