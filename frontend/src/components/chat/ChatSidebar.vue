<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Trash2,
} from 'lucide-vue-next'
import type { SessionSummary, UserProfile } from '@/types/api'

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
}>()

const isCollapsed = ref(false)

const userInitials = computed(() => {
  const name = props.user?.fullname || props.user?.email || 'HF'
  const parts = name.trim().split(/\s+/)
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase()
  }
  return name.slice(0, 2).toUpperCase()
})

function formatRelativeDate(iso: string): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' })
}
</script>

<template>
  <aside
    class="relative z-20 flex h-full flex-col justify-between border-r border-white/[0.07] bg-[#0e0e0e] transition-all duration-300 select-none"
    :class="isCollapsed ? 'w-[68px]' : 'w-[272px]'"
  >
    <!-- Top Section: Brand Toggle + New Chat Button -->
    <div class="flex flex-col gap-2 p-3">
      <div
        class="flex items-center"
        :class="isCollapsed ? 'justify-center' : 'justify-between px-1.5 py-1'"
      >
        <a
          v-if="!isCollapsed"
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
          type="button"
          class="flex h-8 w-8 items-center justify-center rounded-lg text-outline transition-colors hover:bg-white/[0.06] hover:text-primary"
          :title="isCollapsed ? 'Mở rộng thanh bên' : 'Thu gọn thanh bên'"
          @click="isCollapsed = !isCollapsed"
        >
          <PanelLeftOpen v-if="isCollapsed" class="h-4 w-4" />
          <PanelLeftClose v-else class="h-4 w-4" />
        </button>
      </div>

      <!-- New Conversation Button -->
      <button
        type="button"
        :disabled="isStreaming"
        class="group flex items-center gap-3 rounded-xl border border-white/[0.09] bg-[#171717] text-left text-sm font-medium text-primary transition-all duration-200 hover:border-white/25 hover:bg-[#202020] disabled:opacity-50"
        :class="isCollapsed ? 'h-10 w-10 justify-center mx-auto' : 'px-3.5 py-2.5 w-full'"
        title="Cuộc trò chuyện mới"
        @click="emit('new-chat')"
      >
        <Plus class="h-4 w-4 shrink-0 text-primary transition-transform duration-200 group-hover:rotate-90" />
        <span v-if="!isCollapsed" class="truncate">Cuộc trò chuyện mới</span>
      </button>
    </div>

    <!-- Middle Section: Conversation History List -->
    <div class="flex-1 overflow-y-auto px-2.5 py-2 scrollbar-thin">
      <div
        v-if="!isCollapsed"
        class="mb-2 px-2 font-label-telemetry text-[10px] uppercase tracking-[0.18em] text-outline"
      >
        Lịch sử hội thoại
      </div>

      <div v-if="sessions.length === 0 && !isCollapsed" class="px-2.5 py-8 text-center">
        <p class="text-xs text-outline">Chưa có cuộc hội thoại nào</p>
      </div>

      <ul class="space-y-1">
        <li v-for="item in sessions" :key="item.session_id">
          <div
            role="button"
            tabindex="0"
            class="group relative flex items-center rounded-xl transition-all duration-150 cursor-pointer"
            :class="[
              isCollapsed ? 'h-10 w-10 justify-center mx-auto' : 'px-3 py-2.5 gap-2.5',
              item.session_id === activeSessionId
                ? 'bg-white/[0.09] text-primary border border-white/[0.12]'
                : 'text-on-surface-variant hover:bg-white/[0.04] hover:text-primary border border-transparent',
            ]"
            :title="item.title"
            @click="emit('select-session', item.session_id)"
            @keydown.enter="emit('select-session', item.session_id)"
          >
            <MessageSquare
              class="h-4 w-4 shrink-0"
              :class="item.session_id === activeSessionId ? 'text-primary' : 'text-outline'"
            />

            <div v-if="!isCollapsed" class="min-w-0 flex-1">
              <div class="flex items-center justify-between gap-1">
                <p class="truncate text-xs font-medium leading-snug">
                  {{ item.title || 'Cuộc trò chuyện mới' }}
                </p>
                <span class="shrink-0 font-label-telemetry text-[10px] text-outline group-hover:hidden">
                  {{ formatRelativeDate(item.created_at) }}
                </span>
              </div>
              <p
                v-if="item.last_message"
                class="mt-0.5 truncate text-[11px] text-outline"
              >
                {{ item.last_message }}
              </p>
            </div>

            <button
              v-if="!isCollapsed"
              type="button"
              class="hidden h-6 w-6 shrink-0 items-center justify-center rounded-md text-outline transition-colors hover:bg-white/10 hover:text-error group-hover:flex"
              title="Xóa hội thoại"
              @click.stop="emit('delete-session', item.session_id)"
            >
              <Trash2 class="h-3.5 w-3.5" />
            </button>
          </div>
        </li>
      </ul>
    </div>

    <!-- Bottom Section: User Avatar (opens Profile & Settings Modal) -->
    <div class="border-t border-white/[0.07] p-3">
      <button
        type="button"
        class="group flex w-full items-center rounded-xl p-1.5 text-left transition-colors hover:bg-white/[0.06]"
        :class="isCollapsed ? 'justify-center' : 'gap-3 px-2 py-2'"
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

        <div v-if="!isCollapsed" class="min-w-0 flex-1">
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

