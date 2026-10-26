<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import {
  ExternalLink,
  Loader2,
  Sparkles,
} from 'lucide-vue-next'
import type { ChatMessage, PendingAction } from '@/types/api'
import CatalogImage from '@/components/chat/cards/CatalogImage.vue'
import ClarificationCard from '@/components/chat/cards/ClarificationCard.vue'
import ConfirmationCard, { type ConfirmExtras } from '@/components/chat/cards/ConfirmationCard.vue'
import { renderMarkdown } from '@/features/chat/markdown'

const props = defineProps<{
  messages: ChatMessage[]
  isStreaming: boolean
  isConfirming: boolean
  activeNodeLabel: string
  pendingAction: PendingAction | null
}>()

const emit = defineEmits<{
  (e: 'confirm', decision: 'approve' | 'reject', extras: ConfirmExtras): void
  (e: 'send', text: string): void
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

// Options stay answerable only on the latest agent turn.
const lastMessageId = computed(() => props.messages[props.messages.length - 1]?.id)

// While the form is open the bubble shows its intro; the questions themselves are in the form.
function asksForm(msg: ChatMessage): boolean {
  return Boolean(msg.clarification?.questions.length) && msg.status === 'needs_input' && msg.id === lastMessageId.value
}

function host(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url }
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
        <div v-else class="msg-enter flex w-full max-w-[92%] items-start gap-3.5">
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
              :aria-busy="msg.status === 'streaming'"
            >
              <!-- renderMarkdown escapes all HTML first and emits a fixed tag allowlist. -->
              <div
                class="md"
                v-html="renderMarkdown(asksForm(msg) && msg.clarification?.intro ? msg.clarification.intro : msg.content)"
              />
              <span v-if="msg.status === 'streaming'" class="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-white/70 align-middle" aria-hidden="true" />
              <p v-if="msg.status === 'stopped'" class="mt-2 text-xs text-outline">Đã dừng theo yêu cầu.</p>
            </div>

            <!-- Research illustration (web picture; stored only after a confirmed import) -->
            <figure v-if="msg.illustrations && msg.illustrations.length" class="max-w-xs overflow-hidden rounded-xl border border-white/[0.08] bg-[#141414]">
              <CatalogImage :src="msg.illustrations[0].url" :alt="msg.illustrations[0].description || 'Ảnh minh hoạ'" rounded="rounded-none" class="aspect-[4/3] w-full" />
              <figcaption class="px-3 py-2 text-[11px] text-outline">Ảnh minh hoạ · {{ host(msg.illustrations[0].url) }}</figcaption>
            </figure>

            <!-- Human-in-the-loop options -->
            <Transition appear enter-active-class="transition duration-200 ease-out motion-reduce:transition-none" enter-from-class="translate-y-1 opacity-0">
              <ClarificationCard
                v-if="asksForm(msg) && msg.clarification"
                :clarification="msg.clarification"
                :disabled="isStreaming || isConfirming"
                @send="text => emit('send', text)"
              />
            </Transition>

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
      <Transition appear enter-active-class="transition duration-200 ease-out motion-reduce:transition-none" enter-from-class="translate-y-1 opacity-0">
        <div v-if="pendingAction" :key="pendingAction.action_id" class="ml-11">
          <ConfirmationCard
            :action="pendingAction"
            :busy="isConfirming"
            @confirm="(decision, extras) => emit('confirm', decision, extras)"
          />
        </div>
      </Transition>

      <!-- Streaming Progress Indicator (hidden once answer tokens are visible) -->
      <div v-if="isStreaming && messages[messages.length - 1]?.status !== 'streaming'" class="flex items-center gap-3.5">
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


<style scoped>
/* New replies fade in once; an updated (streamed -> final) bubble keeps its node and does not replay this. */
.msg-enter { animation: msg-enter 180ms ease-out; }
@keyframes msg-enter { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) { .msg-enter { animation: none; } }
.md :deep(p) { margin: 0 0 0.6rem; }
.md :deep(p:last-child) { margin-bottom: 0; }
.md :deep(ul) { list-style: disc; padding-left: 1.25rem; margin: 0.25rem 0 0.6rem; }
.md :deep(ol) { list-style: decimal; padding-left: 1.4rem; margin: 0.25rem 0 0.6rem; }
.md :deep(li) { margin: 0.15rem 0; }
.md :deep(strong) { color: rgb(255 255 255 / 0.95); font-weight: 600; }
.md :deep(code) { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.85em; background: rgb(255 255 255 / 0.08); padding: 0.05rem 0.3rem; border-radius: 0.3rem; }
.md :deep(a) { text-decoration: underline; text-underline-offset: 2px; word-break: break-word; }
</style>
