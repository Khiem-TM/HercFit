<script setup lang="ts">
import { computed, useTemplateRef } from 'vue'
import {
  PanelLeftClose,
  Plus,
} from 'lucide-vue-next'
import type { SessionSummary, UserProfile } from '@/types/api'
import ChatHistoryList from './ChatHistoryList.vue'

const props = defineProps<{
  sessions: SessionSummary[]
  activeSessionId: string
  user: UserProfile | null
  isStreaming?: boolean
}>()

const emit = defineEmits<{
  (e: 'new-chat'): void
  (e: 'select-session', sessionId: string): void
  (e: 'delete-session', sessionId: string): void
  (e: 'open-user-modal'): void
  (e: 'collapse'): void
}>()

const collapseButton = useTemplateRef<HTMLButtonElement>('collapseButton')

defineExpose({
  focusToggle: () => collapseButton.value?.focus(),
})

const userInitials = computed(() => {
  const name = props.user?.fullname || props.user?.email || 'HF'
  const parts = name.trim().split(/\s+/)
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase()
  }
  return name.slice(0, 2).toUpperCase()
})

</script>

<template>
  <aside
    id="chat-sidebar"
    class="relative z-20 flex h-full min-h-0 w-[272px] shrink-0 flex-col overflow-hidden border-r border-white/[0.07] bg-[#0e0e0e] select-none"
  >
    <!-- Top Section: Brand Toggle + New Chat Button -->
    <div class="flex shrink-0 flex-col gap-2 p-3">
      <div class="flex items-center justify-between px-1.5 py-1">
        <a
          href="/"
          class="flex items-center gap-2.5 text-primary transition-opacity hover:opacity-80"
        >
          <span
            class="flex h-7 w-7 items-center justify-center rounded-lg border border-white/15 bg-white/[0.04] font-headline-md text-sm font-bold tracking-wider"
          >
            H
          </span>
          <span class="font-label-code text-[11px] tracking-[0.22em] text-primary">
            HERCFIT // AI
          </span>
        </a>

        <button
          ref="collapseButton"
          type="button"
          class="flex h-8 w-8 items-center justify-center rounded-lg text-outline transition-colors hover:bg-white/[0.06] hover:text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-white/60"
          title="Ẩn thanh bên"
          aria-label="Ẩn thanh bên"
          aria-controls="chat-sidebar"
          aria-expanded="true"
          @click="emit('collapse')"
        >
          <PanelLeftClose class="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      <!-- New Conversation Button -->
      <button
        type="button"
        :disabled="isStreaming"
        class="group flex w-full items-center gap-3 rounded-xl border border-white/[0.09] bg-[#171717] px-3.5 py-2.5 text-left text-sm font-medium text-primary transition-all duration-200 hover:border-white/25 hover:bg-[#202020] disabled:opacity-50"
        title="Cuộc trò chuyện mới"
        @click="emit('new-chat')"
      >
        <Plus class="h-4 w-4 shrink-0 text-primary transition-transform duration-200 group-hover:rotate-90" />
        <span class="truncate">Cuộc trò chuyện mới</span>
      </button>
    </div>

    <ChatHistoryList
      :sessions="sessions"
      :active-session-id="activeSessionId"
      :is-streaming="isStreaming"
      @select-session="emit('select-session', $event)"
      @delete-session="emit('delete-session', $event)"
    />

    <!-- Bottom Section: User Avatar (opens Profile & Settings Modal) -->
    <div class="shrink-0 border-t border-white/[0.07] p-3">
      <button
        type="button"
        class="group flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left transition-colors hover:bg-white/[0.06]"
        title="Hồ sơ cá nhân & Cài đặt"
        @click="emit('open-user-modal')"
      >
        <div class="relative h-9 w-9 shrink-0 overflow-hidden rounded-full border border-white/20 bg-[#1c1b1b]">
          <img
            v-if="user?.avatar_url"
            :src="user.avatar_url"
            :alt="user.fullname"
            class="h-full w-full object-cover"
            referrerpolicy="no-referrer"
          />
          <div
            v-else
            class="flex h-full w-full items-center justify-center font-label-code text-xs font-semibold text-primary"
          >
            {{ userInitials }}
          </div>
          <span
            class="absolute bottom-0 right-0 h-2.5 w-2.5 rounded-full border-2 border-[#0e0e0e] bg-emerald-400"
          />
        </div>

        <div class="min-w-0 flex-1">
          <p class="truncate text-xs font-medium text-primary">
            {{ user?.fullname || 'Vận động viên HercFit' }}
          </p>
          <p class="truncate font-label-telemetry text-[10px] text-outline">
            {{ user?.email || 'Cài đặt & Hồ sơ' }}
          </p>
        </div>
      </button>
    </div>
  </aside>
</template>

