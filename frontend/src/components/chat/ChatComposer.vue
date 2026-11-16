<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { ArrowUp, Mic, Sparkles, Square } from 'lucide-vue-next'
import { useMobile } from '@/composables/useMobile'
import type { VoiceState } from '@/composables/useVoice'
import type { ChatMode } from '@/types/api'

const props = defineProps<{
  modelValue?: string
  disabled?: boolean
  isStreaming?: boolean
  voiceState?: VoiceState
}>()

const emit = defineEmits<{
  (e: 'send', message: string): void
  (e: 'stop'): void
  (e: 'voice'): void
}>()

const { isMobile } = useMobile()

/** Chế độ trò chuyện: người dùng chủ động bật Plan thay vì để trợ lý đoán. */
const mode = defineModel<ChatMode>('mode', { default: 'normal' })

function toggleMode(): void {
  mode.value = mode.value === 'plan' ? 'normal' : 'plan'
  nextTick(() => textareaRef.value?.focus())
}

const draft = ref(props.modelValue || '')
const textareaRef = ref<HTMLTextAreaElement | null>(null)

watch(
  () => props.modelValue,
  (val) => {
    if (typeof val === 'string' && val !== draft.value) {
      draft.value = val
      nextTick(adjustHeight)
    }
  },
)

function adjustHeight(): void {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}

function handleSend(): void {
  const text = draft.value.trim()
  if (!text || props.disabled || props.isStreaming) return
  emit('send', text)
  draft.value = ''
  nextTick(() => {
    if (textareaRef.value) {
      textareaRef.value.style.height = 'auto'
    }
  })
}

/** Điền sẵn một câu mở đầu (chip "Ghi bữa ăn", nút trong Dashboard) để người dùng viết tiếp. */
function prefill(text: string): void {
  draft.value = text
  nextTick(() => {
    adjustHeight()
    const el = textareaRef.value
    if (!el) return
    el.focus()
    el.setSelectionRange(text.length, text.length)
  })
}

defineExpose({ prefill })

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <div class="composer" :class="{ plan: mode === 'plan' }">
    <label for="chat-composer" class="hf-sr">Tin nhắn cho trợ lý</label>
    <textarea
      id="chat-composer"
      ref="textareaRef"
      v-model="draft"
      :rows="isMobile ? 1 : 2"
      :disabled="disabled || isStreaming"
      :placeholder="isStreaming ? 'Trợ lý đang trả lời…' : mode === 'plan'
        ? 'Hỏi chuyên sâu, nhờ phân tích hoặc lập kế hoạch tập…'
        : 'Nhắn cho trợ lý HercFit…'"
      @input="adjustHeight"
      @keydown="handleKeydown"
    />

    <div class="tools">
      <!-- Điện thoại: các chip thành một hàng phía trên, ô nhập một dòng nằm cùng hàng với nút micro và nút gửi. -->
      <div class="chips">
      <button
        type="button"
        class="tchip"
        :class="{ on: mode === 'plan' }"
        :aria-pressed="mode === 'plan'"
        :title="mode === 'plan'
          ? 'Đang ở chế độ Plan: tư vấn chuyên sâu, phân tích và lập kế hoạch. Bấm để về chế độ ghi nhanh.'
          : 'Bật chế độ Plan: tư vấn chuyên sâu, phân tích chất lượng sống và lập kế hoạch tập.'"
        @click="toggleMode"
      >
        <Sparkles :size="14" aria-hidden="true" />Plan
      </button>
      <button type="button" class="tchip" :disabled="disabled || isStreaming" @click="prefill('Ghi bữa ăn: ')">Ghi bữa ăn</button>
      <button type="button" class="tchip" :disabled="disabled || isStreaming" @click="prefill('Ghi buổi tập: ')">Ghi buổi tập</button>
      </div>
      <button
        v-if="voiceState"
        type="button"
        class="mic"
        title="Trò chuyện bằng giọng nói"
        aria-label="Trò chuyện bằng giọng nói"
        @click="emit('voice')"
      >
        <Mic :size="16" aria-hidden="true" />
      </button>
      <button v-if="isStreaming" type="button" class="hf-btn sm pri" title="Dừng trả lời" @click="emit('stop')">
        <Square :size="10" class="fill-current" aria-hidden="true" />Dừng
      </button>
      <button
        v-else
        type="button"
        class="send"
        :disabled="!draft.trim() || disabled"
        title="Gửi tin nhắn"
        aria-label="Gửi tin nhắn"
        @click="handleSend"
      >
        <ArrowUp :size="16" :stroke-width="2.4" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.composer {
  background: var(--hf-card); border: 1px solid var(--hf-line); border-radius: 24px; box-shadow: 0 6px 24px var(--hf-shadow);
  padding: 12px 12px 10px 18px; display: flex; flex-direction: column; gap: 6px; transition: border-color .15s;
}
.composer:focus-within { border-color: var(--hf-line-3); }
.composer.plan { border-color: color-mix(in srgb, var(--hf-plan) 45%, var(--hf-line)); }
textarea {
  border: 0; outline: none; resize: none; font-size: 16px; line-height: 1.5; min-height: 52px; max-height: 160px;
  background: transparent; color: var(--hf-ink); font-family: inherit; width: 100%;
}
/* Khung .composer đã đổi viền khi focus; ô nhập bên trong không vẽ thêm viền focus chung của .hf. */
textarea:focus-visible { outline: none; }
textarea::placeholder { color: var(--hf-faint); }
textarea:disabled { opacity: .6; }
.tools { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.chips { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; flex: 1; min-width: 0; }
.tchip {
  display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--hf-line); background: var(--hf-card);
  border-radius: 999px; padding: 0 12px; min-height: 36px; font-size: 13px; font-weight: 500; color: var(--hf-sub);
}
.tchip:hover:not(:disabled) { background: var(--hf-fill-3); }
.tchip:disabled { opacity: .5; }
.tchip.on { background: var(--hf-plan-bg); color: var(--hf-plan-text); border-color: transparent; }
.send {
  width: 36px; height: 36px; border-radius: 12px; border: 0; background: var(--hf-ink); color: var(--hf-on-ink);
  display: inline-flex; align-items: center; justify-content: center; flex: none;
}
.send:disabled { background: var(--hf-fill); color: var(--hf-ghost); cursor: not-allowed; }
.mic {
  width: 36px; height: 36px; border-radius: 12px; border: 1px solid var(--hf-line); background: var(--hf-card); color: var(--hf-sub);
  display: inline-flex; align-items: center; justify-content: center; flex: none;
}
.mic:hover { background: var(--hf-fill-3); }
@media (max-width: 760px) {
  .composer {
    display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: end; gap: 8px 6px;
    border-radius: 22px; padding: 10px 10px 10px 14px;
  }
  .tools { display: contents; }
  .chips { grid-area: 1 / 1 / 2 / -1; flex-wrap: nowrap; gap: 6px; overflow-x: auto; scrollbar-width: none; }
  .chips::-webkit-scrollbar { display: none; }
  .tchip { flex: none; min-height: 34px; }
  textarea { grid-area: 2 / 1; min-height: 0; max-height: 120px; padding: 7px 0; }
  .mic { grid-area: 2 / 2; }
  .send, .tools > .hf-btn { grid-area: 2 / 3; }
  .send, .mic { width: 38px; height: 38px; border-radius: 50%; }
}
</style>
