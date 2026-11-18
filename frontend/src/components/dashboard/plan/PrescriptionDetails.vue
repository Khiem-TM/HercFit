<script setup lang="ts">
import { computed } from 'vue'
import { duration, setLabel, setDetails, stepMeasure, stepName, targetLabel, type Prescription } from '@/features/plan/exercises'
const props = defineProps<{ prescription: Prescription }>()
const blocks = computed(() => props.prescription.kind === 'ENDURANCE' ? props.prescription.steps.map(s => 'steps' in s ? s : { repeat: 1, steps: [s] }) : [])
const intensity = computed(() => props.prescription.kind === 'SPORT' ? ({ LIGHT: 'Nhẹ', MODERATE: 'Vừa', VIGOROUS: 'Cao' } as Record<string, string>)[props.prescription.intensity || ''] || props.prescription.intensity : '')
const progression = computed(() => {
  if (props.prescription.kind !== 'STRENGTH') return ''
  const p = props.prescription.progression
  if (!p || p.rule === 'NONE') return ''
  return `${p.rule === 'LINEAR' ? 'Tăng tải tuyến tính' : 'Tăng tiến kép'}${p.increment_kg != null ? ` · tăng ${p.increment_kg} kg` : ''}`
})
</script>
<template>
  <div class="prescription">
    <h4>Thông số theo kế hoạch</h4>
    <template v-if="prescription.kind === 'STRENGTH'">
      <div v-for="(set, i) in prescription.sets" :key="i" class="set-row">
        <span class="row-number">{{ i + 1 }}</span><div><strong>{{ setLabel(set) }}</strong><p>{{ setDetails(set) }}</p></div>
      </div>
      <p v-if="progression" class="progression">{{ progression }}</p>
    </template>
    <template v-else-if="prescription.kind === 'ENDURANCE'">
      <div v-for="(block, i) in blocks" :key="i" class="block" :class="{ repeat: block.repeat > 1 }">
        <div v-if="block.repeat > 1" class="repeat-label">Lặp {{ block.repeat }} vòng</div>
        <div v-for="(step, j) in block.steps" :key="j" class="step-row">
          <span class="step-name">{{ stepName(step) }}</span><strong>{{ stepMeasure(step) }}</strong><span class="step-target">{{ targetLabel(step.target) }}</span>
        </div>
      </div>
    </template>
    <div v-else class="sport">
      <strong>{{ duration(prescription.duration_seconds) }}</strong>
      <span v-if="intensity">Cường độ: {{ intensity }}</span><span v-if="prescription.rpe_target != null">RPE {{ prescription.rpe_target }}</span>
    </div>
    <p v-if="prescription.kind === 'STRENGTH'" class="help">RPE: mức gắng sức · RIR: số lần còn có thể tập · 1RM: mức tạ tối đa cho một lần.</p>
  </div>
</template>
<style scoped>
.prescription { min-width: 0; }
h4 { font-weight: 600; margin: 0 0 12px; font-size: 13px; }
.set-row { display: flex; gap: 12px; border-top: 1px solid var(--hf-line-2); padding: 12px 0; }
.row-number { font-family: var(--hf-mono); font-size: 11px; color: var(--hf-muted); padding-top: 2px; }
strong { font-size: 12px; font-family: var(--hf-mono); font-weight: 500; line-height: 1.7; }
p { margin: 4px 0 0; font-size: 12px; color: var(--hf-muted); line-height: 1.7; }
.block { border-top: 1px solid var(--hf-line-2); padding: 4px 0; }
.repeat { background: var(--hf-fill-2); border: 1px solid var(--hf-line); border-radius: 12px; padding: 12px; margin: 8px 0; }
.repeat-label { font-weight: 700; font-size: 12px; margin-bottom: 5px; }
.step-row { display: grid; grid-template-columns: 90px minmax(0, 1fr); gap: 3px 10px; padding: 8px 0; }
.step-name { font-size: 12px; }
.step-target { grid-column: 2; font-size: 11px; color: var(--hf-muted); }
.sport { display: flex; flex-wrap: wrap; gap: 12px; font-size: 13px; }
.help { font-size: 11px; margin-top: 10px; }
</style>
