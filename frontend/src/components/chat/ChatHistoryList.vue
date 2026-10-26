<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, shallowRef, useId, useTemplateRef, watch } from 'vue'
import { Clock3, Ellipsis, MessageSquare, Trash2 } from 'lucide-vue-next'
import type { SessionSummary } from '@/types/api'

const props = defineProps<{
  sessions: SessionSummary[]
  activeSessionId: string
  isStreaming?: boolean
  /** Icon-only rail for the collapsed sidebar: switching stays one click away. */
  compact?: boolean
}>()
const emit = defineEmits<{
  'select-session': [sessionId: string]
  'delete-session': [sessionId: string]
}>()

const openSessionId = shallowRef<string | null>(null)
const trigger = shallowRef<HTMLButtonElement | null>(null)
const menu = useTemplateRef<HTMLDivElement>('menu')
const deleteButton = useTemplateRef<HTMLButtonElement>('deleteButton')
const menuId = useId()
const position = shallowRef({ top: '0px', left: '0px' })
const menuSession = computed(() => props.sessions.find(item => item.session_id === openSessionId.value))
const sortedSessions = computed(() => [...props.sessions].sort((a, b) =>
  activityTime(b) - activityTime(a),
))
const lastInteraction = computed(() => {
  const iso = menuSession.value?.last_interaction_at
  const date = iso ? new Date(iso) : null
  if (!date || Number.isNaN(date.getTime())) return null
  return {
    iso: date.toISOString(),
    label: date.toLocaleString('vi-VN', {
      hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric',
    }),
  }
})

function activityTime(session: SessionSummary): number {
  return Date.parse(session.last_interaction_at || session.created_at) || 0
}

function closeMenu(restoreFocus = false): void {
  openSessionId.value = null
  if (restoreFocus) trigger.value?.focus()
}

async function toggleMenu(sessionId: string, event: MouseEvent): Promise<void> {
  if (openSessionId.value === sessionId) {
    closeMenu(true)
    return
  }
  trigger.value = event.currentTarget as HTMLButtonElement
  openSessionId.value = sessionId
  await nextTick()
  if (!menu.value || openSessionId.value !== sessionId || !trigger.value) return
  const anchor = trigger.value.getBoundingClientRect()
  const panel = menu.value.getBoundingClientRect()
  const top = anchor.bottom + 6 + panel.height <= window.innerHeight - 8
    ? anchor.bottom + 6 : anchor.top - panel.height - 6
  position.value = {
    top: `${Math.max(8, top)}px`,
    left: `${Math.max(8, Math.min(anchor.right - panel.width, window.innerWidth - panel.width - 8))}px`,
  }
  menu.value.focus({ preventScroll: true })
}

function dismissOutside(event: Event): void {
  const target = event.target as Node
  if (!menu.value?.contains(target) && !trigger.value?.contains(target)) closeMenu()
}

function onKeydown(event: KeyboardEvent): void {
  if (!openSessionId.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    closeMenu(true)
  }
}

function onViewportChange(): void { closeMenu() }

function deleteSession(): void {
  const sessionId = openSessionId.value
  if (!sessionId || props.isStreaming) return
  closeMenu(true)
  emit('delete-session', sessionId)
}

watch(() => props.activeSessionId, () => closeMenu())
watch(menuSession, session => { if (!session) closeMenu() })
onMounted(() => {
  document.addEventListener('pointerdown', dismissOutside)
  document.addEventListener('focusin', dismissOutside)
  document.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', onViewportChange)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', dismissOutside)
  document.removeEventListener('focusin', dismissOutside)
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', onViewportChange)
})
</script>

<template>
  <nav aria-label="Lịch sử hội thoại" :class="{ 'is-compact': compact }" class="history-scroll min-h-0 min-w-0 w-full flex-1 overflow-x-hidden overflow-y-auto px-2.5 py-3" @scroll="closeMenu()">
    <p v-if="sessions.length === 0 && !compact" class="px-3 py-8 text-center text-xs text-outline">
      Chưa có cuộc hội thoại nào
    </p>
    <ul class="w-full min-w-0 space-y-0.5">
      <li v-for="item in sortedSessions" :key="item.session_id" class="history-item">
        <div
          class="history-row group relative w-full min-w-0 rounded-lg transition-colors"
          :class="item.session_id === activeSessionId || item.session_id === openSessionId
            ? 'bg-white/[0.09] text-primary' : 'text-on-surface-variant hover:bg-white/[0.05] hover:text-primary'"
        >
          <button
            type="button"
            class="block h-10 w-full min-w-0 truncate rounded-lg text-left text-[13px] font-medium focus-visible:outline focus-visible:outline-1 focus-visible:outline-white/60 disabled:cursor-wait"
            :class="compact ? 'flex items-center justify-center' : ['px-3', { 'pr-11': item.session_id === openSessionId }]"
            :title="item.title || 'Cuộc trò chuyện mới'"
            :aria-label="compact ? item.title || 'Cuộc trò chuyện mới' : undefined"
            :aria-current="item.session_id === activeSessionId ? 'page' : undefined"
            :disabled="isStreaming"
            @click="emit('select-session', item.session_id)"
          >
            <MessageSquare v-if="compact" class="h-4 w-4" aria-hidden="true" />
            <template v-else>{{ item.title || 'Cuộc trò chuyện mới' }}</template>
          </button>
          <button
            v-if="!compact"
            type="button"
            class="history-actions absolute right-1 top-1 flex h-8 w-8 items-center justify-center rounded-md text-outline hover:bg-white/10 hover:text-primary focus-visible:outline focus-visible:outline-1 focus-visible:outline-white/60"
            :class="{ 'is-open': item.session_id === openSessionId }"
            :aria-label="`Tùy chọn: ${item.title || 'Cuộc trò chuyện mới'}`"
            aria-haspopup="dialog"
            :aria-expanded="item.session_id === openSessionId"
            :aria-controls="item.session_id === openSessionId ? menuId : undefined"
            @click="toggleMenu(item.session_id, $event)"
          >
            <Ellipsis class="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </li>
    </ul>
  </nav>

  <Teleport to="body">
    <div
      v-if="menuSession"
      :id="menuId"
      ref="menu"
      role="dialog"
      aria-label="Tùy chọn hội thoại"
      tabindex="-1"
      class="fixed z-50 w-60 max-w-[calc(100vw-16px)] rounded-xl border border-white/10 bg-[#202020] p-1.5 font-body-md text-on-surface shadow-xl shadow-black/40 outline-none"
      :style="position"
      @keydown.down.prevent="deleteButton?.focus()"
      @keydown.up.prevent="deleteButton?.focus()"
    >
      <div class="flex items-start gap-2.5 border-b border-white/[0.08] px-2.5 pb-3 pt-2">
        <Clock3 class="mt-0.5 h-4 w-4 shrink-0 text-outline" aria-hidden="true" />
        <div>
          <p class="text-[11px] text-outline">Tương tác cuối</p>
          <time v-if="lastInteraction" :datetime="lastInteraction.iso" class="mt-1 block text-xs leading-5">
            {{ lastInteraction.label }}
          </time>
          <p v-else class="mt-1 text-xs leading-5">Chưa có thông tin</p>
        </div>
      </div>
      <button
        ref="deleteButton"
        type="button"
        :disabled="isStreaming"
        class="mt-1 flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2.5 text-left text-xs text-error hover:bg-error/10 focus-visible:outline focus-visible:outline-1 focus-visible:outline-error disabled:opacity-40"
        @click="deleteSession"
      >
        <Trash2 class="h-4 w-4" aria-hidden="true" />
        Xóa hội thoại
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.history-scroll {
  scrollbar-width: none;
}
.history-scroll::-webkit-scrollbar {
  display: none;
  width: 0;
  height: 0;
}
.history-item {
  width: 100%;
  min-width: 0;
  content-visibility: auto;
  contain-intrinsic-block-size: auto 40px;
}
.history-actions {
  opacity: 0;
  pointer-events: none;
}
.history-scroll:not(.is-compact) .history-row:hover > :first-child,
.history-scroll:not(.is-compact) .history-row:focus-within > :first-child {
  padding-right: 2.75rem;
}
.history-row:hover .history-actions,
.history-row:focus-within .history-actions,
.history-actions.is-open {
  opacity: 1;
  pointer-events: auto;
}
@media (hover: none) {
  .history-actions { opacity: 1; pointer-events: auto; }
  .history-scroll:not(.is-compact) .history-row > :first-child { padding-right: 2.75rem; }
}
@media (prefers-reduced-motion: reduce) {
  .history-row { transition: none; }
}
</style>
