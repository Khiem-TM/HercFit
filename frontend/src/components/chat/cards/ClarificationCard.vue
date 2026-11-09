<script setup lang="ts">
import { computed, nextTick, shallowRef, useTemplateRef, watch } from 'vue'
import { ChevronLeft, CircleHelp } from 'lucide-vue-next'
import type { Clarification } from '@/types/api'
import {
  answerText, choosesOnce, composeReply, emptyAnswer, initialAnswer, isAnswered, setRows, visibleIndexes, type Answer,
} from '@/features/chat/clarification'
import ClarificationQuestion from './ClarificationQuestion.vue'

const props = defineProps<{ clarification: Clarification; disabled?: boolean }>()
const emit = defineEmits<{ send: [text: string] }>()

const questions = computed(() => props.clarification.questions)
// Vị trí đi qua các câu hỏi đã hỏi đến lúc này; câu hỏi show_if xuất hiện khi câu trả lời kích hoạt nó được chọn.
const answers = shallowRef<Answer[]>([])
const order = computed(() => visibleIndexes(props.clarification, answers.value))
const total = computed(() => order.value.length)
const single = computed(() => total.value === 1)
// step === total là màn hình xem lại.
const step = shallowRef(0)
const furthest = shallowRef(0)
// Sửa từ màn hình xem lại thì quay về đó thay vì đi lại mọi câu hỏi phía sau.
const editing = shallowRef(false)
const body = useTemplateRef<InstanceType<typeof ClarificationQuestion>>('body')

watch(() => props.clarification, () => {
  step.value = 0
  furthest.value = 0
  editing.value = false
  answers.value = questions.value.map(initialAnswer)
}, { immediate: true })

const reviewing = computed(() => step.value >= total.value)
const index = computed(() => order.value[Math.min(step.value, total.value - 1)])
const current = computed(() => questions.value[index.value])
const rows = (questionIndex: number) => setRows(props.clarification, answers.value, questionIndex)
const currentRows = computed(() => rows(index.value))
const answer = computed({
  get: () => answers.value[index.value] ?? emptyAnswer(),
  set: (value: Answer) => { answers.value = answers.value.map((item, i) => i === index.value ? value : item) },
})
const answered = computed(() => isAnswered(current.value, answer.value, currentRows.value))
const complete = computed(() => order.value.every(i => {
  const value = answers.value[i] ?? emptyAnswer()
  return isAnswered(questions.value[i], value, rows(i)) || (!questions.value[i].required && value.skipped)
}))
// Lựa chọn duy nhất được trả lời ngay khi chạm, như trả lời nhanh; số, chọn nhiều và set cần nút "Gửi".
const showNext = computed(() => !(single.value && choosesOnce(current.value)))

function go(position: number) {
  step.value = position
  furthest.value = Math.min(Math.max(furthest.value, position), total.value)
  if (position < total.value) nextTick(() => body.value?.focus())
}

function send() {
  if (props.disabled) return
  emit('send', composeReply(props.clarification, answers.value))
}

function next() {
  if (props.disabled || !answered.value) return
  // Đọc sau khi trả lời: chọn một lựa chọn có thể làm hiện hoặc ẩn các câu hỏi phía sau.
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

function edit(position: number) {
  editing.value = true
  go(position)
}

function jump(position: number) {
  // Rời màn hình xem lại là một lần sửa; giữa các câu hỏi thì giữ luồng hiện tại.
  if (reviewing.value) editing.value = true
  go(position)
}

const answeredCount = computed(() => order.value.filter(i => shown(i) != null).length)

function shown(questionIndex: number) {
  const value = answers.value[questionIndex]
  const question = questions.value[questionIndex]
  return value && isAnswered(question, value, rows(questionIndex)) ? answerText(question, value, rows(questionIndex)) : null
}
</script>

<template>
  <section class="hf clarify" aria-label="Trả lời câu hỏi của HercFit">
    <div v-if="single" class="eyebrow"><span class="ic"><CircleHelp :size="14" :stroke-width="2.2" aria-hidden="true" /></span>Cần thêm thông tin</div>
    <template v-else>
      <div class="foot">
        <span class="eyebrow" aria-live="polite">{{ reviewing ? 'Kiểm tra lại' : `Câu ${step + 1}/${total}` }}</span>
        <span class="hint">{{ answeredCount }}/{{ total }} câu đã trả lời</span>
      </div>
      <ol class="prog" :style="{ gridTemplateColumns: `repeat(${total}, minmax(0, 1fr))` }">
        <li v-for="(questionIndex, position) in order" :key="questions[questionIndex].id">
          <button
            type="button"
            :disabled="disabled || position > furthest"
            :aria-label="`Câu ${position + 1}: ${questions[questionIndex].label}`"
            :aria-current="position === step ? 'step' : undefined"
            :class="{ on: position <= step || !!shown(questionIndex), skip: answers[questionIndex]?.skipped }"
            @click="jump(position)"
          />
        </li>
      </ol>
    </template>

    <Transition
      mode="out-in"
      enter-active-class="transition duration-fast ease-out motion-reduce:transition-none"
      enter-from-class="translate-x-2 opacity-0"
      leave-active-class="transition duration-instant ease-in motion-reduce:transition-none"
      leave-to-class="-translate-x-2 opacity-0"
    >
      <!-- Xem lại mọi câu trả lời trước khi gửi một tin nhắn -->
      <div v-if="reviewing" key="review">
        <div v-for="(questionIndex, position) in order" :key="questions[questionIndex].id" class="rv">
          <div><span>{{ questions[questionIndex].label }}</span><br><b :class="{ skipped: !shown(questionIndex) }">{{ shown(questionIndex) ?? 'Bỏ qua' }}</b></div>
          <button type="button" class="hf-lnk" :disabled="disabled" @click="edit(position)">Sửa</button>
        </div>
      </div>

      <ClarificationQuestion
        v-else
        ref="body"
        :key="current.id"
        v-model="answer"
        :question="current"
        :rows="currentRows"
        :disabled="disabled"
        :show-label="!single"
        @commit="next"
      />
    </Transition>

    <div class="foot">
      <button v-if="!single && step > 0" type="button" class="hf-btn ghost" :disabled="disabled" @click="back">
        <ChevronLeft :size="16" aria-hidden="true" />Quay lại
      </button>
      <span v-else-if="single && !showNext" class="hint">Chạm để gửi · hoặc trả lời bằng ô chat</span>
      <span v-else />
      <div class="hf-acts">
        <template v-if="!reviewing">
          <button v-if="!single && !current.required" type="button" class="hf-btn" :disabled="disabled" @click="skip">Bỏ qua</button>
          <button v-if="showNext" type="button" class="hf-btn pri" :disabled="disabled || !answered" @click="next">
            {{ single ? 'Gửi' : editing || step === total - 1 ? 'Kiểm tra lại' : 'Tiếp' }}
          </button>
        </template>
        <button v-else type="button" class="hf-btn pri" :disabled="disabled || !complete" @click="send">Gửi câu trả lời</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.clarify {
  background: var(--hf-card); border: 1px solid var(--hf-line); border-radius: 22px; padding: 18px;
  display: flex; flex-direction: column; gap: 14px; box-shadow: 0 6px 20px rgba(0, 0, 0, .05);
}
.eyebrow { display: flex; align-items: center; gap: 8px; font-size: 12px; font-weight: 600; color: var(--hf-muted); }
.ic { width: 26px; height: 26px; border-radius: 8px; background: var(--hf-fill); display: inline-flex; align-items: center; justify-content: center; color: var(--hf-ink); }
.hint { font-size: 12px; color: var(--hf-muted); }
.foot { display: flex; align-items: center; gap: 8px; justify-content: space-between; flex-wrap: wrap; }
.prog { display: grid; gap: 4px; list-style: none; margin: 0; padding: 0; }
.prog button { display: block; width: 100%; height: 4px; border: 0; padding: 0; border-radius: 2px; background: var(--hf-press); }
.prog button.on { background: var(--hf-ink); }
.prog button.skip { background: var(--hf-ghost); }
.prog button:disabled { cursor: default; }
.rv { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 12px; padding: 12px 0; border-top: 1px solid var(--hf-line-2); align-items: start; }
.rv:first-child { border-top: 0; }
.rv span { font-size: 12px; color: var(--hf-muted); }
.rv b { font-size: 14px; font-weight: 600; white-space: pre-line; line-height: 1.5; }
.rv b.skipped { color: var(--hf-faint); font-weight: 500; font-style: italic; }
</style>
