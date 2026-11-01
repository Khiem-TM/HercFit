<script setup lang="ts">
import { Minus, Plus, Trash2 } from 'lucide-vue-next'
import { defaultGroup, formatGroup, groupError, groupsFor, SET_LIMITS, type Answer, type SetGroup, type SetRow } from '@/features/chat/clarification'
import CatalogImage from './CatalogImage.vue'

/** Sets × reps × kg for each exercise; rows the user has not touched show (and send) the default 3 × 10. */
const props = defineProps<{ rows: SetRow[]; answer: Answer; disabled?: boolean }>()
const emit = defineEmits<{ change: [sets: Record<string, SetGroup[]>] }>()

const LIMITS = SET_LIMITS
const FIELDS = ['sets', 'reps'] as const

function update(row: SetRow, groups: SetGroup[]) {
  emit('change', { ...props.answer.sets, [row.id]: groups })
}

function edit(row: SetRow, index: number, patch: Partial<SetGroup>) {
  update(row, groupsFor(props.answer, row).map((group, i) => i === index ? { ...group, ...patch } : group))
}

function step(row: SetRow, index: number, field: 'sets' | 'reps', delta: number) {
  const [min, max] = LIMITS[field]
  edit(row, index, { [field]: Math.min(max, Math.max(min, groupsFor(props.answer, row)[index][field] + delta)) })
}

function count(row: SetRow, index: number, field: 'sets' | 'reps', raw: string) {
  const [min, max] = LIMITS[field]
  const value = Math.round(Number(raw))
  edit(row, index, { [field]: Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : min })
}

// Blank means no external load; a load outside 0–500 kg is kept and flagged (groupError) rather than dropped.
function load(row: SetRow, index: number, raw: string) {
  const value = Number(raw.replace(',', '.'))
  edit(row, index, { kg: raw.trim() === '' || !Number.isFinite(value) ? null : Math.round(value * 100) / 100 })
}

function add(row: SetRow) {
  // A new group starts from the last one (same load, e.g. a back-off set), which is the common next step.
  const groups = groupsFor(props.answer, row)
  update(row, [...groups, { ...(groups[groups.length - 1] ?? defaultGroup()), sets: 1 }])
}

function remove(row: SetRow, index: number) {
  update(row, groupsFor(props.answer, row).filter((_, i) => i !== index))
}
</script>

<template>
  <ul class="mt-3 space-y-2">
    <li v-for="row in rows" :key="row.id" class="rounded-xl border border-ink/10 bg-ink/[0.03] p-3">
      <div class="flex items-center gap-3">
        <CatalogImage v-if="row.image_url" :src="row.image_url" :alt="row.label" icon="exercise" rounded="rounded-lg" class="h-10 w-10 shrink-0" />
        <span class="min-w-0 flex-1 text-sm font-medium text-primary">{{ row.label }}</span>
        <span class="shrink-0 font-label-telemetry text-[10px] text-on-surface-variant">{{ groupsFor(answer, row).map(formatGroup).join(', ') }}</span>
      </div>

      <div
        v-for="(group, index) in groupsFor(answer, row)"
        :key="index"
        class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-xs text-on-surface-variant"
        role="group"
        :aria-label="`${row.label}, nhóm hiệp ${index + 1}`"
      >
        <template v-for="field in FIELDS" :key="field">
          <span v-if="field === 'reps'" aria-hidden="true">×</span>
          <span class="inline-flex items-center rounded-lg border border-ink/15 bg-sunken">
            <button type="button" :disabled="disabled" class="grid h-8 w-8 place-items-center text-on-surface hover:text-primary disabled:opacity-40"
                    :aria-label="`Giảm ${field === 'sets' ? 'số hiệp' : 'số reps'}`" @click="step(row, index, field, -1)">
              <Minus class="h-3.5 w-3.5" aria-hidden="true" />
            </button>
            <input
              :value="group[field]"
              type="number"
              inputmode="numeric"
              :min="LIMITS[field][0]"
              :max="LIMITS[field][1]"
              :disabled="disabled"
              :aria-label="field === 'sets' ? 'Số hiệp' : 'Số reps mỗi hiệp'"
              class="h-8 w-10 bg-transparent text-center text-sm text-primary [appearance:textfield] focus:outline-none [&::-webkit-inner-spin-button]:appearance-none"
              @change="count(row, index, field, ($event.target as HTMLInputElement).value)"
            />
            <button type="button" :disabled="disabled" class="grid h-8 w-8 place-items-center text-on-surface hover:text-primary disabled:opacity-40"
                    :aria-label="`Tăng ${field === 'sets' ? 'số hiệp' : 'số reps'}`" @click="step(row, index, field, 1)">
              <Plus class="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </span>
          <span>{{ field === 'sets' ? 'hiệp' : 'reps' }}</span>
        </template>
        <span aria-hidden="true">@</span>
        <span class="inline-flex items-center rounded-lg border bg-sunken pr-2" :class="groupError(group) ? 'border-amber-400/60' : 'border-ink/15'">
          <input
            :value="group.kg ?? ''"
            type="text"
            inputmode="decimal"
            placeholder="—"
            :disabled="disabled"
            :aria-invalid="Boolean(groupError(group))"
            aria-label="Mức tạ (kg), bỏ trống nếu không dùng tạ"
            class="h-8 w-14 bg-transparent text-center text-sm text-primary placeholder:text-outline focus:outline-none"
            @change="load(row, index, ($event.target as HTMLInputElement).value)"
          />
          <span>kg</span>
        </span>
        <button v-if="groupsFor(answer, row).length > 1" type="button" :disabled="disabled"
                class="grid h-8 w-8 place-items-center rounded-lg text-outline hover:text-primary disabled:opacity-40"
                :aria-label="`Xoá nhóm hiệp ${index + 1}`" @click="remove(row, index)">
          <Trash2 class="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>

      <button type="button" :disabled="disabled"
              class="mt-2 inline-flex min-h-[32px] items-center gap-1 text-[11px] text-gold hover:text-primary disabled:opacity-40"
              @click="add(row)">
        <Plus class="h-3 w-3" aria-hidden="true" />Thêm nhóm hiệp khác (đổi reps hoặc mức tạ)
      </button>
    </li>
  </ul>
</template>
