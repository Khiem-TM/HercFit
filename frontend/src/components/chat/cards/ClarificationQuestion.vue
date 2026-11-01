<script setup lang="ts">
import { computed, useId, useTemplateRef } from 'vue'
import { Check } from 'lucide-vue-next'
import type { ClarifyQuestion } from '@/types/api'
import { answerError, choosesOnce, groupError, groupsFor, type Answer, type SetGroup, type SetRow } from '@/features/chat/clarification'
import CatalogImage from './CatalogImage.vue'
import NumberField from './NumberField.vue'
import SetsEditor from './SetsEditor.vue'

/** Một khung trên thẻ. Mọi câu trả lời đều được chọn trên thẻ (lựa chọn, một con số, các set); không gõ văn bản tự do. */
const props = defineProps<{ question: ClarifyQuestion; rows?: SetRow[]; disabled?: boolean; showLabel?: boolean }>()
/** Phát ra khi người dùng xong câu hỏi này (chạm một lựa chọn, hoặc Enter trong ô nhập số). */
const emit = defineEmits<{ commit: [] }>()
const answer = defineModel<Answer>({ required: true })

const headingId = useId()
const heading = useTemplateRef<HTMLHeadingElement>('heading')
const withImages = computed(() => props.question.options.some(option => option.image_url || option.ref))
const hint = computed(() => {
  const { mode, min_select: least, max_select: most } = props.question
  switch (mode) {
    case 'multiple': return least > 1 ? `Chọn ${least}–${most}` : `Chọn tối đa ${most}`
    case 'quick_reply': return 'Trả lời nhanh'
    case 'number': return `Chọn số · ${props.question.number?.unit ?? ''}`
    case 'sets': return 'Hiệp × reps × kg'
    default: return 'Chọn một'
  }
})
const picked = (id: string) => answer.value.optionIds.includes(id)
// Nhóm set ngoài phạm vi được nêu tên; trình sửa chưa đụng tới thì không hiện thông báo.
const setsMessage = computed(() => props.question.mode === 'sets' && props.rows?.length
  ? props.rows.flatMap(row => groupsFor(answer.value, row)).map(groupError).find(Boolean) ?? null : null)
const emptyRows = computed(() => props.question.mode === 'sets' && !props.rows?.length)

function pick(id: string) {
  if (props.disabled) return
  if (choosesOnce(props.question)) {
    answer.value = { ...answer.value, optionIds: [id], skipped: false }
    emit('commit')
    return
  }
  const ids = answer.value.optionIds
  const next = ids.includes(id) ? ids.filter(item => item !== id) : ids.length < props.question.max_select ? [...ids, id] : ids
  answer.value = { ...answer.value, optionIds: next, skipped: false }
}

function editSets(sets: Record<string, SetGroup[]>) {
  answer.value = { ...answer.value, sets, skipped: false }
}

function editValue(value: number | null) {
  answer.value = { ...answer.value, value, skipped: false }
}

defineExpose({ focus: () => heading.value?.focus(), error: () => answerError(props.question, answer.value, props.rows ?? []) })
</script>

<template>
  <div role="group" :aria-labelledby="headingId" :data-frame="question.mode">
    <p class="font-label-telemetry text-[10px] uppercase tracking-[0.16em] text-on-surface-variant">
      <span v-if="showLabel" class="text-gold">{{ question.label }} · </span>{{ hint }}
    </p>
    <h4 :id="headingId" ref="heading" tabindex="-1" class="mt-2 font-headline-md text-lg leading-snug text-primary focus:outline-none">
      {{ question.question }}
    </h4>

    <!-- Con số kèm đơn vị và khoảng -->
    <NumberField
      v-if="question.mode === 'number' && question.number"
      :frame="question.number"
      :value="answer.value"
      :label="question.label"
      :disabled="disabled"
      @change="editValue"
      @commit="emit('commit')"
    />

    <!-- Sets × reps × kg cho từng bài tập -->
    <template v-else-if="question.mode === 'sets'">
      <SetsEditor v-if="!emptyRows" :rows="rows ?? []" :answer="answer" :disabled="disabled" @change="editSets" />
      <p v-else class="mt-3 text-xs text-on-surface-variant">Chọn bài tập ở câu trước để nhập số hiệp.</p>
      <p v-if="setsMessage" class="mt-2 text-[11px] text-amber-300" aria-live="polite">{{ setsMessage }}</p>
    </template>

    <!-- Lựa chọn catalog có ảnh -->
    <div v-else-if="withImages" class="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
      <button
        v-for="option in question.options"
        :key="option.id"
        type="button"
        :disabled="disabled"
        :aria-pressed="picked(option.id)"
        class="overflow-hidden rounded-xl border-2 bg-ink/[0.03] text-left transition-colors disabled:opacity-50"
        :class="picked(option.id) ? 'border-gold' : 'border-ink/10 hover:border-ink/30'"
        @click="pick(option.id)"
      >
        <CatalogImage :src="option.image_url" :alt="option.label" :icon="option.ref?.kind === 'exercise' ? 'exercise' : 'food'" rounded="rounded-none" class="h-20 w-full" />
        <span class="block px-3 py-2">
          <span class="flex items-center gap-1.5 text-sm font-medium text-primary">
            <Check v-if="picked(option.id)" class="h-3.5 w-3.5 text-gold" aria-hidden="true" />{{ option.label }}
          </span>
          <span v-if="option.description" class="mt-0.5 block text-[11px] text-on-surface-variant">{{ option.description }}</span>
        </span>
      </button>
    </div>

    <!-- Chip cho lựa chọn và trả lời nhanh -->
    <div v-else class="mt-3 flex flex-wrap gap-2">
      <button
        v-for="option in question.options"
        :key="option.id"
        type="button"
        :disabled="disabled"
        :aria-pressed="picked(option.id)"
        class="inline-flex min-h-[40px] items-center gap-1.5 border px-4 text-sm transition-colors disabled:opacity-50"
        :class="[
          picked(option.id) ? 'border-gold bg-gold/15 text-primary' : 'border-ink/15 bg-ink/[0.04] text-on-surface hover:border-ink/30',
          option.description ? 'rounded-xl py-2 text-left' : 'rounded-full',
        ]"
        @click="pick(option.id)"
      >
        <Check v-if="picked(option.id)" class="h-3.5 w-3.5 shrink-0 text-gold" aria-hidden="true" />
        <span>
          {{ option.label }}
          <span v-if="option.description" class="block text-[11px] text-on-surface-variant">{{ option.description }}</span>
        </span>
      </button>
    </div>
  </div>
</template>
