<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { LayoutDashboard, PanelLeftOpen, SquarePen } from 'lucide-vue-next'
import ChatComposer from '@/components/chat/ChatComposer.vue'
import ChatEmptyState from '@/components/chat/ChatEmptyState.vue'
import ChatMessageList from '@/components/chat/ChatMessageList.vue'
import ChatSidebar from '@/components/chat/ChatSidebar.vue'
import VoiceDock from '@/components/chat/VoiceDock.vue'
import UserSettingsModal from '@/components/chat/UserSettingsModal.vue'
import NotificationBell from '@/components/notifications/NotificationBell.vue'
import HfToast from '@/components/app/HfToast.vue'
import MobileTabBar, { type MobileTab } from '@/components/app/MobileTabBar.vue'
import { AnimatePresence, motion } from 'motion-v'
import { collapseWidth, drawerLeft, fade, presence } from '@/motion'
import type { DashboardTab } from '@/components/dashboard/DashboardModal.vue'
import { useAuth } from '@/composables/useAuth'
import { useChat } from '@/composables/useChat'
import { useMobile } from '@/composables/useMobile'
import { onArrival } from '@/composables/useNotifications'
import { useThemeDefault } from '@/composables/useTheme'
import { useVoice } from '@/composables/useVoice'
import { createHealthApi } from '@/features/health-integration/api'
import { syncOnOpen } from '@/features/health-integration/openSync'
import type { ConfirmExtras } from '@/components/chat/cards/ConfirmationCard.vue'

useThemeDefault('light')
const { user, authFetch } = useAuth()
const {
  sessions,
  activeSessionId,
  messages,
  isStreaming,
  isConfirming,
  isLoadingHistory,
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
const { voiceState, userLevel, agentLevel, caption, muted, toggleVoice, stopVoice, toggleMute } = useVoice()
const { isMobile, keyboardOpen, viewportHeight } = useMobile()

const DashboardModal = defineAsyncComponent(() => import('@/components/dashboard/DashboardModal.vue'))
const isDashboardOpen = ref(false)
// Điện thoại: Dashboard là các trang của thanh tab dưới, mở một lần rồi giữ nguyên (ẩn khi về khung chat) để chuyển
// tab không phải tải lại dữ liệu và vẫn giữ vị trí cuộn.
const dashboardOpened = ref(false)
watch(isDashboardOpen, open => { if (open) dashboardOpened.value = true })
const dashboardTab = ref<DashboardTab>('today')
const isUserModalOpen = ref(false)
// Màn hình đồng ý của Google Health quay về /chat?integration=google-health&result=...
const userModalTab = ref<'profile' | 'integrations' | 'notifications'>('profile')
const integrationResult = ref<string | null>(null)
const composer = useTemplateRef<InstanceType<typeof ChatComposer>>('composer')
const toast = shallowRef<{ text: string; action?: string; run?: () => void }>({ text: '' })
const bell = useTemplateRef<InstanceType<typeof NotificationBell>>('bell')
let toastTimer: ReturnType<typeof setTimeout> | undefined

const title = computed(() => sessions.value.find(item => item.session_id === activeSessionId.value)?.title || 'Cuộc trò chuyện mới')

function openDashboard(tab: DashboardTab = 'today'): void {
  dashboardTab.value = tab
  isDashboardOpen.value = true
}

function say(message: string, action?: { label: string; run: () => void }, ms = 2800): void {
  toast.value = { text: message, action: action?.label, run: action?.run }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = { text: '' } }, ms)
}

/** Nút trong Dashboard ("Ghi bữa ăn"...): đóng Dashboard và điền sẵn câu mở đầu vào ô soạn tin. */
async function prefill(text: string): Promise<void> {
  isDashboardOpen.value = false
  await nextTick()
  composer.value?.prefill(text)
  say('Đã chuyển sang trợ lý')
}

/** Lịch tập vừa được xác nhận hiện ngay trong tab Kế hoạch của Dashboard. */
async function handleConfirm(decision: 'approve' | 'reject', extras: ConfirmExtras = {}): Promise<void> {
  const tool = pendingAction.value?.tool
  await confirmAction(decision, extras)
  if (decision === 'approve' && !error.value && (tool === 'create_training_plans' || tool === 'update_training_plans')) openDashboard('plan')
}

/** "Lập lịch với trợ lý": lập lịch thuộc chế độ Plan (đọc dữ liệu, tra nguyên tắc rồi đề xuất lịch). */
function createPlan(): void {
  if (isStreaming.value || isConfirming.value) return
  isDashboardOpen.value = false
  askInPlan('Lập giúp mình một lịch tập mới theo mục tiêu hiện tại.')
}

/** "Hỏi trợ lý" từ Dashboard hoặc thông báo: câu hỏi sức khoẻ cá nhân thuộc chế độ Plan (có miền health). */
function askAboutHealth(text: string): void {
  if (isStreaming.value || isConfirming.value) return
  isDashboardOpen.value = false
  askInPlan(text)
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

// Điện thoại: thanh bên là ngăn kéo phủ lên khung chat, ẩn sẵn và tự đóng sau khi chọn.
const isSidebarCollapsed = shallowRef(isMobile.value)
const sidebar = useTemplateRef<InstanceType<typeof ChatSidebar>>('sidebar')
const openSidebarButton = useTemplateRef<HTMLButtonElement>('openSidebarButton')
const sidebarMotion = computed(() => presence(isMobile.value ? drawerLeft : collapseWidth(268)))
const closeDrawer = () => { if (isMobile.value) isSidebarCollapsed.value = true }

function selectTab(tab: MobileTab): void {
  if (tab === 'chat') isDashboardOpen.value = false
  else openDashboard(tab)
}

// Bàn phím ảo mở (iOS không co bố cục): khung ứng dụng cao bằng vùng nhìn thấy và trang không bị đẩy lên theo ô nhập.
watch([keyboardOpen, viewportHeight], () => { if (isMobile.value && keyboardOpen.value) window.scrollTo(0, 0) })

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
  // Tần suất "Khi mở ứng dụng": một lượt đồng bộ Google Health cho lần tải trang này.
  void syncOnOpen(createHealthApi((url, init) => authFetch(url, init)))
  await loadSessions()
})
// Rời ứng dụng (đăng xuất về trang giới thiệu): trả lại giao diện mặc định của trang đó.
// Thông báo mới qua WebSocket: toast ngắn, nút "Xem" mở hộp thư ở chuông.
const stopArrivals = onArrival(item => say(item.title, { label: 'Xem', run: () => { toast.value = { text: '' }; bell.value?.open() } }, 6000))
onUnmounted(() => {
  void stopVoice()
  stopArrivals()
  clearTimeout(toastTimer)
  useThemeDefault('dark')
})
</script>

<template>
  <div class="hf shell" :class="{ blur: isDashboardOpen && !isMobile, tabbed: isMobile && !keyboardOpen }"
       :style="isMobile && keyboardOpen ? { height: `${viewportHeight}px` } : undefined">
    <AnimatePresence :initial="false">
    <motion.button v-if="isMobile && !isSidebarCollapsed" key="scrim" type="button" class="hf-scrim drawer-scrim"
                   aria-label="Đóng thanh bên" v-bind="presence(fade)" @click="hideSidebar" />
    <motion.div v-if="!isSidebarCollapsed" key="sidebar" class="side-wrap" v-bind="sidebarMotion">
    <ChatSidebar
      ref="sidebar"
      :sessions="sessions"
      :active-session-id="activeSessionId"
      :user="user"
      :is-streaming="isStreaming"
      @new-chat="createNewSession(); closeDrawer()"
      @select-session="selectSession($event); closeDrawer()"
      @delete-session="deleteSession"
      @open-user-modal="openSettings('profile'); closeDrawer()"
      @open-dashboard="openDashboard('today')"
      @open-map="openDashboard('map')"
      @collapse="hideSidebar"
    />
    </motion.div>
    </AnimatePresence>

    <main class="chat">
      <header class="chat-head">
        <div class="head-left">
          <button
            v-if="isSidebarCollapsed"
            ref="openSidebarButton"
            type="button"
            class="hf-ib clear"
            style="width: 40px; height: 40px"
            title="Mở thanh bên"
            aria-label="Mở thanh bên"
            aria-controls="chat-sidebar"
            aria-expanded="false"
            @click="showSidebar"
          >
            <PanelLeftOpen :size="18" :stroke-width="1.8" aria-hidden="true" />
          </button>
          <h1 class="title">{{ title }}</h1>
        </div>
        <div class="head-right">
          <NotificationBell ref="bell" @ask="askAboutHealth" @settings="openSettings('notifications')" />
          <button v-if="isMobile" type="button" class="hf-ib clear" style="width: 40px; height: 40px" title="Cuộc trò chuyện mới"
                  aria-label="Cuộc trò chuyện mới" :disabled="isStreaming || !hasMessages" @click="createNewSession">
            <SquarePen :size="18" :stroke-width="1.8" aria-hidden="true" />
          </button>
          <button v-else-if="isSidebarCollapsed" type="button" class="hf-btn sm" @click="openDashboard('today')">
            <LayoutDashboard :size="16" aria-hidden="true" />Dashboard
          </button>
        </div>
      </header>

      <div v-if="error" class="error-wrap">
        <div class="hf-err" role="alert">{{ error }}</div>
      </div>

      <!-- Trống / cuộc trò chuyện mới -->
      <div v-if="!hasMessages" class="empty">
        <ChatEmptyState :user="user">
          <template #composer>
            <VoiceDock
              v-if="voiceState !== 'idle'"
              :state="voiceState"
              :user-level="userLevel"
              :agent-level="agentLevel"
              :caption="caption"
              :muted="muted"
              @mute="toggleMute"
              @end="stopVoice"
            />
            <ChatComposer
              v-else
              ref="composer"
              :mode="chatMode"
              :disabled="isConfirming || isLoadingHistory"
              :is-streaming="isStreaming"
              :voice-state="voiceState"
              @send="sendMessage"
              @stop="stopStreaming"
              @voice="toggleVoice"
              @update:mode="setChatMode"
            />
          </template>
        </ChatEmptyState>
      </div>

      <!-- Luồng hội thoại -->
      <template v-else>
        <ChatMessageList
          :messages="messages"
          :is-streaming="isStreaming"
          :is-confirming="isConfirming"
          :active-node-label="activeNodeLabel"
          :pending-action="pendingAction"
          @confirm="handleConfirm"
          @send="sendMessage"
          @resolve-foods="(choices, text) => sendMessage(text, { food_choices: choices })"
          @ask-in-plan="askInPlan"
        />
        <div class="composer-wrap">
          <div class="col720">
            <VoiceDock
              v-if="voiceState !== 'idle'"
              :state="voiceState"
              :user-level="userLevel"
              :agent-level="agentLevel"
              :caption="caption"
              :muted="muted"
              @mute="toggleMute"
              @end="stopVoice"
            />
            <ChatComposer
              v-else
              ref="composer"
              :mode="chatMode"
              :disabled="isConfirming || isLoadingHistory"
              :is-streaming="isStreaming"
              :voice-state="voiceState"
              @send="sendMessage"
              @stop="stopStreaming"
              @voice="toggleVoice"
              @update:mode="setChatMode"
            />
            <p class="disclaimer">Trợ lý HercFit có thể sai sót và không thay thế tư vấn y khoa.</p>
          </div>
        </div>
      </template>
    </main>
  </div>

  <DashboardModal
    v-if="isDashboardOpen || (isMobile && dashboardOpened)"
    v-model:tab="dashboardTab"
    :hidden="!isDashboardOpen"
    :busy="isStreaming || isConfirming"
    :revision="messages.length + Number(isStreaming) + Number(isConfirming) + sessions.length"
    @close="isDashboardOpen = false"
    @settings="openSettings"
    @ask="askAboutHealth"
    @prefill="prefill"
    @create-plan="createPlan"
  />

  <!-- Hộp thoại Hồ sơ & kết nối -->
  <UserSettingsModal
    :open="isUserModalOpen"
    :initial-tab="userModalTab"
    :integration-result="integrationResult"
    @close="isUserModalOpen = false"
  />

  <MobileTabBar v-if="isMobile && !keyboardOpen" :active="isDashboardOpen ? dashboardTab : 'chat'" @select="selectTab" />

  <HfToast :message="toast.text" :action="toast.action" @action="toast.run?.()" />
</template>

<style scoped>
.shell { position: relative; display: flex; height: 100vh; height: 100dvh; width: 100vw; overflow: hidden; background: var(--hf-canvas); transition: filter .25s; }
.shell.blur { filter: blur(7px); }
.side-wrap { flex: none; height: 100%; overflow: hidden; }
.chat { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.chat-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 16px; min-height: 60px; flex: none; }
.head-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
.title { margin: 0; font-size: 15px; font-weight: 600; color: var(--hf-ink); padding: 0 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.head-right { display: flex; align-items: center; gap: 6px; flex: none; }
.error-wrap { max-width: 720px; width: 100%; margin: 4px auto 0; padding: 0 24px; }
.empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; overflow-y: auto; padding: 24px 0; }
.composer-wrap { padding: 8px 24px 16px; flex: none; }
.col720 { max-width: 720px; margin: 0 auto; width: 100%; }
.disclaimer { text-align: center; font-size: 12px; color: var(--hf-muted); margin: 10px 0 0; }
/*
 * Điện thoại: khung chat nằm trên thanh tab dưới (MobileTabBar); thanh bên thành ngăn kéo trượt từ trái, phủ lên chat.
 * Bàn phím ảo mở thì thanh tab ẩn (.tabbed mất) để ô soạn tin nằm sát bàn phím.
 */
@media (max-width: 760px) {
  .shell { width: 100%; }
  .shell.tabbed { padding-bottom: var(--hf-tabbar-h); }
  .drawer-scrim { z-index: 55; }
  .side-wrap { position: fixed; inset: 0 auto 0 0; z-index: 56; width: min(86vw, 320px); box-shadow: 0 0 60px var(--hf-shadow-2); }
  .chat-head { padding: calc(var(--hf-safe-top) + 6px) 8px 6px; min-height: 0; gap: 4px; }
  .head-left { gap: 2px; flex: 1; }
  .head-right { gap: 0; }
  .title { padding: 0 6px; font-size: 16px; }
  .error-wrap { padding: 0 12px; }
  .chat > .empty { justify-content: flex-start; padding: 0; }
  .composer-wrap { padding: 6px 12px 8px; }
  .disclaimer { font-size: 11px; margin-top: 6px; }
}
@media (prefers-reduced-motion: reduce) { .shell { transition: none; } }
</style>
