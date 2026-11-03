<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Pencil, RotateCcw, Trash2 } from 'lucide-vue-next'
import CatalogImage from './CatalogImage.vue'
import { setTarget, shortDate, stepBars, stepSummary, WORKOUT } from '@/features/chat/confirmation'
import { draftPayload, entryDrafts, type EntryDraft } from '@/features/plan/model'

/** Lịch tập trên thẻ xác nhận. Người dùng sửa ngày, tên buổi, số hiệp/reps hoặc bỏ buổi/bài trước khi lưu. */
const props = defineProps<{ plan: Record<string, any>; payload: Record<string, any>; disabled?: boolean }>()
const emit = defineEmits<{ change: [payload: Record<string, any> | null] }>()

const VISIBLE = 8
const tone = { easy: 'bg-mist', hard: 'bg-clay', calm: 'bg-stone' }
const editing = ref(false)
const showAll = ref(false)
const name = ref('')
const rows = ref<EntryDraft[]>([])
const original = computed(() => JSON.stringify(draftPayload(props.payload, props.payload.name || '', entryDrafts(props.payload, props.plan))))

function reset() {
  name.value = props.payload.name || props.plan.name || ''
  rows.value = entryDrafts(props.payload, props.plan)
  emit('change', null)
}
watch(() => props.payload, reset, { immediate: true })

/** Mỗi lần sửa dựng lại payload; trùng bản gốc thì thẻ lưu đúng đề xuất ban đầu. */
function changed() {
  const next = draftPayload(props.payload, name.value, rows.value)
  emit('change', JSON.stringify(next) === original.value ? null : next)
}

const visible = computed(() => (editing.value || showAll.value ? rows.value : rows.value.slice(0, VISIBLE)))
const sessions = computed(() => rows.value.filter(row => !row.entry.is_rest).length)
const span = computed(() => {
  const days = rows.value.map(row => row.entry.scheduled_date as string).sort()
  return days.length ? `${days[0]} → ${days[days.length - 1]}` : ''
})

function removeEntry(row: EntryDraft) {
  rows.value = rows.value.filter(item => item !== row)
  changed()
}
function removeItem(row: EntryDraft, index: number) {
  row.items = row.items.filter((_, position) => position !== index)
  changed()
}
function setNumber(target: Record<string, any>, key: string, raw: string, min = 1) {
  const value = Math.round(Number(raw))
  if (!Number.isFinite(value) || value < min) return
  target[key] = value
  if (key === 'reps_min' && target.reps_max != null && target.reps_max < value) target.reps_max = value
  changed()
}
const field = 'block w-full min-w-0 rounded-md border border-ink/15 bg-ink/[0.03] px-2 py-1 text-xs text-primary focus:border-gold/60 focus:outline-none disabled:opacity-50'
const tiny = 'w-11 rounded-md border border-ink/15 bg-ink/[0.03] px-1 py-0.5 text-center text-xs text-primary focus:border-gold/60 focus:outline-none'
</script>

<template>
  <div class="px-5">
    <div class="flex items-center justify-between gap-3 pt-3">
      <p class="font-label-telemetry text-[11px] uppercase tracking-[0.14em] text-on-surface-variant">
        {{ sessions }} buổi tập · {{ span }}
      </p>
      <div class="flex shrink-0 gap-1.5">
        <button v-if="editing" type="button" :disabled="disabled" class="inline-flex items-center gap-1 rounded-full border border-ink/10 px-2.5 py-1 text-[11px] text-on-surface-variant hover:bg-ink/[0.06]" @click="reset">
          <RotateCcw class="h-3 w-3" aria-hidden="true" />Hoàn tác
        </button>
        <button type="button" :disabled="disabled" :aria-pressed="editing" class="inline-flex items-center gap-1 rounded-full border border-gold/30 px-2.5 py-1 text-[11px] text-gold hover:bg-gold/10" @click="editing = !editing">
          <Pencil class="h-3 w-3" aria-hidden="true" />{{ editing ? 'Xong' : 'Sửa lịch' }}
        </button>
      </div>
    </div>

    <label v-if="editing" class="mt-3 block text-[11px] text-on-surface-variant">Tên lịch
      <input v-model="name" :class="field" class="mt-1" maxlength="255" :disabled="disabled" @change="changed">
    </label>

    <ol class="mt-1 divide-y divide-ink/[0.06]">
      <li v-for="row in visible" :key="row.key" class="grid grid-cols-[52px_1fr] gap-3.5 py-3">
        <div class="self-start rounded-lg bg-ink/[0.04] py-1.5 text-center">
          <p class="text-[11px] capitalize text-on-surface-variant">{{ shortDate(row.entry.scheduled_date).dow }}</p>
          <p class="font-label-code text-xs text-primary">{{ shortDate(row.entry.scheduled_date).day }}</p>
        </div>
        <div class="min-w-0">
          <div v-if="editing" class="grid grid-cols-[8.5rem_minmax(0,1fr)_auto] items-center gap-2">
            <input v-model="row.entry.scheduled_date" type="date" :class="field" :disabled="disabled" aria-label="Ngày tập" @change="changed">
            <input v-if="!row.entry.is_rest" v-model="row.entry.label" :class="field" maxlength="255" :disabled="disabled" aria-label="Tên buổi" @change="changed">
            <span v-else class="text-sm text-primary">Nghỉ</span>
            <button type="button" class="shrink-0 rounded-md p-1.5 text-on-surface-variant hover:bg-ink/[0.06] hover:text-primary" :disabled="disabled || rows.length === 1" aria-label="Bỏ buổi này" @click="removeEntry(row)">
              <Trash2 class="h-3.5 w-3.5" />
            </button>
          </div>
          <p v-else class="text-sm font-medium text-primary">{{ row.entry.is_rest ? 'Nghỉ' : row.entry.label }}</p>

          <ul class="mt-1.5 space-y-2">
            <li v-for="(value, index) in row.items" :key="index" class="flex gap-2.5">
              <CatalogImage :src="value.view.exercise_snapshot?.image_url" :alt="value.view.exercise_snapshot?.name_vi || 'Bài tập'" :icon="value.item.prescription?.kind === 'ENDURANCE' ? 'run' : 'exercise'" rounded="rounded-md" class="h-9 w-9 shrink-0" />
              <div class="min-w-0 flex-1 text-xs">
                <div class="flex items-start gap-2">
                  <p class="min-w-0 flex-1 truncate text-primary">{{ value.view.exercise_snapshot?.name_vi || 'Bài tập' }}</p>
                  <button v-if="editing && row.items.length > 1" type="button" class="shrink-0 text-on-surface-variant hover:text-primary" :disabled="disabled" aria-label="Bỏ bài này" @click="removeItem(row, index)">
                    <Trash2 class="h-3 w-3" />
                  </button>
                </div>
                <template v-if="value.item.prescription?.kind === 'STRENGTH'">
                  <template v-for="(target, setIndex) in value.item.prescription.sets" :key="setIndex">
                    <p v-if="editing && target.reps_min != null" class="mt-0.5 flex flex-wrap items-center gap-1 text-on-surface-variant">
                      <input :value="target.count || 1" type="number" min="1" max="20" :class="tiny" :disabled="disabled" aria-label="Số hiệp" @change="setNumber(target, 'count', ($event.target as HTMLInputElement).value)">
                      hiệp ×
                      <input :value="target.reps_min" type="number" min="1" :class="tiny" :disabled="disabled" aria-label="Reps tối thiểu" @change="setNumber(target, 'reps_min', ($event.target as HTMLInputElement).value)">
                      <template v-if="target.reps_max != null">–
                        <input :value="target.reps_max" type="number" :min="target.reps_min" :class="tiny" :disabled="disabled" aria-label="Reps tối đa" @change="setNumber(target, 'reps_max', ($event.target as HTMLInputElement).value, target.reps_min)">
                      </template>
                      reps
                    </p>
                    <p v-else class="text-on-surface-variant">{{ setTarget(target) }}</p>
                  </template>
                </template>
                <template v-else-if="value.item.prescription?.kind === 'ENDURANCE'">
                  <div class="mt-1 flex h-2 gap-px overflow-hidden rounded" aria-hidden="true">
                    <span v-for="(bar, barIndex) in stepBars(value.item.prescription)" :key="barIndex" :class="tone[bar.tone]" :style="{ flexGrow: bar.grow }" :title="bar.label" />
                  </div>
                  <p class="mt-1 text-on-surface-variant">{{ WORKOUT[value.item.prescription.workout_type] }} · {{ stepSummary(value.item.prescription) }}</p>
                </template>
              </div>
            </li>
          </ul>
        </div>
      </li>
    </ol>
    <button v-if="!editing && rows.length > VISIBLE" type="button" class="pb-1 text-xs text-on-surface-variant underline-offset-2 hover:underline" @click="showAll = !showAll">
      {{ showAll ? 'Thu gọn' : `+ ${rows.length - VISIBLE} buổi nữa trong lịch` }}
    </button>
  </div>
</template>
