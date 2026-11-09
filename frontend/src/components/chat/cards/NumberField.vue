<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { AlertCircle, Minus, Plus } from 'lucide-vue-next'
import type { NumberFrame } from '@/types/api'
import { formatNumber, snap } from '@/features/chat/clarification'

/** Khung nhập số: −/+ trong khoảng, giá trị có sẵn một chạm, và ô nhập số được kiểm tra theo khoảng. */
const props = defineProps<{ frame: NumberFrame; value: number | null; label: string; disabled?: boolean }>()
const emit = defineEmits<{ change: [value: number | null]; commit: [] }>()

const hintId = useId()
// Những gì ô hiển thị. Giá trị ngoài khoảng vẫn hiển thị kèm thông báo thay vì bị kẹp lại.
const draft = ref(props.value === null ? '' : formatNumber(props.value))
watch(() => props.value, value => { draft.value = value === null ? '' : formatNumber(value) })
const presets = computed(() => props.frame.presets ?? [])
const invalid = computed(() => draft.value.trim() !== ''
  && (props.value === null || props.value < props.frame.min || props.value > props.frame.max))
const range = computed(() => `${formatNumber(props.frame.min)}–${formatNumber(props.frame.max)} ${props.frame.unit}`)

function step(direction: 1 | -1) {
  if (props.disabled) return
  const { min, max, step: size } = props.frame
  // Lần nhấn đầu bắt đầu từ giá trị gợi ý thay vì từ đáy của một khoảng rộng (30 kg).
  const start = props.value ?? props.frame.default ?? presets.value[0] ?? min
  const next = props.value === null ? start : start + direction * size
  emit('change', snap(props.frame, Math.min(max, Math.max(min, next))))
}

function type(raw: string) {
  draft.value = raw
  const text = raw.trim().replace(',', '.')
  const parsed = Number(text)
  // Giá trị gõ vào giữ độ chính xác (21.5 g với bước 5 g); chỉ −/+ mới di chuyển theo lưới bước.
  emit('change', text === '' || !Number.isFinite(parsed) ? null : Math.round(parsed * 100) / 100)
}

function commit(raw: string) {
  type(raw)
  emit('commit')
}
</script>

<template>
  <div class="numf">
    <div class="num">
      <button type="button" class="rb" :disabled="disabled || (value !== null && value <= frame.min)" :aria-label="`Giảm ${label}`" @click="step(-1)">
        <Minus :size="18" :stroke-width="2.2" aria-hidden="true" />
      </button>
      <label class="numin" :class="{ bad: invalid }">
        <input :value="draft" type="text" inputmode="decimal" :disabled="disabled" :aria-label="`${label} (${frame.unit})`"
               :aria-invalid="invalid" :aria-describedby="hintId" placeholder="—"
               @change="type(($event.target as HTMLInputElement).value)"
               @keydown.enter.prevent="commit(($event.target as HTMLInputElement).value)" />
        <span class="unit">{{ frame.unit }}</span>
      </label>
      <button type="button" class="rb" :disabled="disabled || (value !== null && value >= frame.max)" :aria-label="`Tăng ${label}`" @click="step(1)">
        <Plus :size="18" :stroke-width="2.2" aria-hidden="true" />
      </button>
    </div>
    <div v-if="presets.length" class="chips">
      <button v-for="preset in presets" :key="preset" type="button" class="hf-tog" :disabled="disabled" :aria-pressed="value === preset"
              @click="emit('change', preset)">{{ formatNumber(preset) }}</button>
    </div>
    <p v-if="invalid" :id="hintId" class="err" aria-live="polite"><AlertCircle :size="14" :stroke-width="2.2" aria-hidden="true" />Giá trị phải từ {{ range }}.</p>
    <p v-else :id="hintId" class="hint">Khoảng hợp lệ: {{ range }}</p>
  </div>
</template>

<style scoped>
.numf { display: flex; flex-direction: column; gap: 12px; }
.num { display: flex; align-items: center; gap: 10px; }
.rb { width: 48px; height: 48px; border-radius: 50%; border: 1px solid var(--hf-line-3); background: var(--hf-card); color: var(--hf-ink); display: inline-flex; align-items: center; justify-content: center; flex: none; }
.rb:hover:not(:disabled) { background: var(--hf-fill-3); }
.rb:disabled { opacity: .4; }
.numin { flex: 1; height: 60px; border: 1px solid var(--hf-line-3); border-radius: 18px; display: flex; align-items: center; padding: 0 18px; gap: 8px; background: var(--hf-card); }
.numin:focus-within { border-color: var(--hf-ink); }
.numin input { border: 0; outline: none; font-size: 28px; font-weight: 700; width: 100%; background: transparent; min-width: 0; color: var(--hf-ink); font-family: inherit; }
.numin.bad { border-color: var(--hf-bad); box-shadow: 0 0 0 3px var(--hf-err-bg); }
.unit { font-size: 15px; color: var(--hf-muted); font-weight: 600; white-space: nowrap; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.hint { font-size: 12px; color: var(--hf-muted); margin: 0; }
.err { font-size: 12px; color: var(--hf-bad); display: flex; gap: 6px; align-items: center; margin: 0; }
</style>
