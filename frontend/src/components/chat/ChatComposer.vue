<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { ArrowUp, Sparkles, Square } from 'lucide-vue-next'
import type { ChatMode } from '@/types/api'

const props = defineProps<{
  modelValue?: string
  disabled?: boolean
  isStreaming?: boolean
}>()

const emit = defineEmits<{
  (e: 'send', message: string): void
  (e: 'stop'): void
}>()

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

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <!-- Khung nhập tối giản: chỉ ô soạn tin, nút Plan và nút gửi -->
  <div
    class="w-full rounded-[20px] border border-ink/[0.09] bg-panel-raised/90 px-4 pt-3.5 pb-2.5 shadow-[0_24px_64px_rgb(var(--c-shadow)/calc(0.4*var(--shadow-k)))] backdrop-blur-xl transition-colors focus-within:border-ink/[0.2]"
  >
    <textarea
      ref="textareaRef"
      v-model="draft"
      rows="2"
      :disabled="disabled || isStreaming"
      :placeholder="mode === 'plan'
        ? 'Hỏi chuyên sâu, nhờ phân tích chất lượng sống hoặc lập kế hoạch tập...'
        : 'Ghi bữa ăn, buổi tập, cân nặng hoặc xem nhanh tiến độ...'"
      class="w-full resize-none bg-transparent text-sm leading-relaxed text-primary placeholder:text-outline focus:outline-none disabled:opacity-50"
      @input="adjustHeight"
      @keydown="handleKeydown"
    />

    <!-- Thanh công cụ dưới cùng bên trong -->
    <div class="mt-2 flex items-center justify-between gap-2 pt-1">
      <div class="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          :aria-pressed="mode === 'plan'"
          :title="mode === 'plan'
            ? 'Đang ở chế độ Plan: tư vấn chuyên sâu, phân tích và lập kế hoạch. Bấm để về chế độ ghi nhanh.'
            : 'Bật chế độ Plan: tư vấn chuyên sâu, phân tích chất lượng sống và lập kế hoạch tập.'"
          class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition-colors"
          :class="mode === 'plan'
            ? 'border-gold/40 bg-gold/15 text-gold hover:bg-gold/20'
            : 'border-ink/[0.08] bg-ink/[0.03] text-on-surface-variant hover:border-ink/20 hover:bg-ink/[0.07] hover:text-primary'"
          @click="toggleMode"
        >
          <Sparkles class="h-3 w-3" />
          <span>Plan</span>
        </button>
        <span v-if="mode === 'plan'" class="text-[11px] text-outline">Tư vấn chuyên sâu · phân tích · lập kế hoạch</span>
      </div>

      <!-- Nút tròn Gửi / Dừng -->
      <button
        v-if="isStreaming"
        type="button"
        class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-ink/30 bg-ink/10 text-primary transition-all duration-200 hover:scale-105 hover:bg-ink/20"
        title="Dừng trả lời"
        aria-label="Dừng trả lời"
        @click="emit('stop')"
      >
        <Square class="h-3.5 w-3.5 fill-current" />
      </button>
      <button
        v-else
        type="button"
        :disabled="!draft.trim() || disabled"
        class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ink text-paper shadow-[0_0_20px_rgba(255,255,255,0.25)] transition-all duration-200 hover:scale-105 disabled:cursor-not-allowed disabled:bg-ink/15 disabled:text-outline disabled:shadow-none"
        title="Gửi tin nhắn"
        aria-label="Gửi tin nhắn"
        @click="handleSend"
      >
        <ArrowUp class="h-4 w-4 stroke-[2.5]" />
      </button>
    </div>
  </div>
</template>

