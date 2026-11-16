<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { AlertCircle, Check, ImageIcon, Sparkles } from 'lucide-vue-next'
import type { ChatMessage, FoodChoice, PendingAction } from '@/types/api'
import HfLogo from '@/components/app/HfLogo.vue'
import CatalogImage from '@/components/chat/cards/CatalogImage.vue'
import ClarificationCard from '@/components/chat/cards/ClarificationCard.vue'
import ConfirmationCard, { type ConfirmExtras } from '@/components/chat/cards/ConfirmationCard.vue'
import FoodGapCard from '@/components/chat/cards/FoodGapCard.vue'
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
  (e: 'resolve-foods', choices: FoodChoice[], text: string): void
  (e: 'ask-in-plan', text: string): void
}>()

/** Câu người dùng vừa hỏi trước một lời mời sang chế độ Plan, để gửi lại đúng câu đó. */
function questionBefore(msg: ChatMessage): string | null {
  const index = props.messages.indexOf(msg)
  for (let i = index - 1; i >= 0; i -= 1) {
    if (props.messages[i].role === 'human') return props.messages[i].content
  }
  return null
}

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

// Câu trả lời đang stream dài dần: cuộn theo, trừ khi người dùng đã kéo lên đọc đoạn trước.
watch(
  () => props.messages[props.messages.length - 1]?.content.length,
  () => {
    const el = containerRef.value
    if (props.isStreaming && el && el.scrollHeight - el.scrollTop - el.clientHeight < 160) scrollToBottom()
  },
)

// Các lựa chọn chỉ còn trả lời được ở lượt agent mới nhất.
const lastMessageId = computed(() => props.messages[props.messages.length - 1]?.id)

// Khi form đang mở, bong bóng chat hiển thị lời dẫn của nó; các câu hỏi nằm trong form.
function asksForm(msg: ChatMessage): boolean {
  return Boolean(msg.clarification?.questions.length) && msg.status === 'needs_input' && msg.id === lastMessageId.value
}

// Thẻ món thiếu (tìm món / tạo món riêng) chỉ trả lời được ở lượt needs_input mới nhất.
function asksFoods(msg: ChatMessage): boolean {
  return Boolean(msg.food_gap?.items.length) && msg.status === 'needs_input' && msg.id === lastMessageId.value
}

function hidesReply(msg: ChatMessage): boolean {
  const intro = msg.clarification?.intro?.trim()
  return asksForm(msg) && Boolean(intro) && msg.content.trim() !== intro
}

function host(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url }
}

/** Hai chữ đầu của tên miền làm "favicon" chữ cho nút nguồn. */
function badge(url: string): string {
  return host(url).replace(/\..*$/, '').slice(0, 2).toUpperCase()
}
</script>

<template>
  <div ref="containerRef" class="thread">
    <div class="col720">
      <template v-for="msg in messages" :key="msg.id">
        <div v-if="msg.role === 'human'" class="um um-enter">{{ msg.content }}</div>

        <div v-else class="am msg-enter">
          <span class="spark" :class="{ live: msg.status === 'streaming' }"><HfLogo :size="28" class="avatar" /></span>
          <div class="body">
            <span v-if="msg.status === 'confirmed' || msg.status === 'rejected'" class="state" :class="msg.status === 'confirmed' ? 'ok' : 'no'">
              <Check v-if="msg.status === 'confirmed'" :size="12" :stroke-width="3" aria-hidden="true" />
              {{ msg.status === 'confirmed' ? 'Đã xác nhận' : 'Đã từ chối' }}
            </span>

            <div v-if="msg.status === 'failed'" class="errb" role="alert">
              <AlertCircle :size="18" aria-hidden="true" />
              <div class="md" v-html="renderMarkdown(msg.content || 'Không hoàn tất được yêu cầu. Bạn có thể thử lại.')" />
            </div>
            <div v-else-if="msg.content || msg.status === 'streaming'" :aria-busy="msg.status === 'streaming'">
              <!-- renderMarkdown escape toàn bộ HTML trước rồi mới sinh các thẻ trong danh sách cho phép cố định. -->
              <div class="md" :class="{ stopped: msg.status === 'stopped' }"
                   v-html="renderMarkdown(asksForm(msg) && msg.clarification?.intro ? msg.clarification.intro : msg.content)" />
              <span v-if="msg.status === 'streaming'" class="caret" aria-hidden="true" />
            </div>
            <!-- Câu hỏi có thể nhắc tới câu trả lời ("trong danh sách trên"), nên nó luôn cách một chạm. -->
            <details v-if="hidesReply(msg)" class="more">
              <summary class="hf-lnk">Xem toàn bộ tin nhắn</summary>
              <div class="md" v-html="renderMarkdown(msg.content)" />
            </details>
            <span v-if="msg.status === 'stopped'" class="state no">Đã dừng</span>

            <!-- Ảnh minh hoạ từ tra cứu (ảnh trên web; chỉ được lưu sau khi xác nhận nhập) -->
            <figure v-if="msg.illustrations && msg.illustrations.length" class="ill">
              <CatalogImage :src="msg.illustrations[0].url" :alt="msg.illustrations[0].description || 'Ảnh minh hoạ'" rounded="rounded-none" class="ill-img" />
              <figcaption><ImageIcon :size="13" aria-hidden="true" />{{ host(msg.illustrations[0].url) }}</figcaption>
            </figure>

            <!-- Các lựa chọn để con người quyết định -->
            <Transition appear enter-active-class="transition duration-base ease-out motion-reduce:transition-none" enter-from-class="translate-y-2 opacity-0">
              <ClarificationCard
                v-if="asksForm(msg) && msg.clarification"
                :clarification="msg.clarification"
                :disabled="isStreaming || isConfirming"
                @send="text => emit('send', text)"
              />
            </Transition>
            <Transition appear enter-active-class="transition duration-base ease-out motion-reduce:transition-none" enter-from-class="translate-y-2 opacity-0">
              <FoodGapCard
                v-if="asksFoods(msg) && msg.food_gap"
                :gap="msg.food_gap"
                :disabled="isStreaming || isConfirming"
                @resolve="(choices, text) => emit('resolve-foods', choices, text)"
              />
            </Transition>

            <!-- Chế độ thường không tư vấn: gửi lại câu hỏi ở chế độ Plan -->
            <div v-if="msg.suggested_mode === 'plan' && msg.id === lastMessageId && questionBefore(msg)" class="plan">
              <span><Sparkles :size="16" aria-hidden="true" />Câu này phù hợp với chế độ Plan</span>
              <button type="button" class="hf-btn sm" :disabled="isStreaming || isConfirming"
                      @click="emit('ask-in-plan', questionBefore(msg) as string)">Hỏi ở chế độ Plan</button>
            </div>

            <!-- Nguồn tra cứu -->
            <div v-if="msg.sources && msg.sources.length > 0" class="srcs">
              <a v-for="(src, idx) in msg.sources" :key="idx" :href="src.url" target="_blank" rel="noopener noreferrer"
                 class="srcb" :title="src.title || src.url">
                <span class="fav">{{ badge(src.url) }}</span><span class="src-name">{{ host(src.url) }}</span>
              </a>
            </div>
          </div>
        </div>
      </template>

      <!-- Thẻ xác nhận đang chờ -->
      <Transition appear enter-active-class="transition duration-base ease-out motion-reduce:transition-none" enter-from-class="translate-y-2 opacity-0">
        <div v-if="pendingAction" :key="pendingAction.action_id" class="pending">
          <ConfirmationCard
            :action="pendingAction"
            :busy="isConfirming"
            @confirm="(decision, extras) => emit('confirm', decision, extras)"
          />
        </div>
      </Transition>

      <!-- Chỉ báo tiến độ trước khi có token câu trả lời -->
      <div v-if="isStreaming && messages[messages.length - 1]?.status !== 'streaming'" class="am msg-enter">
        <span class="spark live"><HfLogo :size="28" class="avatar" /></span>
        <div class="body">
          <Transition mode="out-in" enter-from-class="step-from" leave-to-class="step-to"
                      enter-active-class="step-move" leave-active-class="step-move">
            <span :key="activeNodeLabel" class="think" aria-live="polite">{{ activeNodeLabel || 'Đang suy nghĩ…' }}</span>
          </Transition>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.thread { flex: 1; overflow-y: auto; padding: 32px 24px 8px; }
.col720 { max-width: 720px; margin: 0 auto; width: 100%; display: flex; flex-direction: column; gap: 28px; }
.um {
  align-self: flex-end; max-width: 80%; background: var(--hf-bubble); color: var(--hf-ink); border-radius: 20px;
  padding: 12px 16px; font-size: 15px; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere;
}
.am { display: flex; gap: 14px; align-items: flex-start; font-size: 16px; line-height: 1.7; color: var(--hf-text); }
.spark { margin-top: 2px; }
.body { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 10px; }
.md.stopped { color: var(--hf-sub-2); }
/* Chấm nhịp đập ở cuối câu trả lời đang stream (thay con trỏ khối). */
.caret {
  display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: var(--hf-ink); margin-left: 4px;
  vertical-align: 1px; animation: pulse 1.1s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { transform: scale(.7); opacity: .45; } 50% { transform: scale(1); opacity: 1; } }
/* Vòng sáng xoay quanh avatar khi trợ lý đang suy nghĩ hoặc viết. */
.spark { position: relative; flex: none; display: inline-flex; border-radius: 50%; }
.spark.live::before {
  content: ''; position: absolute; inset: -4px; border-radius: 50%; padding: 2px;
  background: conic-gradient(from 0deg, transparent 0 30%, var(--hf-acc), var(--hf-violet), var(--hf-blue), transparent 85%);
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); -webkit-mask-composite: xor; mask-composite: exclude;
  animation: spin 1.4s linear infinite;
}
/* Nhãn bước đang chạy: chữ có ánh sáng quét qua, đổi bước thì trượt lên. */
.think {
  align-self: flex-start; margin-top: 3px; font-size: 15px; font-weight: 500;
  background: linear-gradient(90deg, var(--hf-faint) 0%, var(--hf-ink) 45%, var(--hf-faint) 90%) 0 0 / 200% 100%;
  -webkit-background-clip: text; background-clip: text; color: transparent; animation: shimmer 1.6s linear infinite;
}
@keyframes shimmer { to { background-position: -200% 0; } }
.step-move { transition: opacity 180ms ease, transform 180ms ease; }
.step-from { opacity: 0; transform: translateY(6px); }
.step-to { opacity: 0; transform: translateY(-6px); }
.state {
  align-self: flex-start; display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; font-weight: 700;
  border-radius: 999px; padding: 3px 10px; line-height: 1.4;
}
.state.ok { background: var(--hf-ok-bg); color: var(--hf-ok-text); }
.state.no { background: var(--hf-fill); color: var(--hf-sub); }
.errb {
  display: flex; gap: 10px; align-items: flex-start; background: var(--hf-err-bg); color: var(--hf-err-text);
  border-radius: 16px; padding: 12px 14px; font-size: 14px; line-height: 1.5;
}
.errb svg { flex: none; margin-top: 2px; }
.more summary { list-style: none; cursor: pointer; color: var(--hf-sub); }
.more .md { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--hf-line-2); }
.ill { margin: 0; border-radius: 16px; overflow: hidden; border: 1px solid var(--hf-press); background: var(--hf-card); max-width: 420px; }
.ill-img { display: block; width: 100%; height: 170px; }
.ill figcaption { display: flex; align-items: center; gap: 6px; padding: 8px 12px; font-size: 12px; color: var(--hf-muted); }
.plan {
  display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;
  background: var(--hf-plan-bg); color: var(--hf-plan-text); border-radius: 16px; padding: 10px 10px 10px 14px; font-size: 13.5px;
}
.plan span { display: inline-flex; gap: 8px; align-items: center; }
.plan .hf-btn { background: var(--hf-plan); color: #fff; }
.srcs { display: flex; flex-wrap: wrap; gap: 8px; }
.srcb {
  display: inline-flex; align-items: center; gap: 8px; border: 1px solid var(--hf-line); background: var(--hf-card);
  border-radius: 999px; padding: 0 12px 0 6px; min-height: 36px; font-size: 12.5px; font-weight: 500;
  text-decoration: none; color: var(--hf-ink); max-width: 260px;
}
.srcb:hover { background: var(--hf-fill-3); }
.src-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fav {
  width: 22px; height: 22px; border-radius: 50%; background: var(--hf-fill); flex: none;
  display: inline-flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 700; color: var(--hf-sub);
}
.pending { margin-left: 42px; }
@keyframes spin { to { transform: rotate(360deg); } }
/* Câu trả lời mới hiện mờ dần một lần; bong bóng được cập nhật (stream -> bản cuối) giữ nguyên node và không chạy lại hiệu ứng. */
.msg-enter { animation: msg-enter 320ms cubic-bezier(.2, .8, .2, 1); }
@keyframes msg-enter { from { opacity: 0; transform: translateY(10px); filter: blur(3px); } to { opacity: 1; transform: none; filter: none; } }
.um-enter { animation: um-enter 260ms cubic-bezier(.2, .8, .2, 1); transform-origin: right bottom; }
@keyframes um-enter { from { opacity: 0; transform: translateY(8px) scale(.97); } to { opacity: 1; transform: none; } }
.md :deep(p) { margin: 0 0 10px; }
.md :deep(p:last-child) { margin-bottom: 0; }
.md :deep(ul) { list-style: disc; padding-left: 20px; margin: 4px 0 10px; }
.md :deep(ol) { list-style: decimal; padding-left: 22px; margin: 4px 0 10px; }
.md :deep(li) { margin: 3px 0; }
.md :deep(strong) { color: var(--hf-ink); font-weight: 700; }
.md :deep(code) { font-family: var(--hf-mono); font-size: 13px; background: var(--hf-fill); padding: 1px 5px; border-radius: 5px; }
.md :deep(a) { color: var(--hf-ink); text-decoration: underline; text-underline-offset: 2px; word-break: break-word; }
/* Điện thoại: câu trả lời và thẻ dùng trọn chiều ngang (dấu HercFit nằm trên một hàng riêng), kéo quá mép không làm trang nảy. */
@media (max-width: 760px) {
  .thread { padding: 12px 14px 8px; overscroll-behavior-y: contain; }
  .col720 { gap: 22px; }
  .um { max-width: 86%; padding: 10px 14px; }
  .am { flex-direction: column; gap: 8px; font-size: 15.5px; line-height: 1.65; }
  .am > .body { width: 100%; }
  .spark { margin-top: 0; }
  .spark .avatar { width: 24px; height: 24px; }
  .pending { margin-left: 0; }
  .plan .hf-btn { flex: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .msg-enter, .um-enter, .caret, .spark.live::before, .think { animation: none; }
  .think { color: var(--hf-sub); background: none; }
  .step-move { transition: none; }
}
</style>
