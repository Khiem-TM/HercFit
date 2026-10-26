<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import {
  Activity,
  ArrowUp,
  Dumbbell,
  Sparkles,
  Square,
  Utensils,
} from 'lucide-vue-next'

const props = defineProps<{
  modelValue?: string
  disabled?: boolean
  isStreaming?: boolean
  activeNodeLabel?: string
}>()

const emit = defineEmits<{
  (e: 'send', message: string): void
  (e: 'stop'): void
}>()

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

function insertQuickPrefix(prefix: string): void {
  draft.value = prefix
  nextTick(() => {
    adjustHeight()
    textareaRef.value?.focus()
  })
}
</script>

<template>
  <div
    class="w-full rounded-[24px] border border-white/[0.09] bg-[#1a1a1a]/90 p-1.5 shadow-[0_24px_64px_rgba(0,0,0,0.68)] backdrop-blur-xl transition-colors focus-within:border-white/[0.18]"
  >
    <!-- Outer Layer Top Strip -->
    <div class="flex items-center justify-between px-3.5 py-2 text-xs">
      <div class="flex items-center gap-2 text-on-surface-variant">
        <Sparkles class="h-3.5 w-3.5 text-primary" />
        <span class="font-medium text-primary/90">HercFit Kinetic AI</span>
        <span class="hidden text-outline sm:inline">
          — Trợ lý Dinh dưỡng &amp; Huấn luyện Cá nhân hóa
        </span>
      </div>

      <div class="flex items-center gap-2">
        <span
          v-if="isStreaming"
          class="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/[0.06] px-2.5 py-0.5 font-label-telemetry text-[10px] text-primary"
        >
          <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
          {{ activeNodeLabel || 'Đang xử lý...' }}
        </span>
        <span
          v-else
          class="rounded-full border border-white/[0.08] bg-white/[0.03] px-2.5 py-0.5 font-label-telemetry text-[10px] tracking-wider text-outline"
        >
          OLYMPUS // V2.4
        </span>
      </div>
    </div>

    <!-- Inner Prompt Container -->
    <div
      class="rounded-[18px] border border-white/[0.07] bg-[#101010] px-4 pt-3.5 pb-2.5"
    >
      <textarea
        ref="textareaRef"
        v-model="draft"
        rows="2"
        :disabled="disabled || isStreaming"
        placeholder="Nhập câu hỏi, bữa ăn vừa dùng hoặc lịch tập hôm nay..."
        class="w-full resize-none bg-transparent text-sm leading-relaxed text-primary placeholder:text-outline focus:outline-none disabled:opacity-50"
        @input="adjustHeight"
        @keydown="handleKeydown"
      />

      <!-- Inner Bottom Toolbar -->
      <div class="mt-2 flex items-center justify-between gap-2 pt-1">
        <div class="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.03] px-2.5 py-1 text-[11px] text-on-surface-variant transition-colors hover:border-white/20 hover:bg-white/[0.07] hover:text-primary"
            @click="insertQuickPrefix('Hôm nay mình vừa ăn 1 tô phở bò tái và 2 quả trứng luộc, tính giúp mình calo nhé.')"
          >
            <Utensils class="h-3 w-3 text-outline" />
            <span>Ghi bữa ăn</span>
          </button>

          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.03] px-2.5 py-1 text-[11px] text-on-surface-variant transition-colors hover:border-white/20 hover:bg-white/[0.07] hover:text-primary"
            @click="insertQuickPrefix('Thiết kế giúp mình lịch tập Push Pull Legs 4 buổi/tuần để tăng cơ.')"
          >
            <Dumbbell class="h-3 w-3 text-outline" />
            <span>Lên lịch tập</span>
          </button>

          <button
            type="button"
            class="hidden items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.03] px-2.5 py-1 text-[11px] text-on-surface-variant transition-colors hover:border-white/20 hover:bg-white/[0.07] hover:text-primary sm:inline-flex"
            @click="insertQuickPrefix('Tổng hợp tiến độ dinh dưỡng và luyện tập của mình trong tuần này.')"
          >
            <Activity class="h-3 w-3 text-outline" />
            <span>Tiến độ tuần</span>
          </button>
        </div>

        <!-- Circular Send / Stop Button -->
        <button
          v-if="isStreaming"
          type="button"
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-white/30 bg-white/10 text-primary transition-all duration-200 hover:scale-105 hover:bg-white/20"
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
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-[#0e0e0e] shadow-[0_0_20px_rgba(255,255,255,0.25)] transition-all duration-200 hover:scale-105 disabled:cursor-not-allowed disabled:bg-white/15 disabled:text-outline disabled:shadow-none"
          title="Gửi tin nhắn"
          aria-label="Gửi tin nhắn"
          @click="handleSend"
        >
          <ArrowUp class="h-4 w-4 stroke-[2.5]" />
        </button>
      </div>
    </div>
  </div>
</template>

