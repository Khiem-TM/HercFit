<script setup lang="ts">
import { defineAsyncComponent, nextTick, onMounted, ref, shallowRef, useTemplateRef } from 'vue'
import { PanelLeftOpen, Sparkles } from 'lucide-vue-next'
import ChatComposer from '@/components/chat/ChatComposer.vue'
import ChatEmptyState from '@/components/chat/ChatEmptyState.vue'
import ChatMessageList from '@/components/chat/ChatMessageList.vue'
import ChatSidebar from '@/components/chat/ChatSidebar.vue'
import UserSettingsModal from '@/components/chat/UserSettingsModal.vue'
import NotificationBell from '@/components/notifications/NotificationBell.vue'
import { useAuth } from '@/composables/useAuth'
import { useChat } from '@/composables/useChat'
import type { ConfirmExtras } from '@/components/chat/cards/ConfirmationCard.vue'
import type { KnowledgeTab } from '@/types/knowledge'

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
  chatMode,
  setChatMode,
  askInPlan,
} = useChat()

const KnowledgePanel = defineAsyncComponent(() => import('@/components/knowledge/KnowledgePanel.vue'))
const isKnowledgeOpen = ref(false)
const knowledgeTab = ref<KnowledgeTab>('overview')
const isUserModalOpen = ref(false)
// Màn hình đồng ý của Google Health quay về /chat?integration=google-health&result=...
const userModalTab = ref<'profile' | 'integrations' | 'notifications'>('profile')
const integrationResult = ref<string | null>(null)

function openPlan(): void {
  knowledgeTab.value = 'plan'
  isKnowledgeOpen.value = true
}

/** Lịch tập vừa được xác nhận hiện ngay dưới dạng checklist ở thanh bên. */
async function handleConfirm(decision: 'approve' | 'reject', extras: ConfirmExtras = {}): Promise<void> {
  const tool = pendingAction.value?.tool
  await confirmAction(decision, extras)
  if (decision === 'approve' && !error.value && (tool === 'create_training_plans' || tool === 'update_training_plans')) openPlan()
}

/** Nút "Lập lịch mới" ở thanh bên: lập lịch thuộc chế độ Plan (đọc dữ liệu, tra nguyên tắc rồi đề xuất lịch). */
function createPlan(): void {
  if (isStreaming.value || isConfirming.value) return
  askInPlan('Lập giúp mình một lịch tập mới theo mục tiêu hiện tại.')
}

/** "Hỏi trợ lý" từ thẻ sẵn sàng hoặc thông báo: câu hỏi sức khoẻ cá nhân thuộc chế độ Plan (có miền health). */
function askAboutHealth(text: string): void {
  if (isStreaming.value || isConfirming.value) return
  askInPlan(text)
}

function openUserModal(): void {
  userModalTab.value = 'profile'
  integrationResult.value = null
  isUserModalOpen.value = true
}

function openSettings(tab: 'profile' | 'integrations' | 'notifications'): void {
  userModalTab.value = tab
  integrationResult.value = null
  isUserModalOpen.value = true
}

function consumeIntegrationReturn(): void {
  const params = new URLSearchParams(window.location.search)
  if (params.get('integration') !== 'google-health') return
  integrationResult.value = params.get('result') ?? 'error'
  userModalTab.value = 'integrations'
  isUserModalOpen.value = true
  window.history.replaceState({}, '', window.location.pathname)
}
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
  consumeIntegrationReturn()
  if (!activeSessionId.value) {
    createNewSession()
  }
  await loadSessions()
})
</script>

<template>
  <div
    class="relative flex h-screen w-screen overflow-hidden bg-background font-body-md text-on-surface selection:bg-ink selection:text-paper"
  >
    <!-- Lớp phủ nhiễu hạt giống trang giới thiệu -->
    <div class="grain-overlay pointer-events-none" aria-hidden="true" />

    <!-- Vệt sáng toả tròn nhẹ tạo không khí -->
    <div
      class="pointer-events-none absolute left-1/2 top-1/4 z-0 h-[540px] w-[760px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink/[0.035] blur-[130px]"
      aria-hidden="true"
    />

    <!-- Thanh bên trái (CHỈ gồm lịch sử + cuộc trò chuyện mới + avatar người dùng) -->
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
      @open-user-modal="openUserModal"
      @collapse="hideSidebar"
    />

    <!-- Vùng làm việc chính bên phải -->
    <main class="relative z-10 flex min-w-0 flex-1 flex-col">
      <!-- Thanh trên tối giản -->
      <header
        class="flex h-14 shrink-0 items-center justify-between border-b border-ink/[0.05] px-6"
      >
        <div class="flex min-w-0 items-center gap-2.5 overflow-hidden whitespace-nowrap">
          <button
            v-if="isSidebarCollapsed"
            ref="openSidebarButton"
            type="button"
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-outline transition-colors hover:bg-ink/[0.06] hover:text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-ink/60"
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

        <div class="ml-auto flex shrink-0 items-center gap-2">
          <NotificationBell @ask="askAboutHealth" @settings="openSettings('notifications')" />
          <button type="button" class="shrink-0 whitespace-nowrap rounded-full border border-gold/25 px-3 py-1.5 text-xs text-gold hover:bg-gold/10" :aria-expanded="isKnowledgeOpen" @click="isKnowledgeOpen = !isKnowledgeOpen">✧ Dashboard</button>
        </div>
      </header>

      <!-- Banner lỗi -->
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

      <!-- TRẠNG THÁI A: Trống / cuộc trò chuyện mới (theo bố cục tham chiếu) -->
      <div
        v-if="!hasMessages"
        class="flex flex-1 flex-col items-center justify-center overflow-y-auto py-6"
      >
        <ChatEmptyState
          :user="user"
        >
          <template #composer>
            <ChatComposer
              :mode="chatMode"
              :is-streaming="isStreaming"
              @send="sendMessage"
              @stop="stopStreaming"
              @update:mode="setChatMode"
            />
          </template>
        </ChatEmptyState>
      </div>

      <!-- TRẠNG THÁI B: Luồng hội thoại đang diễn ra -->
      <template v-else>
        <ChatMessageList
          :messages="messages"
          :is-streaming="isStreaming"
          :is-confirming="isConfirming"
          :active-node-label="activeNodeLabel"
          :pending-action="pendingAction"
          @confirm="handleConfirm"
          @send="sendMessage"
          @ask-in-plan="askInPlan"
        />

        <!-- Khung soạn tin ghim ở dưới cùng -->
        <div class="shrink-0 px-4 pb-5 pt-2 md:px-8">
          <div class="mx-auto w-full max-w-3xl">
            <ChatComposer
              :mode="chatMode"
              :is-streaming="isStreaming"
              @send="sendMessage"
              @stop="stopStreaming"
              @update:mode="setChatMode"
            />
          </div>
        </div>
      </template>
    </main>

    <KnowledgePanel v-if="isKnowledgeOpen" v-model:tab="knowledgeTab" :busy="isStreaming || isConfirming" :activity="activeNodeLabel" :revision="messages.length + Number(isStreaming) + Number(isConfirming) + sessions.length" @close="isKnowledgeOpen = false" @open-settings="openSettings" @create-plan="createPlan" @ask="askAboutHealth" />

    <!-- Hộp thoại Hồ sơ, Số đo & Cài đặt -->
    <UserSettingsModal
      :open="isUserModalOpen"
      :initial-tab="userModalTab"
      :integration-result="integrationResult"
      @close="isUserModalOpen = false"
    />
  </div>
</template>

