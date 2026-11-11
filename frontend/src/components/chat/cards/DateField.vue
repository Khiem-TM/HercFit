<script setup lang="ts">
import { computed, useId } from 'vue'
import { AlertCircle, CalendarDays } from 'lucide-vue-next'
import type { DateFrame } from '@/types/api'
import { formatDay, isDay } from '@/features/chat/clarification'

/** Khung chọn ngày: mốc gợi ý một chạm và lịch của trình duyệt, giới hạn trong khoảng do agent dựng. */
const props = defineProps<{ frame: DateFrame; value: string | null; label: string; disabled?: boolean }>()
const emit = defineEmits<{ change: [value: string | null]; commit: [] }>()

const hintId = useId()
const presets = computed(() => props.frame.presets ?? [])
const range = computed(() => `${formatDay(props.frame.min)} – ${formatDay(props.frame.max)}`)
const invalid = computed(() => props.value !== null
  && (!isDay(props.value) || props.value < props.frame.min || props.value > props.frame.max))

function pickDay(raw: string) {
  emit('change', raw ? raw : null)
}
</script>

<template>
  <div class="datef">
    <div v-if="presets.length" class="chips">
      <button v-for="preset in presets" :key="preset.value" type="button" class="hf-tog" :disabled="disabled"
              :aria-pressed="value === preset.value" @click="emit('change', preset.value)">{{ preset.label }}</button>
    </div>
    <label class="day" :class="{ bad: invalid }">
      <CalendarDays :size="20" :stroke-width="2" aria-hidden="true" class="ic" />
      <input :value="value ?? ''" type="date" :min="frame.min" :max="frame.max" :disabled="disabled"
             :aria-label="label" :aria-invalid="invalid" :aria-describedby="hintId"
             @change="pickDay(($event.target as HTMLInputElement).value)"
             @keydown.enter.prevent="pickDay(($event.target as HTMLInputElement).value); emit('commit')" />
      <span v-if="value && !invalid" class="picked">{{ formatDay(value) }}</span>
    </label>
    <p v-if="invalid" :id="hintId" class="err" aria-live="polite"><AlertCircle :size="14" :stroke-width="2.2" aria-hidden="true" />Ngày phải trong khoảng {{ range }}.</p>
    <p v-else :id="hintId" class="hint">Chọn một mốc hoặc một ngày trên lịch · {{ range }}</p>
  </div>
</template>

<style scoped>
.datef { display: flex; flex-direction: column; gap: 12px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.day { height: 60px; border: 1px solid var(--hf-line-3); border-radius: 18px; display: flex; align-items: center; padding: 0 18px; gap: 10px; background: var(--hf-card); }
.day:focus-within { border-color: var(--hf-ink); }
.day.bad { border-color: var(--hf-bad); box-shadow: 0 0 0 3px var(--hf-err-bg); }
.day .ic { color: var(--hf-muted); flex: none; }
.day input { border: 0; outline: none; font-size: 18px; font-weight: 600; flex: 1; min-width: 0; background: transparent; color: var(--hf-ink); font-family: inherit; }
.picked { font-size: 13px; color: var(--hf-muted); font-weight: 600; white-space: nowrap; }
.hint { font-size: 12px; color: var(--hf-muted); margin: 0; }
.err { font-size: 12px; color: var(--hf-bad); display: flex; gap: 6px; align-items: center; margin: 0; }
</style>
