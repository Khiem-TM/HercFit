<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import {
  Check,
  ExternalLink,
  Loader2,
  ShieldAlert,
  Sparkles,
  X,
} from 'lucide-vue-next'
import type { ChatMessage, PendingAction } from '@/types/api'

const props = defineProps<{
  messages: ChatMessage[]
  isStreaming: boolean
  isConfirming: boolean
  activeNodeLabel: string
  pendingAction: PendingAction | null
}>()

const emit = defineEmits<{
  (e: 'confirm', decision: 'approve' | 'reject'): void
}>()

const containerRef = ref<HTMLElement | null>(null)

function scrollToBottom(): void {
  nextTick(() => {
    const el = containerRef.value
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  })
}

watch(
  () => [props.messages.length, props.isStreaming, props.activeNodeLabel],
  () => scrollToBottom(),
  { deep: true },
)

const TOOL_LABELS: Record<string, string> = {
  create_food: 'Thêm món ăn mới',
  create_exercise: 'Thêm bài tập mới',
  log_meal: 'Ghi nhận nhật ký bữa ăn',
  log_training: 'Ghi nhận buổi tập luyện',
  create_meal_plan: 'Tạo kế hoạch thực đơn',
  create_training_plan: 'Tạo giáo án tập luyện',
  confirm_goal: 'Thiết lập mục tiêu thể hình',
  update_goal: 'Cập nhật mục tiêu',
  record_body_metric: 'Ghi nhận chỉ số cơ thể',
  update_profile: 'Cập nhật hồ sơ cá nhân',
}

function formatToolName(tool: string): string {
  return TOOL_LABELS[tool] || tool
}

function formatPreviewEntries(action: PendingAction): Array<{ key: string; value: string }> {
  const source =
    action.preview && Object.keys(action.preview).length > 0
      ? action.preview
      : action.payload || {}
  return Object.entries(source)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => ({
      key: k,
      value: typeof v === 'object' ? JSON.stringify(v, null, 2) : String(v),
    }))
}
</script>

<template>
  <div
    ref="containerRef"
    class="flex-1 overflow-y-auto px-4 py-6 md:px-8 scrollbar-thin"
  >
    <div class="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <div
        v-for="msg in messages"
        :key="msg.id"
        class="flex w-full"
        :class="msg.role === 'human' ? 'justify-end' : 'justify-start'"
      >
        <!-- Human Message Bubble -->
        <div
          v-if="msg.role === 'human'"
          class="max-w-[82%] rounded-2xl rounded-tr-sm border border-white/10 bg-[#202020] px-4 py-3 text-sm leading-relaxed text-primary shadow-md"
        >
          <p class="whitespace-pre-wrap">{{ msg.content }}</p>
        </div>

        <!-- AI Agent Message Block -->
        <div v-else class="flex w-full max-w-[92%] items-start gap-3.5">
          <!-- Mini Kinetic Orb Avatar -->
          <div
            class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-white/20 shadow-inner"
            style="background: radial-gradient(circle at 30% 30%, #4b4e54 0%, #18191c 70%, #0b0b0c 100%);"
          >
            <Sparkles class="h-3.5 w-3.5 text-primary" />
          </div>

          <div class="min-w-0 flex-1 space-y-3">
            <div class="flex items-center gap-2">
              <span class="font-label-code text-[11px] uppercase tracking-[0.16em] text-primary">
                HERCFIT // OLYMPUS AGENT
              </span>
              <span
                v-if="msg.status === 'pending_confirmation'"
                class="rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 font-label-telemetry text-[10px] text-amber-300"
              >
                CẦN XÁC NHẬN
              </span>
            </div>

            <!-- Message Text -->
            <div
              class="rounded-2xl rounded-tl-sm border border-white/[0.08] bg-[#161616]/90 px-5 py-4 text-sm leading-relaxed text-on-surface"
            >
              <p class="whitespace-pre-wrap">{{ msg.content }}</p>
            </div>

            <!-- Research Sources -->
            <div
              v-if="msg.sources && msg.sources.length > 0"
              class="flex flex-wrap gap-2 pt-1"
            >
              <a
                v-for="(src, idx) in msg.sources"
                :key="idx"
                :href="src.url"
                target="_blank"
                rel="noopener noreferrer"
                class="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] bg-[#141414] px-2.5 py-1 text-xs text-on-surface-variant transition-colors hover:border-white/25 hover:text-primary"
              >
                <ExternalLink class="h-3 w-3 text-outline" />
                <span class="max-w-[220px] truncate">{{ src.title || src.url }}</span>
              </a>
            </div>
          </div>
        </div>
      </div>

      <!-- Active Pending Confirmation Card -->
      <div
        v-if="pendingAction"
        class="ml-11 rounded-2xl border border-white/20 bg-[#181818] p-5 shadow-[0_20px_50px_rgba(0,0,0,0.65)]"
      >
        <div class="flex items-start justify-between gap-3 border-b border-white/[0.08] pb-3.5">
          <div class="flex items-center gap-2.5">
            <div
              class="flex h-8 w-8 items-center justify-center rounded-lg border border-white/15 bg-white/[0.06] text-primary"
            >
              <ShieldAlert class="h-4 w-4" />
            </div>
            <div>
              <p class="font-label-telemetry text-[10px] uppercase tracking-[0.18em] text-outline">
                XÁC NHẬN GHI DỮ LIỆU // REV #{{ pendingAction.revision }}
              </p>
              <h4 class="text-sm font-semibold text-primary">
                {{ formatToolName(pendingAction.tool) }}
              </h4>
            </div>
          </div>
        </div>

        <!-- Preview Key-Value Grid -->
        <div class="my-4 space-y-2 rounded-xl border border-white/[0.06] bg-[#111111] p-3.5">
          <div
            v-for="entry in formatPreviewEntries(pendingAction)"
            :key="entry.key"
            class="flex flex-col justify-between gap-1 border-b border-white/[0.04] pb-2 last:border-b-0 last:pb-0 sm:flex-row sm:items-start"
          >
            <span class="font-label-code text-xs text-outline">{{ entry.key }}</span>
            <pre
              class="max-w-full overflow-x-auto whitespace-pre-wrap font-body-sm text-xs text-primary sm:text-right"
            >{{ entry.value }}</pre>
          </div>
        </div>

        <!-- Approve / Reject Actions -->
        <div class="flex items-center justify-end gap-2.5">
          <button
            type="button"
            :disabled="isConfirming"
            class="inline-flex items-center gap-1.5 rounded-xl border border-white/15 bg-white/[0.04] px-4 py-2 text-xs font-medium text-on-surface-variant transition-colors hover:border-white/30 hover:bg-white/[0.08] hover:text-primary disabled:opacity-50"
            @click="emit('confirm', 'reject')"
          >
            <X class="h-3.5 w-3.5" />
            <span>Huỷ bỏ</span>
          </button>

          <button
            type="button"
            :disabled="isConfirming"
            class="inline-flex items-center gap-1.5 rounded-xl bg-white px-4 py-2 text-xs font-semibold text-[#0e0e0e] shadow-[0_0_20px_rgba(255,255,255,0.2)] transition-transform hover:scale-[1.02] disabled:opacity-50"
            @click="emit('confirm', 'approve')"
          >
            <Loader2 v-if="isConfirming" class="h-3.5 w-3.5 animate-spin" />
            <Check v-else class="h-3.5 w-3.5" />
            <span>Xác nhận &amp; Lưu</span>
          </button>
        </div>
      </div>

      <!-- Streaming Progress Indicator -->
      <div v-if="isStreaming" class="flex items-center gap-3.5">
        <div
          class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-white/20 bg-[#181818]"
        >
          <Loader2 class="h-3.5 w-3.5 animate-spin text-primary" />
        </div>
        <div
          class="inline-flex items-center gap-2 rounded-full border border-white/[0.09] bg-[#161616] px-4 py-2 text-xs text-on-surface-variant"
        >
          <span class="h-2 w-2 animate-ping rounded-full bg-white" />
          <span>{{ activeNodeLabel }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

