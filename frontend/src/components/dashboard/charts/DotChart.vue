<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'

/**
 * Biểu đồ cột chấm: mỗi ngày một cột. `bar` tô từ đáy tới giá trị (năng lượng), `dot` chỉ tô một chấm ở mức
 * giá trị (nhịp tim nghỉ). Ngày trống có gạch nhỏ ở đáy và không bao giờ được vẽ như 0.
 */
export interface DotColumn { value: number | null; readout: string }

const props = defineProps<{
  columns: DotColumn[]
  type: 'bar' | 'dot'
  min: number
  max: number
  rows: number
  yTop: string
  yBottom: string
  xLabels: [string, string, string]
  legend: string
  target?: { value: number; label: string } | null
}>()
const emit = defineEmits<{ hover: [index: number] }>()

const lastWithValue = computed(() => {
  for (let i = props.columns.length - 1; i >= 0; i -= 1) if (props.columns[i].value != null) return i
  return props.columns.length - 1
})
const hover = shallowRef(-1)
const shown = computed(() => (hover.value >= 0 && hover.value < props.columns.length ? hover.value : lastWithValue.value))
watch(() => props.columns, () => { hover.value = -1 })
watch(shown, index => emit('hover', index), { immediate: true })

const size = computed(() => (props.columns.length <= 7 ? 'r7' : props.columns.length <= 31 ? 'r28' : 'r90'))
const cells = computed(() => props.columns.map(column => {
  if (column.value == null) return []
  const span = props.max - props.min || 1
  if (props.type === 'dot') {
    const level = Math.max(0, Math.min(props.rows - 1, Math.round(((column.value - props.min) / span) * (props.rows - 1))))
    return Array.from({ length: props.rows }, (_, row) => props.rows - 1 - row === level)
  }
  const filled = Math.max(1, Math.min(props.rows, Math.round((column.value / props.max) * props.rows)))
  return Array.from({ length: props.rows }, (_, row) => props.rows - 1 - row < filled)
}))
const targetPos = computed(() => (props.target ? `${Math.min(100, (props.target.value / props.max) * 100).toFixed(1)}%` : '0%'))
</script>

<template>
  <div class="dotchart">
    <div class="readout" aria-live="polite"><span class="pin" /><b>{{ columns[shown]?.readout }}</b></div>
    <div class="plot-row">
      <div class="yaxis hf-mut"><span>{{ yTop }}</span><span>{{ yBottom }}</span></div>
      <div class="plot-wrap">
        <div class="plot" :class="size">
          <div v-if="target" class="tline" :style="{ bottom: targetPos }"><span>{{ target.label }}</span></div>
          <button v-for="(column, index) in columns" :key="index" type="button" class="col"
                  :class="{ miss: column.value == null, hv: index === shown && hover >= 0 }"
                  :title="column.readout" :aria-label="column.readout"
                  @mouseenter="hover = index" @focus="hover = index" @click="hover = index">
            <span v-for="(on, row) in cells[index]" :key="row" class="cell"><span class="hf-dt" :class="{ on }" /></span>
          </button>
        </div>
        <div class="xaxis hf-mut"><span>{{ xLabels[0] }}</span><span>{{ xLabels[1] }}</span><span>{{ xLabels[2] }}</span></div>
      </div>
    </div>
    <div class="hf-lg">
      <span><i style="background: var(--hf-acc)" />{{ legend }}</span>
      <span><i class="gap" />Ngày trống = không có dữ liệu (không tính là 0)</span>
    </div>
  </div>
</template>

<style scoped>
.dotchart { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.readout { display: flex; align-items: center; gap: 10px; font-size: 14px; min-height: 28px; }
.pin { width: 10px; height: 10px; border-radius: 50%; background: var(--hf-acc); flex: none; }
.plot-row { display: flex; gap: 10px; min-width: 0; }
.yaxis { display: flex; flex-direction: column; justify-content: space-between; font-size: 11px; text-align: right; width: 44px; flex: none; padding: 3px 0; height: 240px; }
.plot-wrap { flex: 1; min-width: 0; }
.plot { display: flex; gap: 6px; height: 240px; position: relative; }
.col { flex: 1; min-width: 0; display: flex; flex-direction: column; border-radius: 8px; position: relative; border: 0; background: transparent; padding: 3px 0; margin: 0; }
.col.hv { background: var(--hf-fill); }
.col.miss::after { content: ''; position: absolute; bottom: 3px; left: 20%; right: 20%; height: 2px; border-radius: 2px; background: var(--hf-line-3); }
.cell { flex: 1; display: flex; align-items: center; justify-content: center; min-height: 0; }
.r7 .hf-dt { width: 16px; height: 16px; } .r28 .hf-dt { width: 10px; height: 10px; } .r90 .hf-dt { width: 5px; height: 5px; }
.r28 { gap: 3px; } .r90 { gap: 1px; }
.tline { position: absolute; left: 0; right: 0; border-top: 1.5px dashed var(--hf-ink); pointer-events: none; z-index: 1; }
.tline span { position: absolute; right: 0; top: -22px; font-size: 11px; background: var(--hf-card); padding: 2px 6px; border-radius: 6px; color: var(--hf-ink); }
.xaxis { display: flex; justify-content: space-between; font-size: 11px; margin-top: 8px; }
.gap { width: 10px !important; height: 2px !important; border-radius: 2px !important; background: var(--hf-line-3); }
@media (max-width: 760px) {
  .plot, .yaxis { height: 200px; }
  .r28 .hf-dt { width: 6px; height: 6px; } .r90 .hf-dt { width: 3px; height: 3px; } .r7 .hf-dt { width: 12px; height: 12px; }
  .r28 { gap: 1px; } .r90 { gap: 0; }
}
</style>
