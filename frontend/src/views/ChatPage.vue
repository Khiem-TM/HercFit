<script setup lang="ts">
import { defineAsyncComponent, nextTick, onMounted, ref, shallowRef, useTemplateRef } from 'vue'
import { PanelLeftOpen, Plus, Sparkles } from 'lucide-vue-next'
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
  stopStreaming,
  confirmAction,
} = useChat()

const KnowledgePanel = defineAsyncComponent(() => import('@/components/knowledge/KnowledgePanel.vue'))
const ImageLibraryModal = defineAsyncComponent(() => import('@/components/media/ImageLibraryModal.vue'))
const isImageLibraryOpen = ref(false)
const isKnowledgeOpen = ref(false)
const isUserModalOpen = ref(false)
const isSidebarCollapsed = shallowRef(false)
const sidebar = useTemplateRef<InstanceType<typeof ChatSidebar>>('sidebar')
const openSidebarButton = useTemplateRef<HTMLButtonElement>('openSidebarButton')

async function hideSidebar(): Promise<void> {
  isSidebarCollapsed.value = true
  await nextTick()
  openSidebarButton.value?.focus()
}

async function showSidebar(): Promise<void> {
  isSidebarCollapsed.value = false
  await nextTick()
  sidebar.value?.focusToggle()
}

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
      v-if="!isSidebarCollapsed"
      ref="sidebar"
      :sessions="sessions"
      :active-session-id="activeSessionId"
      :user="user"
      :is-streaming="isStreaming"
      @new-chat="createNewSession"
      @select-session="selectSession"
      @delete-session="deleteSession"
      @open-user-modal="isUserModalOpen = true"
      @collapse="hideSidebar"
    />

    <!-- Right Main Workspace -->
    <main class="relative z-10 flex min-w-0 flex-1 flex-col">
      <!-- Minimal Top Bar -->
      <header
        class="flex h-14 shrink-0 items-center justify-between border-b border-white/[0.05] px-6"
      >
        <div class="flex min-w-0 items-center gap-2.5 overflow-hidden whitespace-nowrap">
          <button
            v-if="isSidebarCollapsed"
            ref="openSidebarButton"
            type="button"
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-outline transition-colors hover:bg-white/[0.06] hover:text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-white/60"
            title="Mở thanh bên"
            aria-label="Mở thanh bên"
            aria-controls="chat-sidebar"
            aria-expanded="false"
            @click="showSidebar"
          >
            <PanelLeftOpen class="h-4 w-4" aria-hidden="true" />
          </button>
          <Sparkles class="h-4 w-4 shrink-0 text-outline" />
          <span class="text-xs font-medium text-on-surface-variant">
            HercFit Kinetic AI
          </span>
          <span class="truncate font-label-telemetry text-[10px] text-outline">
            // OLYMPUS CORE
          </span>
        </div>

        <button type="button" class="ml-auto mr-2 shrink-0 whitespace-nowrap rounded-full border border-white/10 px-3 py-1.5 text-xs text-on-surface-variant hover:bg-white/10" aria-haspopup="dialog" @click="isImageLibraryOpen = true">Ảnh</button>
        <button type="button" class="mr-3 shrink-0 whitespace-nowrap rounded-full border border-[#d4b77d]/25 px-3 py-1.5 text-xs text-[#d4b77d] hover:bg-[#d4b77d]/10" :aria-expanded="isKnowledgeOpen" @click="isKnowledgeOpen = !isKnowledgeOpen">✧ Tri thức của tôi</button>
        <button
          v-if="hasMessages"
          type="button"
          :disabled="isStreaming"
          class="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-on-surface-variant transition-colors hover:border-white/25 hover:text-primary disabled:opacity-50"
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
              @stop="stopStreaming"
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
          @send="sendMessage"
        />

        <!-- Bottom Pinned Composer -->
        <div class="shrink-0 px-4 pb-5 pt-2 md:px-8">
          <div class="mx-auto w-full max-w-3xl">
            <ChatComposer
              :is-streaming="isStreaming"
              :active-node-label="activeNodeLabel"
              @send="sendMessage"
              @stop="stopStreaming"
            />
          </div>
        </div>
      </template>
    </main>

    <KnowledgePanel v-if="isKnowledgeOpen" :busy="isStreaming || isConfirming" :activity="activeNodeLabel" :revision="messages.length + Number(isStreaming) + Number(isConfirming) + sessions.length" @close="isKnowledgeOpen = false" />
    <ImageLibraryModal v-if="isImageLibraryOpen" @close="isImageLibraryOpen = false" />

    <!-- User Profile, Metrics & Settings Modal -->
    <UserSettingsModal
      :open="isUserModalOpen"
      @close="isUserModalOpen = false"
    />
  </div>
</template>

