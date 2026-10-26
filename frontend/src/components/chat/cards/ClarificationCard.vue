<script setup lang="ts">
import { computed, nextTick, shallowRef, useTemplateRef, watch } from 'vue'
import { ArrowLeft, ArrowRight, PencilLine, Send, SkipForward } from 'lucide-vue-next'
import type { Clarification } from '@/types/api'
import { answerText, choosesOnce, composeReply, emptyAnswer, isAnswered, type Answer } from '@/features/chat/clarification'
import ClarificationQuestion from './ClarificationQuestion.vue'

const props = defineProps<{ clarification: Clarification; disabled?: boolean }>()
const emit = defineEmits<{ send: [text: string] }>()

const questions = computed(() => props.clarification.questions)
const total = computed(() => questions.value.length)
const single = computed(() => total.value === 1)
// step === total is the review screen.
const step = shallowRef(0)
const furthest = shallowRef(0)
const answers = shallowRef<Answer[]>([])
// Editing from the review screen returns there instead of walking every later question again.
const editing = shallowRef(false)
const body = useTemplateRef<InstanceType<typeof ClarificationQuestion>>('body')

watch(() => props.clarification, () => {
  step.value = 0
  furthest.value = 0
  editing.value = false
  answers.value = questions.value.map(() => emptyAnswer())
}, { immediate: true })

const reviewing = computed(() => step.value >= total.value)
const current = computed(() => questions.value[Math.min(step.value, total.value - 1)])
const answer = computed({
  get: () => answers.value[step.value] ?? emptyAnswer(),
  set: (value: Answer) => { answers.value = answers.value.map((item, index) => index === step.value ? value : item) },
})
const answered = computed(() => isAnswered(current.value, answer.value))
const complete = computed(() => questions.value.every((question, index) => {
  const value = answers.value[index] ?? emptyAnswer()
  return isAnswered(question, value) || (!question.required && value.skipped)
}))
// A lone pick-only question answers on tap, like quick replies.
const showNext = computed(() => !(single.value && choosesOnce(current.value) && !current.value.allow_free_text))

function go(index: number) {
  step.value = index
  furthest.value = Math.max(furthest.value, index)
  if (index < total.value) nextTick(() => body.value?.focus())
}

function send() {
  if (props.disabled) return
  emit('send', composeReply(props.clarification, answers.value))
}

function next() {
  if (props.disabled || !answered.value) return
  if (single.value) return send()
  go(editing.value ? total.value : step.value + 1)
}

function skip() {
  if (props.disabled || single.value || current.value.required) return
  answer.value = { ...emptyAnswer(), skipped: true }
  go(editing.value ? total.value : step.value + 1)
}

function back() {
  editing.value = false
  go(Math.max(0, step.value - 1))
}

function edit(index: number) {
  editing.value = true
  go(index)
}

function jump(index: number) {
  // Jumping away from the review screen is an edit; between questions it keeps the current flow.
  if (reviewing.value) editing.value = true
  go(index)
}

function shown(index: number) {
  const value = answers.value[index]
  return value && isAnswered(questions.value[index], value) ? answerText(questions.value[index], value) : null
}
</script>

<template>
  <section class="rounded-2xl border border-[#d4b77d]/35 bg-[#181818] p-4" aria-label="Trả lời câu hỏi của HercFit">
    <!-- Progress: one segment per question, answered ones in gold -->
    <header v-if="!single" class="mb-3 flex items-center gap-3">
      <span class="shrink-0 font-label-telemetry text-[10px] uppercase tracking-[0.16em] text-on-surface-variant" aria-live="polite">
        {{ reviewing ? 'Xem lại' : `Câu ${step + 1}/${total}` }}
      </span>
      <ol class="flex flex-1 gap-1">
        <li v-for="(question, index) in questions" :key="question.id" class="flex-1">
          <button
            type="button"
            :disabled="disabled || index > furthest"
            :aria-label="`Câu ${index + 1}: ${question.label}`"
            :aria-current="index === step ? 'step' : undefined"
            class="block h-1.5 w-full rounded-full transition-colors disabled:cursor-default"
            :class="index === step ? 'bg-primary' : shown(index) ? 'bg-[#d4b77d]' : answers[index]?.skipped ? 'bg-white/30' : 'bg-white/10'"
            @click="jump(index)"
          />
        </li>
      </ol>
    </header>

    <Transition
      mode="out-in"
      enter-active-class="transition duration-150 ease-out motion-reduce:transition-none"
      enter-from-class="translate-x-2 opacity-0"
      leave-active-class="transition duration-100 ease-in motion-reduce:transition-none"
      leave-to-class="-translate-x-2 opacity-0"
    >
      <!-- Review all answers before sending one message -->
      <div v-if="reviewing" key="review">
        <h4 class="font-headline-md text-lg leading-snug text-primary">Kiểm tra lại câu trả lời</h4>
        <ul class="mt-3 divide-y divide-white/[0.06] rounded-xl border border-white/[0.08] bg-white/[0.02]">
          <li v-for="(question, index) in questions" :key="question.id">
            <button
              type="button"
              :disabled="disabled"
              class="flex min-h-[44px] w-full items-start gap-3 px-3 py-2.5 text-left transition-colors hover:bg-white/[0.04] disabled:opacity-50"
              @click="edit(index)"
            >
              <span class="w-32 shrink-0 text-[11px] uppercase tracking-[0.08em] text-on-surface-variant">{{ question.label }}</span>
              <span class="min-w-0 flex-1 text-sm" :class="shown(index) ? 'text-primary' : 'italic text-outline'">
                {{ shown(index) ?? 'Bỏ qua' }}
              </span>
              <PencilLine class="mt-0.5 h-3.5 w-3.5 shrink-0 text-outline" aria-label="Sửa" />
            </button>
          </li>
        </ul>
      </div>

      <ClarificationQuestion
        v-else
        ref="body"
        :key="current.id"
        v-model="answer"
        :question="current"
        :disabled="disabled"
        :show-label="!single"
        @commit="next"
      />
    </Transition>

    <footer class="mt-4 flex flex-wrap items-center gap-2">
      <button
        v-if="!single && step > 0"
        type="button"
        :disabled="disabled"
        class="inline-flex min-h-[40px] items-center gap-1.5 rounded-lg border border-white/15 px-3 text-xs text-on-surface transition-colors hover:border-white/30 disabled:opacity-40"
        @click="back"
      >
        <ArrowLeft class="h-3.5 w-3.5" aria-hidden="true" />Quay lại
      </button>
      <span class="flex-1" />
      <template v-if="!reviewing">
        <button
          v-if="!single && !current.required"
          type="button"
          :disabled="disabled"
          class="inline-flex min-h-[40px] items-center gap-1.5 rounded-lg px-3 text-xs text-on-surface-variant transition-colors hover:text-primary disabled:opacity-40"
          @click="skip"
        >
          <SkipForward class="h-3.5 w-3.5" aria-hidden="true" />Bỏ qua
        </button>
        <button
          v-if="showNext"
          type="button"
          :disabled="disabled || !answered"
          class="inline-flex min-h-[40px] items-center gap-1.5 rounded-lg bg-white px-4 text-xs font-semibold text-[#0e0e0e] disabled:opacity-40"
          @click="next"
        >
          <template v-if="single"><Send class="h-3.5 w-3.5" aria-hidden="true" />Gửi</template>
          <template v-else>{{ editing || step === total - 1 ? 'Xem lại' : 'Tiếp' }}<ArrowRight class="h-3.5 w-3.5" aria-hidden="true" /></template>
        </button>
      </template>
      <button
        v-else
        type="button"
        :disabled="disabled || !complete"
        class="inline-flex min-h-[40px] items-center gap-1.5 rounded-lg bg-white px-4 text-xs font-semibold text-[#0e0e0e] disabled:opacity-40"
        @click="send"
      >
        <Send class="h-3.5 w-3.5" aria-hidden="true" />Gửi câu trả lời
      </button>
    </footer>
  </section>
</template>
