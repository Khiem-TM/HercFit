<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Plus, Sparkles } from 'lucide-vue-next'
import ChatComposer from '@/components/chat/ChatComposer.vue'
import ChatEmptyState from '@/components/chat/ChatEmptyState.vue'
import ChatMessageList from '@/components/chat/ChatMessageList.vue'
import ChatSidebar from '@/components/chat/ChatSidebar.vue'
import UserSettingsModal from '@/components/chat/UserSettingsModal.vue'
import { useAuth } from '@/composables/useAuth'
import { useChat } from '@/composables/useChat'

const { user } = useAuth()
const {
  sessions,
  activeSessionId,
  messages,
  isStreaming,
  isConfirming,
  activeNodeLabel,
  pendingAction,
  hasMessages,
  error,
  loadSessions,
  createNewSession,
  selectSession,
  deleteSession,
  sendMessage,
  confirmAction,
} = useChat()

const isUserModalOpen = ref(false)

onMounted(async () => {
  if (!activeSessionId.value) {
    createNewSession()
  }
  await loadSessions()
})

function handleSelectPrompt(prompt: string): void {
  sendMessage(prompt)
}
</script>

<template>
  <div
    class="relative flex h-screen w-screen overflow-hidden bg-background font-body-md text-on-surface selection:bg-white selection:text-[#0e0e0e]"
  >
    <!-- Film grain overlay matching Landing Page -->
    <div class="grain-overlay pointer-events-none" aria-hidden="true" />

    <!-- Subtle atmospheric radial spotlight -->
    <div
      class="pointer-events-none absolute left-1/2 top-1/4 z-0 h-[540px] w-[760px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-white/[0.035] blur-[130px]"
      aria-hidden="true"
    />

    <!-- Left Sidebar (History + New Chat + User Avatar ONLY) -->
    <ChatSidebar
      :sessions="sessions"
      :active-session-id="activeSessionId"
      :user="user"
      :is-streaming="isStreaming"
      @new-chat="createNewSession"
      @select-session="selectSession"
      @delete-session="deleteSession"
      @open-user-modal="isUserModalOpen = true"
    />

    <!-- Right Main Workspace -->
    <main class="relative z-10 flex min-w-0 flex-1 flex-col">
      <!-- Minimal Top Bar -->
      <header
        class="flex h-14 shrink-0 items-center justify-between border-b border-white/[0.05] px-6"
      >
        <div class="flex items-center gap-2.5">
          <Sparkles class="h-4 w-4 text-outline" />
          <span class="text-xs font-medium text-on-surface-variant">
            HercFit Kinetic AI
          </span>
          <span class="font-label-telemetry text-[10px] text-outline">
            // OLYMPUS CORE
          </span>
        </div>

        <button
          v-if="hasMessages"
          type="button"
          :disabled="isStreaming"
          class="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-on-surface-variant transition-colors hover:border-white/25 hover:text-primary disabled:opacity-50"
          @click="createNewSession"
        >
          <Plus class="h-3.5 w-3.5" />
          <span>Hội thoại mới</span>
        </button>
      </header>

      <!-- Error Banner -->
      <div
        v-if="error"
        class="mx-auto mt-3 w-full max-w-3xl px-4"
      >
        <div
          class="rounded-xl border border-error/40 bg-error/10 px-4 py-2.5 text-xs text-error"
        >
          {{ error }}
        </div>
      </div>

      <!-- STATE A: Empty / New Conversation (Matches Reference Layout) -->
      <div
        v-if="!hasMessages"
        class="flex flex-1 flex-col items-center justify-center overflow-y-auto py-6"
      >
        <ChatEmptyState
          :user="user"
          @select-prompt="handleSelectPrompt"
        >
          <template #composer>
            <ChatComposer
              :is-streaming="isStreaming"
              :active-node-label="activeNodeLabel"
              @send="sendMessage"
            />
          </template>
        </ChatEmptyState>
      </div>

      <!-- STATE B: Active Conversation Stream -->
      <template v-else>
        <ChatMessageList
          :messages="messages"
          :is-streaming="isStreaming"
          :is-confirming="isConfirming"
          :active-node-label="activeNodeLabel"
          :pending-action="pendingAction"
          @confirm="confirmAction"
        />

        <!-- Bottom Pinned Composer -->
        <div class="shrink-0 px-4 pb-5 pt-2 md:px-8">
          <div class="mx-auto w-full max-w-3xl">
            <ChatComposer
              :is-streaming="isStreaming"
              :active-node-label="activeNodeLabel"
              @send="sendMessage"
            />
          </div>
        </div>
      </template>
    </main>

    <!-- User Profile, Metrics & Settings Modal -->
    <UserSettingsModal
      :open="isUserModalOpen"
      @close="isUserModalOpen = false"
    />
  </div>
</template>

