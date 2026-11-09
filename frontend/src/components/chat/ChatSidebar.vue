<script setup lang="ts">
import { computed, useTemplateRef } from 'vue'
import { LayoutDashboard, Orbit, PanelLeftClose, Plus } from 'lucide-vue-next'
import type { SessionSummary, UserProfile } from '@/types/api'
import HfLogo from '@/components/app/HfLogo.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
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
  (e: 'open-dashboard'): void
  (e: 'open-map'): void
  (e: 'collapse'): void
}>()

const collapseButton = useTemplateRef<HTMLButtonElement>('collapseButton')

defineExpose({
  focusToggle: () => collapseButton.value?.focus(),
})

const displayName = computed(() => props.user?.nick_name || props.user?.fullname || 'Bạn')
const initial = computed(() => (displayName.value.trim()[0] || 'B').toUpperCase())
</script>

<template>
  <aside id="chat-sidebar" class="side" aria-label="Thanh bên">
    <div class="brand">
      <a href="/" class="brand-link">
        <HfLogo :size="28" />
        <span>HercFit</span>
      </a>
      <button
        ref="collapseButton"
        type="button"
        class="hf-ib clear"
        style="width: 40px; height: 40px"
        title="Thu gọn thanh bên"
        aria-label="Thu gọn thanh bên"
        aria-controls="chat-sidebar"
        aria-expanded="true"
        @click="emit('collapse')"
      >
        <PanelLeftClose :size="18" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </div>

    <button type="button" class="snav" :disabled="isStreaming" @click="emit('new-chat')">
      <span class="new-dot"><Plus :size="14" :stroke-width="2.4" aria-hidden="true" /></span>
      Cuộc trò chuyện mới
    </button>
    <button type="button" class="snav" @click="emit('open-dashboard')">
      <LayoutDashboard :size="18" :stroke-width="1.8" class="nav-icon" aria-hidden="true" />
      Dashboard
    </button>
    <button type="button" class="snav" @click="emit('open-map')">
      <Orbit :size="18" :stroke-width="1.8" class="nav-icon" aria-hidden="true" />
      Bản đồ dữ liệu
    </button>

    <p class="hf-lbl recent">Gần đây</p>
    <ChatHistoryList
      :sessions="sessions"
      :active-session-id="activeSessionId"
      :is-streaming="isStreaming"
      @select-session="emit('select-session', $event)"
      @delete-session="emit('delete-session', $event)"
    />

    <div class="foot">
      <button type="button" class="snav me" title="Hồ sơ & kết nối" @click="emit('open-user-modal')">
        <span class="avatar">
          <img v-if="user?.avatar_url" :src="user.avatar_url" :alt="displayName" referrerpolicy="no-referrer" />
          <template v-else>{{ initial }}</template>
        </span>
        <span class="me-text">
          <span class="me-name">{{ displayName }}</span>
          <span class="me-sub">Hồ sơ &amp; kết nối</span>
        </span>
      </button>
      <ThemeToggle variant="app" />
    </div>
  </aside>
</template>

<style scoped>
.side {
  position: relative; z-index: 20; width: 268px; flex: none; height: 100%; min-height: 0;
  display: flex; flex-direction: column; gap: 2px; padding: 12px; background: var(--hf-side); user-select: none;
}
.brand { display: flex; align-items: center; justify-content: space-between; padding: 4px 4px 14px 8px; }
.brand-link { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 17px; color: var(--hf-ink); text-decoration: none; }
.snav {
  display: flex; align-items: center; gap: 10px; border: 0; background: transparent; text-align: left; width: 100%;
  padding: 0 10px; border-radius: 10px; font-size: 14px; font-weight: 500; color: var(--hf-ink); min-height: 40px;
}
.snav:hover:not(:disabled) { background: var(--hf-hover); }
.snav:disabled { opacity: .5; }
.new-dot {
  width: 26px; height: 26px; border-radius: 50%; background: var(--hf-ink); color: var(--hf-on-ink);
  display: inline-flex; align-items: center; justify-content: center; flex: none;
}
.nav-icon { margin: 0 4px; flex: none; }
.recent { padding: 18px 10px 6px; font-size: 12px; }
.foot { display: flex; align-items: center; gap: 6px; border-top: 1px solid var(--hf-press); padding-top: 8px; margin-top: 4px; }
.me { min-height: 52px; flex: 1; min-width: 0; padding: 0 8px; }
.avatar {
  width: 32px; height: 32px; border-radius: 50%; background: var(--hf-line); flex: none; overflow: hidden;
  display: inline-flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700;
}
.avatar img { width: 100%; height: 100%; object-fit: cover; }
.me-text { display: flex; flex-direction: column; line-height: 1.25; min-width: 0; }
.me-name, .me-sub { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.me-sub { font-size: 12px; color: var(--hf-muted); font-weight: 400; }
</style>
