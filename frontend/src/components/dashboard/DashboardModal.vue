<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, shallowRef, useTemplateRef, watch } from 'vue'
import { CalendarDays, Plug, RefreshCw, UserRound, X } from 'lucide-vue-next'
import { AnimatePresence, motion } from 'motion-v'
import { indicatorTransition, modalTransition, presence } from '@/motion'
import { useAuth } from '@/composables/useAuth'
import { createHealthApi } from '@/features/health-integration/api'
import { syncOnOpen } from '@/features/health-integration/openSync'
import { goalChoices } from '@/features/onboarding/model'
import HfLogo from '@/components/app/HfLogo.vue'
import HfToast from '@/components/app/HfToast.vue'
import NutritionDetail from './NutritionDetail.vue'
import PlanTab from './PlanTab.vue'
import ProgressTab from './ProgressTab.vue'
import ReadinessDetail from './ReadinessDetail.vue'
import TodayTab from './TodayTab.vue'
import WorkoutDetail from './WorkoutDetail.vue'
import { clockTime, ddmmyyyy, localDate, stamp } from './format'
import { useDashboardData } from './useDashboardData'

export type DashboardTab = 'today' | 'progress' | 'plan' | 'map'
type SettingsTab = 'profile' | 'integrations' | 'notifications'

const MapTab = defineAsyncComponent(() => import('./MapTab.vue'))

/** Dashboard dạng hộp thoại lớn trên khung chat: Hôm nay · Tiến độ · Kế hoạch · Bản đồ. */
const props = defineProps<{ busy: boolean; revision: number }>()
const emit = defineEmits<{
  close: []
  settings: [tab: SettingsTab]
  ask: [text: string]
  prefill: [text: string]
  'create-plan': []
}>()
const tab = defineModel<DashboardTab>('tab', { default: 'today' })

const data = useDashboardData()
const { currentGoal, authFetch } = useAuth()
const detail = shallowRef<'' | 'ready' | 'workout' | 'nutrition'>('')
const mapOpened = shallowRef(tab.value === 'map')
const toast = shallowRef('')
// Đóng = chạy hiệu ứng ra trước (AnimatePresence), xong mới báo cho trang cha gỡ Dashboard.
const shown = shallowRef(true)
const close = () => { shown.value = false }
const dialog = useTemplateRef<HTMLElement>('dialog')
let toastTimer: ReturnType<typeof setTimeout> | undefined

const TABS: { id: DashboardTab; label: string }[] = [
  { id: 'today', label: 'Hôm nay' }, { id: 'progress', label: 'Tiến độ' }, { id: 'plan', label: 'Kế hoạch' }, { id: 'map', label: 'Bản đồ' },
]
const TITLES: Record<DashboardTab, string> = { today: 'Dashboard', progress: 'Tiến độ', plan: 'Kế hoạch', map: 'Bản đồ dữ liệu' }

function pick(next: DashboardTab) {
  tab.value = next
  detail.value = ''
}
watch(tab, value => { if (value === 'map') mapOpened.value = true })

const connection = computed(() => data.health.value?.connection ?? null)
const goalLabel = computed(() => {
  const goal = currentGoal.value
  if (!goal) return null
  return goalChoices.find(choice => choice.id === goal.goal_types?.[0])?.title ?? goal.title
})
const sync = computed(() => {
  const status = connection.value?.status
  if (data.loading.value || data.healthLoading.value) return { text: 'Đang tải dữ liệu…', dot: 'var(--hf-ghost)', warn: false }
  if (status === 'NEEDS_REAUTH' || status === 'ERROR' || data.failed.value.length) {
    const last = connection.value?.last_success_at
    return { text: last ? `Tải lỗi · dữ liệu lúc ${stamp(last)}` : 'Không tải được dữ liệu mới', dot: 'var(--hf-warn-dot)', warn: true }
  }
  if (status !== 'ACTIVE') return { text: 'Chưa kết nối thiết bị', dot: 'var(--hf-ghost)', warn: false }
  const last = connection.value?.last_sync_at
  if (!last) return { text: 'Chưa có dữ liệu đồng bộ', dot: 'var(--hf-ghost)', warn: false }
  const sameDay = localDate(last) === data.today
  return { text: sameDay ? `Đồng bộ lúc ${clockTime(last)}` : `Đồng bộ ${stamp(last)}`, dot: 'var(--hf-ok)', warn: false }
})

function say(message: string) {
  toast.value = message
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 2800)
}

async function refresh() {
  await data.refresh()
  say('Đã cập nhật dữ liệu')
}

function chat(text: string) {
  emit('prefill', text)
}

/* ---------- làm mới sau một lượt chat (có thể vừa lưu bữa ăn, buổi tập, lịch) ---------- */
let timers: ReturnType<typeof setTimeout>[] = []
function schedule(...delays: number[]) {
  timers.forEach(clearTimeout)
  timers = delays.map(delay => setTimeout(() => { if (!props.busy) void data.refresh() }, delay))
}
watch(() => props.busy, (busy, was) => { if (was && !busy) schedule(1500, 5000) })
watch(() => props.revision, () => { if (!props.busy) schedule(900) })

function keydown(event: KeyboardEvent) {
  if (event.key !== 'Escape' || event.defaultPrevented) return
  if (document.querySelector('.hf-smodal')) return  // hộp thoại Hồ sơ & kết nối đang mở phía trên
  if (detail.value) detail.value = ''
  else close()
}
onMounted(async () => {
  window.addEventListener('keydown', keydown)
  // "Khi mở ứng dụng": lượt đồng bộ của lần tải trang này xong thì đọc lại dữ liệu.
  void syncOnOpen(createHealthApi((url, init) => authFetch(url, init))).then(synced => { if (synced) void data.refresh() })
  await nextTick()
  // Phần tử motion: lấy DOM qua $el khi ref trỏ vào component.
  const node = dialog.value as unknown as HTMLElement & { $el?: HTMLElement }
  ;(node?.$el ?? node)?.focus?.({ preventScroll: true })
})
onUnmounted(() => {
  timers.forEach(clearTimeout)
  clearTimeout(toastTimer)
  window.removeEventListener('keydown', keydown)
})
</script>

<template>
  <Teleport to="body">
    <AnimatePresence @exit-complete="emit('close')">
    <div v-if="shown" class="hf dash-root">
      <motion.button type="button" class="hf-scrim scrim" aria-label="Đóng Dashboard" v-bind="presence(modalTransition.scrim)"
                     @click="close" />
      <div class="center">
      <motion.div ref="dialog" class="modal" role="dialog" aria-modal="true" aria-label="Dashboard HercFit" tabindex="-1"
                  v-bind="presence(modalTransition.panel)">
        <header class="mh">
          <div class="row1">
            <div class="brand"><HfLogo :size="30" /><span>HercFit</span></div>
            <nav class="tabs" aria-label="Điều hướng Dashboard">
              <button v-for="item in TABS" :key="item.id" type="button" class="tab" :class="{ on: tab === item.id }"
                      :aria-current="tab === item.id ? 'page' : undefined" @click="pick(item.id)">
                <motion.span v-if="tab === item.id" layout-id="dashboard-tab" class="tab-ind" :transition="indicatorTransition" />
                <span class="tab-label">{{ item.label }}</span>
              </button>
            </nav>
            <div class="actions">
              <button type="button" class="hf-ib" aria-label="Cập nhật dữ liệu" title="Cập nhật dữ liệu" @click="refresh">
                <RefreshCw :size="20" :stroke-width="1.8" :class="{ 'hf-spin': data.loading.value }" aria-hidden="true" />
              </button>
              <button type="button" class="hf-ib" aria-label="Kết nối dữ liệu" title="Kết nối dữ liệu" @click="emit('settings', 'integrations')">
                <Plug :size="20" :stroke-width="1.8" aria-hidden="true" />
              </button>
              <button type="button" class="hf-ib" aria-label="Hồ sơ" title="Hồ sơ" @click="emit('settings', 'profile')">
                <UserRound :size="20" :stroke-width="1.8" aria-hidden="true" />
              </button>
              <button type="button" class="hf-ib dk" aria-label="Đóng Dashboard" title="Đóng" @click="close">
                <X :size="20" :stroke-width="2" aria-hidden="true" />
              </button>
            </div>
          </div>
          <div class="row2">
            <h1>{{ TITLES[tab] }}</h1>
            <div class="chips">
              <span class="hf-chip"><CalendarDays :size="15" aria-hidden="true" />Hôm nay, {{ ddmmyyyy(data.today) }}</span>
              <span v-if="goalLabel" class="hf-chip">Mục tiêu: <b class="ink">{{ goalLabel }}</b></span>
              <span v-else class="hf-chip">Chưa đặt mục tiêu · <button type="button" class="hf-lnk" @click="emit('settings', 'profile')">Thiết lập</button></span>
              <span class="hf-chip" :class="{ wn: sync.warn }" role="status"><span class="sync-dot" :style="{ background: sync.dot }" />{{ sync.text }}</span>
            </div>
          </div>
        </header>

        <div class="body">
          <Transition name="hf-fade"><div v-show="tab === 'today'" class="pane">
            <TodayTab :data="data" @detail="detail = $event" @settings="emit('settings', $event)" @ask="emit('ask', $event)"
                      @prefill="chat" @create-plan="emit('create-plan')" @plan="pick('plan')" />
          </div></Transition>
          <Transition name="hf-fade"><div v-show="tab === 'progress'" class="pane">
            <ProgressTab :data="data" @settings="emit('settings', $event)" @prefill="chat" @create-plan="emit('create-plan')" />
          </div></Transition>
          <Transition name="hf-fade"><div v-show="tab === 'plan'" class="pane">
            <PlanTab :data="data" @create-plan="emit('create-plan')" @ask="emit('ask', $event)" />
          </div></Transition>
          <Transition name="hf-fade"><div v-if="mapOpened" v-show="tab === 'map'" class="pane">
            <MapTab :busy="busy" :revision="revision" @ask="emit('ask', $event)" />
          </div></Transition>

          <Transition name="hf-sheet"><ReadinessDetail v-if="tab === 'today' && detail === 'ready'" :assessment="data.health.value?.assessment ?? null"
                           :connection="connection" @back="detail = ''" @ask="emit('ask', $event)" @logged="data.refresh()" /></Transition>
          <Transition name="hf-sheet"><WorkoutDetail v-if="tab === 'today' && detail === 'workout'" :plan="data.plan.value" :today="data.today"
                         @back="detail = ''" @done="say" @changed="data.refresh()" /></Transition>
          <Transition name="hf-sheet"><NutritionDetail v-if="tab === 'today' && detail === 'nutrition'" :meals="data.mealsToday.value"
                           :targets="data.targets.value" @back="detail = ''" @prefill="chat" /></Transition>
        </div>
      </motion.div>
      </div>
    </div>
    </AnimatePresence>
    <HfToast :message="toast" />
  </Teleport>
</template>

<style scoped>
.dash-root { position: fixed; inset: 0; z-index: 45; }
.scrim { z-index: 0; }
.center { position: absolute; inset: 24px 0; display: flex; justify-content: center; pointer-events: none; z-index: 1; }
.modal {
  width: min(92vw, 1440px); height: 100%; pointer-events: auto;
  background: var(--hf-stage); border-radius: 30px; box-shadow: 0 40px 120px var(--hf-shadow-2);
  display: flex; flex-direction: column; overflow: hidden; outline: none;
}
.mh { padding: 18px 28px 14px; display: flex; flex-direction: column; gap: 12px; flex: none; }
.row1 { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 16px; }
.tabs { display: flex; gap: 2px; background: var(--hf-card); border-radius: 999px; padding: 4px; overflow-x: auto; max-width: 100%; margin: 0 auto; scrollbar-width: none; }
.tab { position: relative; border: 0; background: transparent; border-radius: 999px; padding: 0 18px; min-height: 40px; font-size: 14px; font-weight: 500; color: var(--hf-sub-2); white-space: nowrap; }
.tab { transition: color var(--hf-dur-fast) var(--hf-ease-out); }
.tab:hover:not(.on) { color: var(--hf-ink); }
.tab.on { color: var(--hf-on-ink); }
.tab-ind { position: absolute; inset: 0; border-radius: 999px; background: var(--hf-ink); }
.tab-label { position: relative; }
.actions { display: flex; gap: 8px; margin-left: auto; }
.row2 { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px 24px; flex-wrap: wrap; }
h1 { margin: 0; font-size: 40px; line-height: 1.05; font-weight: 700; letter-spacing: -0.02em; }
.chips { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.ink { color: var(--hf-ink); }
.sync-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.body { position: relative; flex: 1; min-height: 0; }
.pane { position: absolute; inset: 0; overflow-y: auto; padding: 4px 28px 28px; }
.body > .layer { position: absolute; inset: 0; overflow-y: auto; background: var(--hf-stage); padding: 4px 28px 28px; z-index: 2; }
@media (max-width: 760px) {
  .center { inset: 0; }
  .modal { width: 100%; border-radius: 0; }
  .mh { padding: 14px 16px 10px; }
  .pane, .body > .layer { padding: 4px 16px 24px; }
  .tabs { margin: 0; order: 3; width: 100%; }
  h1 { font-size: 30px; }
}
</style>
