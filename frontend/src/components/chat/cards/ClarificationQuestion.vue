<script setup lang="ts">
import { computed, useId, useTemplateRef } from 'vue'
import { Check } from 'lucide-vue-next'
import type { ClarifyQuestion } from '@/types/api'
import { choosesOnce, type Answer, type SetGroup, type SetRow } from '@/features/chat/clarification'
import CatalogImage from './CatalogImage.vue'
import SetsEditor from './SetsEditor.vue'

const props = defineProps<{ question: ClarifyQuestion; rows?: SetRow[]; disabled?: boolean; showLabel?: boolean }>()
/** Fired when the user is done with this question (option tapped or Enter in the text field). */
const emit = defineEmits<{ commit: [] }>()
const answer = defineModel<Answer>({ required: true })

const freeId = useId()
const heading = useTemplateRef<HTMLHeadingElement>('heading')
const multiple = computed(() => props.question.mode === 'multiple')
const withImages = computed(() => props.question.options.some(option => option.image_url || option.ref))
const hint = computed(() => {
  switch (props.question.mode) {
    case 'multiple': return `Chọn tối đa ${props.question.max_select}`
    case 'quick_reply': return 'Trả lời nhanh'
    case 'text': return 'Tự nhập'
    case 'sets': return 'Hiệp × reps × kg'
    default: return 'Chọn một'
  }
})
const picked = (id: string) => answer.value.optionIds.includes(id) && !answer.value.text.trim()

function pick(id: string) {
  if (props.disabled) return
  if (choosesOnce(props.question)) {
    answer.value = { ...answer.value, optionIds: [id], text: '', skipped: false }
    emit('commit')
    return
  }
  const ids = answer.value.optionIds
  const next = ids.includes(id) ? ids.filter(item => item !== id) : ids.length < props.question.max_select ? [...ids, id] : ids
  answer.value = { ...answer.value, optionIds: next, text: '', skipped: false }
}

const editsSets = computed(() => props.question.mode === 'sets' && Boolean(props.rows?.length))

function editSets(sets: Record<string, SetGroup[]>) {
  answer.value = { ...answer.value, sets, text: '', skipped: false }
}

function type(text: string) {
  // Typing replaces a single choice; picked chips of a multiple question are kept in case the text is cleared.
  answer.value = { ...answer.value, optionIds: choosesOnce(props.question) ? [] : answer.value.optionIds, text, skipped: false }
}

defineExpose({ focus: () => heading.value?.focus() })
</script>

<template>
  <div role="group" :aria-labelledby="`${freeId}-q`">
    <p class="font-label-telemetry text-[10px] uppercase tracking-[0.16em] text-on-surface-variant">
      <span v-if="showLabel" class="text-gold">{{ question.label }} · </span>{{ hint }}
    </p>
    <h4 :id="`${freeId}-q`" ref="heading" tabindex="-1" class="mt-2 font-headline-md text-lg leading-snug text-primary focus:outline-none">
      {{ question.question }}
    </h4>

    <!-- Sets × reps × kg for each exercise -->
    <SetsEditor v-if="editsSets" :rows="rows ?? []" :answer="answer" :disabled="disabled" @change="editSets" />

    <!-- Catalog choices with pictures -->
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

    <!-- Chips for quick replies and text choices -->
    <div v-else-if="question.options.length" class="mt-3 flex flex-wrap gap-2">
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

    <div v-if="question.allow_free_text || question.mode === 'text'" class="mt-3">
      <label :for="freeId" class="text-[11px] text-on-surface-variant">
        {{ question.free_text_hint || (editsSets ? 'Hoặc tự nhập (ví dụ: Đẩy ngực 4×8 @ 60kg)' : question.options.length ? 'Hoặc tự nhập câu trả lời' : 'Câu trả lời của bạn') }}
      </label>
      <input
        :id="freeId"
        :value="answer.text"
        type="text"
        :disabled="disabled"
        maxlength="300"
        enterkeyhint="next"
        class="mt-1 min-h-[40px] w-full rounded-lg border border-white/15 bg-[#111111] px-3 text-sm text-primary placeholder:text-outline focus:border-white/35 focus:outline-none"
        @input="type(($event.target as HTMLInputElement).value)"
        @keydown.enter.prevent="emit('commit')"
      />
    </div>
  </div>
</template>
