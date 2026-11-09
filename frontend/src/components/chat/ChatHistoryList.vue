<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, shallowRef, useId, useTemplateRef, watch } from 'vue'
import { Clock3, Ellipsis, MessageSquare, Trash2 } from 'lucide-vue-next'
import type { SessionSummary } from '@/types/api'

const props = defineProps<{
  sessions: SessionSummary[]
  activeSessionId: string
  isStreaming?: boolean
  /** Dải chỉ có biểu tượng cho thanh bên đã thu gọn: chuyển cuộc trò chuyện vẫn chỉ một cú nhấp. */
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
  <nav aria-label="Lịch sử hội thoại" :class="{ 'is-compact': compact }" class="history-scroll" @scroll="closeMenu()">
    <p v-if="sessions.length === 0 && !compact" class="empty">Chưa có cuộc hội thoại nào</p>
    <ul class="list">
      <li v-for="item in sortedSessions" :key="item.session_id" class="history-item">
        <div class="history-row" :class="{ on: item.session_id === activeSessionId || item.session_id === openSessionId }">
          <button
            type="button"
            class="conv"
            :class="{ 'is-compact': compact, 'menu-open': item.session_id === openSessionId }"
            :title="item.title || 'Cuộc trò chuyện mới'"
            :aria-label="compact ? item.title || 'Cuộc trò chuyện mới' : undefined"
            :aria-current="item.session_id === activeSessionId ? 'page' : undefined"
            :disabled="isStreaming"
            @click="emit('select-session', item.session_id)"
          >
            <MessageSquare v-if="compact" :size="16" aria-hidden="true" />
            <template v-else>{{ item.title || 'Cuộc trò chuyện mới' }}</template>
          </button>
          <button
            v-if="!compact"
            type="button"
            class="history-actions"
            :class="{ 'is-open': item.session_id === openSessionId }"
            :aria-label="`Tùy chọn: ${item.title || 'Cuộc trò chuyện mới'}`"
            aria-haspopup="dialog"
            :aria-expanded="item.session_id === openSessionId"
            :aria-controls="item.session_id === openSessionId ? menuId : undefined"
            @click="toggleMenu(item.session_id, $event)"
          >
            <Ellipsis :size="16" aria-hidden="true" />
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
      class="hf history-menu"
      :style="position"
      @keydown.down.prevent="deleteButton?.focus()"
      @keydown.up.prevent="deleteButton?.focus()"
    >
      <div class="menu-head">
        <Clock3 :size="16" class="menu-icon" aria-hidden="true" />
        <div>
          <p class="menu-label">Tương tác cuối</p>
          <time v-if="lastInteraction" :datetime="lastInteraction.iso" class="menu-time">{{ lastInteraction.label }}</time>
          <p v-else class="menu-time">Chưa có thông tin</p>
        </div>
      </div>
      <button ref="deleteButton" type="button" class="menu-delete" :disabled="isStreaming" @click="deleteSession">
        <Trash2 :size="16" aria-hidden="true" />
        Xóa hội thoại
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.history-scroll { flex: 1; min-height: 0; min-width: 0; width: 100%; overflow-x: hidden; overflow-y: auto; scrollbar-width: none; }
.history-scroll::-webkit-scrollbar { display: none; width: 0; height: 0; }
.empty { padding: 24px 12px; text-align: center; font-size: 12px; color: var(--hf-muted); margin: 0; }
.list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.history-item { width: 100%; min-width: 0; content-visibility: auto; contain-intrinsic-block-size: auto 38px; }
.history-row { position: relative; width: 100%; min-width: 0; border-radius: 10px; }
.history-row:hover { background: var(--hf-hover); }
.history-row.on { background: var(--hf-press); }
.conv {
  display: block; width: 100%; min-width: 0; min-height: 38px; padding: 0 12px; border: 0; background: transparent;
  border-radius: 10px; text-align: left; font-size: 14px; color: var(--hf-sub);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.history-row.on .conv { color: var(--hf-ink); font-weight: 500; }
.conv.is-compact { display: flex; align-items: center; justify-content: center; padding: 0; }
.conv:disabled { cursor: wait; }
.conv.menu-open { padding-right: 44px; }
.history-actions {
  position: absolute; right: 3px; top: 3px; width: 32px; height: 32px; border: 0; border-radius: 8px; background: transparent;
  display: flex; align-items: center; justify-content: center; color: var(--hf-muted); opacity: 0; pointer-events: none;
}
.history-actions:hover { background: var(--hf-line); color: var(--hf-ink); }
.history-scroll:not(.is-compact) .history-row:hover > .conv,
.history-scroll:not(.is-compact) .history-row:focus-within > .conv { padding-right: 44px; }
.history-row:hover .history-actions, .history-row:focus-within .history-actions, .history-actions.is-open { opacity: 1; pointer-events: auto; }
@media (hover: none) {
  .history-actions { opacity: 1; pointer-events: auto; }
  .history-scroll:not(.is-compact) .history-row > .conv { padding-right: 44px; }
}
.history-menu {
  position: fixed; z-index: 70; width: 240px; max-width: calc(100vw - 16px); padding: 6px; outline: none;
  background: var(--hf-card); border: 1px solid var(--hf-line); border-radius: 16px; box-shadow: 0 14px 36px rgba(0, 0, 0, .14);
}
.menu-head { display: flex; align-items: flex-start; gap: 10px; padding: 8px 10px 12px; border-bottom: 1px solid var(--hf-line-2); }
.menu-icon { margin-top: 2px; color: var(--hf-muted); flex: none; }
.menu-label { margin: 0; font-size: 12px; color: var(--hf-muted); }
.menu-time { display: block; margin: 4px 0 0; font-size: 13px; color: var(--hf-ink); }
.menu-delete {
  margin-top: 4px; display: flex; width: 100%; align-items: center; gap: 10px; border: 0; background: transparent;
  border-radius: 10px; padding: 0 10px; min-height: 40px; font-size: 13px; font-weight: 500; color: var(--hf-bad); text-align: left;
}
.menu-delete:hover:not(:disabled) { background: var(--hf-err-bg); }
.menu-delete:disabled { opacity: .4; }
</style>
