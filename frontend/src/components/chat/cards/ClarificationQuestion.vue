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
  <div class="question" role="group" :aria-labelledby="headingId" :data-frame="question.mode">
    <p v-if="question.mode === 'quick_reply'" class="qr-row"><span class="qr">Trả lời nhanh</span></p>
    <h4 :id="headingId" ref="heading" tabindex="-1" class="q">{{ question.question }}</h4>
    <p v-if="showLabel || question.mode === 'multiple'" class="hint">
      <template v-if="showLabel">{{ question.label }} · </template>{{ hint }}<template v-if="question.mode === 'multiple'"> · đã chọn {{ answer.optionIds.length }}</template>
    </p>

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
      <p v-else class="hint">Chọn bài tập ở câu trước để nhập số hiệp.</p>
      <p v-if="setsMessage" class="err" aria-live="polite">{{ setsMessage }}</p>
    </template>

    <!-- Lưới catalog có ảnh -->
    <div v-else-if="withImages" class="tiles">
      <button v-for="option in question.options" :key="option.id" type="button" class="tile" :class="{ on: picked(option.id) }"
              :disabled="disabled || (!picked(option.id) && question.mode === 'multiple' && answer.optionIds.length >= question.max_select)"
              :aria-pressed="picked(option.id)" @click="pick(option.id)">
        <CatalogImage :src="option.image_url" :alt="option.label" :icon="option.ref?.kind === 'exercise' ? 'exercise' : 'food'" rounded="rounded-[10px]" class="img" />
        <b>{{ option.label }}</b>
        <span v-if="option.description" class="m">{{ option.description }}</span>
        <span v-if="picked(option.id)" class="ck"><Check :size="12" :stroke-width="3.5" aria-hidden="true" /></span>
      </button>
    </div>

    <!-- Lựa chọn có mô tả: ô; không mô tả: chip -->
    <div v-else-if="question.options.some(option => option.description)" class="opts">
      <button v-for="option in question.options" :key="option.id" type="button" class="opt" :class="{ on: picked(option.id) }"
              :disabled="disabled" :aria-pressed="picked(option.id)" @click="pick(option.id)">
        <b>{{ option.label }}</b><span>{{ option.description }}</span>
      </button>
    </div>
    <div v-else class="chips">
      <button v-for="option in question.options" :key="option.id" type="button" class="hf-tog"
              :disabled="disabled || (!picked(option.id) && question.mode === 'multiple' && answer.optionIds.length >= question.max_select)"
              :aria-pressed="picked(option.id)" @click="pick(option.id)">
        <Check v-if="picked(option.id) && question.mode === 'multiple'" :size="14" :stroke-width="3" aria-hidden="true" />{{ option.label }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.question { display: flex; flex-direction: column; gap: 12px; }
.q { font-size: 16px; font-weight: 700; line-height: 1.4; margin: 0; color: var(--hf-ink); }
.q:focus { outline: none; }
.hint { font-size: 12px; color: var(--hf-muted); margin: -4px 0 0; }
.err { font-size: 12px; color: var(--hf-bad); margin: 0; }
.qr-row { margin: 0; }
.qr { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 700; color: var(--hf-qr); background: var(--hf-plan-bg); border-radius: 999px; padding: 3px 9px; }
.opts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.opt { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; text-align: left; border: 1px solid var(--hf-line-3); background: var(--hf-card); border-radius: 16px; padding: 12px 14px; min-height: 44px; }
.opt:hover:not(:disabled) { background: var(--hf-fill-3); }
.opt b { font-size: 14px; font-weight: 600; }
.opt span { font-size: 12px; color: var(--hf-muted); line-height: 1.45; }
.opt.on { background: var(--hf-ink); color: var(--hf-on-ink); border-color: var(--hf-ink); }
.opt.on span { color: #C9C9CF; }
.opt:disabled { opacity: .5; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.tiles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.tile { position: relative; border: 1px solid var(--hf-line-3); background: var(--hf-card); border-radius: 16px; padding: 8px; display: flex; flex-direction: column; gap: 6px; text-align: left; }
.tile:hover:not(:disabled) { background: var(--hf-fill-3); }
.tile:disabled { opacity: .45; }
.tile .img { aspect-ratio: 4 / 3; width: 100%; }
.tile b { font-size: 13px; line-height: 1.3; padding: 0 2px; }
.tile .m { font-size: 11px; color: var(--hf-muted); padding: 0 2px 2px; }
.tile.on { border: 2px solid var(--hf-ink); padding: 7px; }
.ck { position: absolute; top: 13px; right: 13px; width: 24px; height: 24px; border-radius: 50%; background: var(--hf-ink); color: var(--hf-on-ink); display: flex; align-items: center; justify-content: center; box-shadow: 0 0 0 2px var(--hf-card); }
@media (min-width: 640px) { .tiles { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 480px) { .opts { grid-template-columns: minmax(0, 1fr); } }
</style>
