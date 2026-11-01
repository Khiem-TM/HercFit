<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { Check, Minus, Plus } from 'lucide-vue-next'
import type { NumberFrame } from '@/types/api'
import { formatNumber, snap } from '@/features/chat/clarification'

/** Number frame: −/+ within the range, one-tap presets, and a number field checked against the range. */
const props = defineProps<{ frame: NumberFrame; value: number | null; label: string; disabled?: boolean }>()
const emit = defineEmits<{ change: [value: number | null]; commit: [] }>()

const hintId = useId()
// What the field shows. A value outside the range stays visible with its message instead of being clamped.
const draft = ref(props.value === null ? '' : formatNumber(props.value))
watch(() => props.value, value => { draft.value = value === null ? '' : formatNumber(value) })
const presets = computed(() => props.frame.presets ?? [])
const invalid = computed(() => draft.value.trim() !== ''
  && (props.value === null || props.value < props.frame.min || props.value > props.frame.max))
const range = computed(() => `${formatNumber(props.frame.min)}–${formatNumber(props.frame.max)} ${props.frame.unit}`)

function step(direction: 1 | -1) {
  if (props.disabled) return
  const { min, max, step: size } = props.frame
  // The first press starts at the suggested value instead of the bottom of a wide range (30 kg).
  const start = props.value ?? props.frame.default ?? presets.value[0] ?? min
  const next = props.value === null ? start : start + direction * size
  emit('change', snap(props.frame, Math.min(max, Math.max(min, next))))
}

function type(raw: string) {
  draft.value = raw
  const text = raw.trim().replace(',', '.')
  const parsed = Number(text)
  // A typed value keeps its precision (21.5 g with a 5 g stepper); only −/+ move on the step grid.
  emit('change', text === '' || !Number.isFinite(parsed) ? null : Math.round(parsed * 100) / 100)
}

function commit(raw: string) {
  type(raw)
  emit('commit')
}
</script>

<template>
  <div class="mt-3">
    <div class="flex items-center gap-2.5">
      <span class="inline-flex items-center rounded-xl border bg-sunken" :class="invalid ? 'border-amber-400/60' : 'border-ink/15'">
        <button
          type="button"
          :disabled="disabled || (value !== null && value <= frame.min)"
          class="grid h-11 w-11 place-items-center text-on-surface hover:text-primary disabled:opacity-40"
          :aria-label="`Giảm ${label}`"
          @click="step(-1)"
        >
          <Minus class="h-4 w-4" aria-hidden="true" />
        </button>
        <input
          :value="draft"
          type="text"
          inputmode="decimal"
          :disabled="disabled"
          :aria-label="`${label} (${frame.unit})`"
          :aria-invalid="invalid"
          :aria-describedby="hintId"
          placeholder="—"
          class="h-11 w-20 bg-transparent text-center font-label-code text-lg text-primary placeholder:text-outline focus:outline-none"
          @change="type(($event.target as HTMLInputElement).value)"
          @keydown.enter.prevent="commit(($event.target as HTMLInputElement).value)"
        />
        <button
          type="button"
          :disabled="disabled || (value !== null && value >= frame.max)"
          class="grid h-11 w-11 place-items-center text-on-surface hover:text-primary disabled:opacity-40"
          :aria-label="`Tăng ${label}`"
          @click="step(1)"
        >
          <Plus class="h-4 w-4" aria-hidden="true" />
        </button>
      </span>
      <span class="text-sm text-on-surface-variant">{{ frame.unit }}</span>
    </div>

    <div v-if="presets.length" class="mt-3 flex flex-wrap gap-2">
      <button
        v-for="preset in presets"
        :key="preset"
        type="button"
        :disabled="disabled"
        :aria-pressed="value === preset"
        class="inline-flex min-h-[40px] items-center gap-1.5 rounded-full border px-4 text-sm transition-colors disabled:opacity-50"
        :class="value === preset ? 'border-gold bg-gold/15 text-primary' : 'border-ink/15 bg-ink/[0.04] text-on-surface hover:border-ink/30'"
        @click="emit('change', preset)"
      >
        <Check v-if="value === preset" class="h-3.5 w-3.5 shrink-0 text-gold" aria-hidden="true" />{{ formatNumber(preset) }} {{ frame.unit }}
      </button>
    </div>

    <p :id="hintId" class="mt-2 text-[11px]" :class="invalid ? 'text-amber-300' : 'text-on-surface-variant'" aria-live="polite">
      {{ invalid ? `Giá trị phải trong khoảng ${range}` : `Khoảng hợp lệ ${range}` }}
    </p>
  </div>
</template>
