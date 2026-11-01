<script setup lang="ts">
import { ref } from 'vue'
import { NotebookPen } from 'lucide-vue-next'
import type { HealthLogKind } from '@/types/api'
import type { HealthApi } from './api'

const props = defineProps<{ api: HealthApi }>()

const kind = ref<HealthLogKind>('hydration')
const amount = ref(250)
const moods = ref<string[]>([])
const valence = ref('PLEASANT')
const symptoms = ref<string[]>([])
const periodStart = ref(new Date().toISOString().slice(0, 10))
const periodEnd = ref('')
const ovulation = ref('NEGATIVE')
const busy = ref(false)
const message = ref<{ tone: 'ok' | 'error'; text: string } | null>(null)

const KINDS: { key: HealthLogKind; label: string }[] = [
  { key: 'hydration', label: 'Nước uống' }, { key: 'mood', label: 'Tâm trạng' }, { key: 'symptoms', label: 'Triệu chứng' },
  { key: 'menstrual-period', label: 'Kỳ kinh' }, { key: 'ovulation-test', label: 'Que thử rụng trứng' },
]
// Values from the Google Health `moods` enum (backend validates the full list).
const MOODS: Record<string, string> = { HAPPY: 'Vui', CALM: 'Bình tĩnh', STRESSED: 'Căng thẳng', ANXIOUS: 'Lo âu',
  SAD: 'Buồn', ENERGIZED: 'Tràn năng lượng', FATIGUED: 'Mệt mỏi' }
const MOOD_OPTIONS = Object.entries(MOODS)
const SYMPTOMS: Record<string, string> = { HEADACHE: 'Đau đầu', FATIGUE: 'Mệt', CRAMPS: 'Chuột rút', NAUSEA: 'Buồn nôn',
  COUGH: 'Ho', FEVER: 'Sốt', BACK_PAIN: 'Đau lưng', INSOMNIA: 'Mất ngủ', DIZZINESS: 'Chóng mặt' }
const OVULATION: Record<string, string> = { NEGATIVE: 'Âm tính', POSITIVE: 'Dương tính',
  LUTEINIZING_HORMONE_SURGE: 'Tăng LH', ESTROGEN_SURGE: 'Tăng estrogen', INDETERMINATE: 'Không rõ' }

function zoned(date: string): string {
  return new Date(`${date}T08:00:00`).toISOString()
}

/** Payload sent for the selected kind (exported in tests). */
function payload(): Record<string, unknown> {
  switch (kind.value) {
    case 'hydration': return { amount_ml: amount.value }
    case 'mood': return { moods: moods.value, valences: [valence.value] }
    case 'symptoms': return { symptoms: symptoms.value }
    case 'menstrual-period': return { started_at: zoned(periodStart.value), ...(periodEnd.value ? { ended_at: zoned(periodEnd.value) } : {}) }
    default: return { result: ovulation.value }
  }
}

async function save(): Promise<void> {
  busy.value = true
  message.value = null
  try {
    await props.api.createLog(kind.value, payload())
    message.value = { tone: 'ok', text: 'Đã lưu nhật ký.' }
    moods.value = []
    symptoms.value = []
  } catch (err) {
    message.value = { tone: 'error', text: err instanceof Error ? err.message : 'Không lưu được.' }
  } finally {
    busy.value = false
  }
}

defineExpose({ payload })
</script>

<template>
  <div class="space-y-3 rounded-2xl border border-ink/[0.08] bg-panel p-4 text-xs">
    <div class="flex items-center gap-2">
      <NotebookPen class="h-4 w-4 text-primary" />
      <h4 class="text-sm font-medium text-primary">Nhật ký sức khoẻ</h4>
    </div>
    <div class="flex flex-wrap gap-1.5">
      <button
        v-for="item in KINDS" :key="item.key" type="button"
        class="rounded-lg px-2 py-1 text-[11px]"
        :class="kind === item.key ? 'bg-ink text-paper font-semibold' : 'border border-ink/20 text-primary'"
        @click="kind = item.key"
      >{{ item.label }}</button>
    </div>

    <label v-if="kind === 'hydration'" class="flex items-center gap-2 text-on-surface-variant">
      <input v-model.number="amount" type="number" min="10" max="5000" step="50" class="w-24 rounded-lg border border-ink/15 bg-transparent px-2 py-1 text-primary" /> ml
    </label>
    <div v-else-if="kind === 'mood'" class="space-y-2">
      <div class="flex flex-wrap gap-2">
        <label v-for="[key, label] in MOOD_OPTIONS" :key="key" class="flex items-center gap-1 text-on-surface-variant">
          <input v-model="moods" type="checkbox" :value="key" class="accent-ink" />{{ label }}
        </label>
      </div>
      <select v-model="valence" class="rounded-lg border border-ink/15 bg-panel px-2 py-1 text-primary">
        <option value="PLEASANT">Dễ chịu</option><option value="BASELINE">Bình thường</option><option value="UNPLEASANT">Khó chịu</option>
      </select>
    </div>
    <div v-else-if="kind === 'symptoms'" class="flex flex-wrap gap-2">
      <label v-for="(label, key) in SYMPTOMS" :key="key" class="flex items-center gap-1 text-on-surface-variant">
        <input v-model="symptoms" type="checkbox" :value="key" class="accent-ink" />{{ label }}
      </label>
    </div>
    <div v-else-if="kind === 'menstrual-period'" class="flex flex-wrap items-center gap-2 text-on-surface-variant">
      Từ <input v-model="periodStart" type="date" class="rounded-lg border border-ink/15 bg-transparent px-2 py-1 text-primary" />
      đến <input v-model="periodEnd" type="date" class="rounded-lg border border-ink/15 bg-transparent px-2 py-1 text-primary" />
    </div>
    <select v-else v-model="ovulation" class="rounded-lg border border-ink/15 bg-panel px-2 py-1 text-primary">
      <option v-for="(label, key) in OVULATION" :key="key" :value="key">{{ label }}</option>
    </select>

    <p v-if="kind !== 'hydration'" class="text-[11px] text-outline">Dữ liệu nhạy cảm: trợ lý chỉ đọc khi bạn cho phép riêng; Google
      chỉ nhận khi bạn bật xuất nhóm này.</p>
    <div class="flex items-center gap-2">
      <button
        type="button"
        :disabled="busy || (kind === 'mood' && !moods.length) || (kind === 'symptoms' && !symptoms.length)"
        class="rounded-xl bg-ink px-3 py-1.5 font-semibold text-paper hover:bg-ink/90 disabled:opacity-40"
        @click="save"
      >Lưu</button>
      <span v-if="message" :class="message.tone === 'ok' ? 'text-emerald-300' : 'text-error'">{{ message.text }}</span>
    </div>
  </div>
</template>
