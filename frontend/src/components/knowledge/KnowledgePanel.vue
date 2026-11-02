<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { ChevronsDown, ChevronsDownUp, ChevronsUp, History, LayoutGrid, Maximize2, Minus, Orbit, Plus, RefreshCw, X } from 'lucide-vue-next'
import ConstellationCanvas from './ConstellationCanvas.vue'
import KnowledgeDashboard from './KnowledgeDashboard.vue'
import KnowledgeInspector from './KnowledgeInspector.vue'
import KnowledgeTimeline from './KnowledgeTimeline.vue'
import TimeWindow from './TimeWindow.vue'
import { localDay, shiftDay } from './dashboard/dashboardData'
import { ancestors, collapse, indexTree, visibleIds } from './knowledgeTree'
import { centreOn, clampDay, dayDiff, rangeLength, recentRange, sameRange } from './timeWindow'
import { useKnowledgeGraph, type DayRange } from '@/composables/useKnowledgeGraph'
import { useResizable } from '@/composables/useResizable'
import { useKnowledgeHealthSync } from '@/features/health-integration/useKnowledgeHealthSync'
import { hubColor, hubTheme, type KnowledgeHub } from '@/types/knowledge'

const props = defineProps<{ busy: boolean; activity: string; revision: number }>()
const { message: healthSyncMessage, revision: healthRevision } = useKnowledgeHealthSync(() => schedule(0, 5000))
const emit = defineEmits<{ close: []; 'open-settings': [tab: 'profile' | 'integrations'] }>()
type Tab = 'overview' | 'map' | 'timeline'
const tabs: { id: Tab; label: string; icon: typeof Orbit }[] = [
  { id: 'overview', label: 'Tổng quan', icon: LayoutGrid },
  { id: 'map', label: 'Bản đồ', icon: Orbit },
  { id: 'timeline', label: 'Dòng thời gian', icon: History },
]
const hubs = Object.keys(hubTheme) as KnowledgeHub[]
// Tổng quan và dòng thời gian đọc các bản ghi gần đây; bản đồ chỉ vẽ các ngày đã chọn.
const { graph, loading, refresh } = useKnowledgeGraph()
const today = localDay(new Date())
// Cho đến khi server báo lịch sử còn lưu, giả định mặc định là 90 ngày.
const fallbackMin = shiftDay(today, -90)
const NO_DENSITY = {}
const range = shallowRef<DayRange>(recentRange(fallbackMin, today))
const { graph: atlas, loading: atlasLoading, failed: atlasFailed, refresh: refreshAtlas } = useKnowledgeGraph(() => range.value)
const tab = ref<Tab>('overview')
// Chỉ là trạng thái trình bày; id là khoá graph ổn định, nên nhánh đang mở vẫn giữ qua các lần làm mới.
const expanded = shallowRef<Set<string>>(new Set())
const selectedId = ref<string>()
const pending = shallowRef<string>()
const canvas = ref<InstanceType<typeof ConstellationCanvas>>()
const index = computed(() => indexTree(atlas.value))
const recentIndex = computed(() => indexTree(graph.value))
const visible = computed(() => visibleIds(index.value, expanded.value))
const selected = computed(() => (selectedId.value ? index.value.byId.get(selectedId.value) : undefined))
const bounds = computed(() => ({ min: atlas.value.window?.min ?? fallbackMin, max: atlas.value.window?.max ?? today }))
const shown = computed(() => (tab.value === 'map' ? atlas.value : graph.value))
const records = computed(() => shown.value.nodes.filter(node => !['User', 'Hub', 'Group'].includes(node.kind)).length)
const activeTab = computed(() => tabs.findIndex(item => item.id === tab.value))
const refreshing = computed(() => (tab.value === 'map' ? atlasLoading.value : loading.value))

function relative(iso?: string | null) {
  if (!iso) return ''
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000
  if (Number.isNaN(seconds)) return ''
  if (seconds < 60) return 'vừa cập nhật'
  if (seconds < 3600) return `cập nhật ${Math.round(seconds / 60)} phút trước`
  if (seconds < 86400) return `cập nhật ${Math.round(seconds / 3600)} giờ trước`
  return `cập nhật ${new Date(iso).toLocaleDateString('vi-VN')}`
}

const statusText = computed(() => {
  const status = shown.value.status
  if (status === 'loading') return 'Đang đọc bản đồ…'
  if (status === 'ok') {
    const span = tab.value === 'map' ? `${rangeLength(range.value)} ngày` : ''
    return [`${records.value} mục tri thức`, span, relative(shown.value.model_at ?? shown.value.generated_at)].filter(Boolean).join(' · ')
  }
  if (status === 'empty') return 'Chưa có dữ liệu để kết nối'
  if (status === 'warming') return 'Đang xây dựng bản đồ'
  return 'Chưa kết nối được bản đồ'
})
// Cửa sổ rỗng không có nghĩa là lịch sử rỗng: chỉ cách tìm phần còn lại.
const quietWindow = computed(() => atlas.value.status === 'empty' && Object.keys(atlas.value.window?.density ?? {}).length > 0)
const skyText = computed(() => quietWindow.value ? 'Những ngày này chưa có hoạt động nào' : ({
  loading: 'Đang tìm các vì sao…', warming: 'Đang xây dựng bản đồ tri thức', unavailable: 'Chưa kết nối được bản đồ',
  blocked: 'Bản đồ hiện không khả dụng', empty: 'Bầu trời của bạn đang chờ những dấu sao đầu tiên',
} as Record<string, string>)[atlas.value.status] ?? '')
const skyHint = computed(() => quietWindow.value
  ? 'Kéo thanh thời gian phía trên hoặc chọn “30 ngày” để xem thêm.'
  : 'Ghi bữa ăn, số đo, buổi tập hoặc trò chuyện với trợ lý để bắt đầu.')

/* ---------- Cửa sổ bản đồ: một request dù có bao nhiêu tác nhân kích hoạt trong một tick ---------- */
let atlasOpened = false
let atlasQueued = false
let requested: DayRange | undefined
let adopted: DayRange | undefined
function requestAtlas() {
  if (atlasQueued) return
  atlasQueued = true
  queueMicrotask(() => {
    atlasQueued = false
    requested = range.value
    refreshAtlas()
  })
}
function refreshAll() {
  refresh()
  if (atlasOpened) requestAtlas()
}
watch(tab, value => { if (value === 'map' && !atlasOpened) { atlasOpened = true; requestAtlas() } })
watch(range, value => {
  if (sameRange(value, adopted)) {
    adopted = undefined
    return
  }
  if (atlasOpened) requestAtlas()
})
watch(() => atlas.value.window, (window, previous) => {
  // Câu trả lời cho khoảng cũ hơn có thể tới trong khi khoảng mới hơn đang được hỏi.
  if (!window || !sameRange(requested, range.value)) return
  // Cửa sổ kết thúc ở ngày mới nhất vẫn kết thúc ở đó sau nửa đêm.
  if (previous && range.value.end === previous.max && window.max > previous.max) {
    range.value = { start: shiftDay(range.value.start, dayDiff(previous.max, window.max)), end: window.max }
    return
  }
  const drawn = { start: window.start, end: window.end }
  // Server kẹp vào lịch sử còn lưu; chấp nhận điều đó mà không hỏi lại.
  if (!sameRange(drawn, range.value)) {
    adopted = drawn
    range.value = drawn
  }
})

function toggle(id: string) {
  const node = index.value.byId.get(id)
  if (!node || !node.children || node.kind === 'User') return
  expanded.value = expanded.value.has(id) ? collapse(index.value, expanded.value, id) : new Set([...expanded.value, id])
}

/** Chạm lần đầu mở một nhánh và chọn nó; chạm vào nhánh đang mở và đang chọn thì thu gọn nó. */
function activate(id: string) {
  const node = index.value.byId.get(id)
  if (!node) return
  const again = selectedId.value === id
  selectedId.value = id
  if (node.children && node.kind !== 'User' && (!expanded.value.has(id) || again)) toggle(id)
}

function focusLater(id: string, attempt = 0) {
  // Bản đồ được gắn sau hiệu ứng chuyển tab; chờ nó thay vì đoán thời gian trễ.
  if (canvas.value) canvas.value.focus(id)
  else if (attempt < 12) setTimeout(() => focusLater(id, attempt + 1), 80)
}

/** Mở mọi node tổ tiên của một node trên bản đồ, chọn nó và bay tới nó. */
function show(id: string) {
  const node = index.value.byId.get(id)
  if (!node) return
  const opened = ancestors(index.value, id).filter(item => item !== index.value.root)
  if (node.children && node.kind !== 'User') opened.push(id)
  expanded.value = new Set([...expanded.value, ...opened])
  selectedId.value = id
  nextTick(() => setTimeout(() => focusLater(id), 120))
}

const DATED = new Set(['BodyMetric', 'Meal', 'MealItem', 'Training', 'TrainingItem', 'Run'])
/** Ngày địa phương bản ghi xảy ra, cho các bản ghi mà bản đồ chỉ vẽ theo ngày. */
function dayOf(id: string): string | undefined {
  const lookup = (key: string) => recentIndex.value.byId.get(key) ?? index.value.byId.get(key)
  let node = lookup(id)
  if (node?.kind === 'Intent') {
    const last = graph.value.intents.find(item => item.node_id === id)?.last_at
    return last ? localDay(last) : undefined
  }
  if (!node || !DATED.has(node.kind)) return undefined
  while (node && !node.at && node.parent) node = lookup(node.parent)
  return node?.at ? localDay(node.at) : undefined
}

/** Chính bản ghi khi bản đồ vẽ nó, nếu không thì tổ tiên gần nhất được vẽ. */
function nearest(id: string): string | undefined {
  let current: string | null | undefined = id
  while (current && !index.value.byId.has(current)) current = recentIndex.value.byId.get(current)?.parent
  return current ?? index.value.root
}

function settle() {
  const id = pending.value
  pending.value = undefined
  const target = id && nearest(id)
  if (target) show(target)
}

/** Hiển thị một bản ghi được chọn từ tổng quan hoặc dòng thời gian, dời cửa sổ tới ngày của nó nếu cần. */
function reveal(id: string) {
  tab.value = 'map'
  const day = dayOf(id)
  const outside = !!day && (day < range.value.start || day > range.value.end)
  if (!outside && atlas.value.status !== 'loading' && !atlasLoading.value) {
    const target = nearest(id)
    if (target) show(target)
    return
  }
  pending.value = id
  if (outside) range.value = centreOn(range.value, clampDay(day, bounds.value.min, bounds.value.max), bounds.value.min, bounds.value.max)
}
watch(atlasLoading, (now, was) => { if (was && !now && pending.value) settle() })

function collapseAll() {
  expanded.value = new Set()
  selectedId.value = undefined
  setTimeout(() => canvas.value?.fit(), 600)
}

watch(index, current => {
  if (selectedId.value && !current.byId.has(selectedId.value)) selectedId.value = undefined
  const kept = [...expanded.value].filter(id => current.byId.has(id))
  if (kept.length !== expanded.value.size) expanded.value = new Set(kept)
})

/* ---------- Đổi kích thước: bảng từ mép trái, khung chi tiết từ mép trên ---------- */
const panel = useTemplateRef<HTMLElement>('panel')
const mapView = useTemplateRef<HTMLElement>('mapView')
const toolbar = useTemplateRef<HTMLElement>('toolbar')
const dockElement = useTemplateRef<HTMLElement>('dockPane')
const viewport = shallowRef(window.innerWidth)
const width = reactive(useResizable({
  axis: 'x', grow: -1, step: 32, storageKey: 'hercfit:knowledge-panel-width',
  measure: () => panel.value?.offsetWidth ?? 720,
  bounds: () => {
    const screen = window.innerWidth
    if (screen <= 1000) return { min: Math.min(360, screen), max: screen }
    // Gắn bên cạnh khung chat, khung chat vẫn giữ đủ chỗ để đọc hội thoại.
    const main = panel.value?.parentElement?.querySelector<HTMLElement>(':scope > main')
    const shared = (main?.offsetWidth ?? 0) + (panel.value?.offsetWidth ?? 0)
    return { min: 380, max: Math.max(380, (shared || screen) - 400) }
  },
}))
const dockBounds = () => ({ min: 96, max: Math.max(96, (mapView.value?.clientHeight ?? 560) - (toolbar.value?.offsetHeight ?? 0) - 120) })
const dock = reactive(useResizable({
  axis: 'y', grow: -1, step: 32, storageKey: 'hercfit:knowledge-inspector-height',
  measure: () => dockElement.value?.offsetHeight ?? 200,
  bounds: dockBounds,
}))
const resizable = computed(() => viewport.value > 640)
const naturalWidth = computed(() => Math.round(Math.min(860, viewport.value <= 1000 ? viewport.value : viewport.value * .56)))
const panelStyle = computed(() => (resizable.value && width.size ? { width: `${width.size}px` } : undefined))
const dockStyle = computed(() => (dock.size == null ? undefined : { height: `${dock.size}px`, maxHeight: 'none' }))
const mapHeight = shallowRef(0)
// Khung chi tiết cao đọc như một trang: mọi node con, chữ lớn hơn và ảnh to hơn.
const roomy = computed(() => (dock.size ?? 0) >= 300)
const tall = computed(() => dock.size != null && dock.size > mapHeight.value * .5)

let mapObserver: ResizeObserver | undefined
watch(mapView, element => {
  mapObserver?.disconnect()
  if (!element) return
  mapObserver = new ResizeObserver(([entry]) => {
    mapHeight.value = entry?.contentRect.height ?? 0
    if (!dock.dragging) dock.fit()
  })
  mapObserver.observe(element)
})

function settleDock() {
  // Giữ ngôi sao đã chọn trong tầm nhìn phía trên khung chi tiết khi hiệu ứng chiều cao kết thúc.
  setTimeout(() => { if (selectedId.value) canvas.value?.focus(selectedId.value) }, 360)
}

async function expandDock() {
  if (dock.size == null) {
    // Chiều cao chỉ chuyển động giữa các độ dài cụ thể, nên bắt đầu từ chiều cao tự nhiên.
    dock.set(dockElement.value?.offsetHeight ?? 200, false)
    await nextTick()
    await new Promise(requestAnimationFrame)
  }
  dock.set(dockBounds().max)
  settleDock()
}

function toggleDock() {
  if (!tall.value) return expandDock()
  dock.set(Math.round(mapHeight.value * .38))
  settleDock()
}

function onResize() {
  viewport.value = window.innerWidth
  width.fit()
}

let timers: ReturnType<typeof setTimeout>[] = []
function schedule(...delays: number[]) {
  timers.forEach(clearTimeout)
  timers = delays.map(delay => setTimeout(() => { if (!props.busy) refreshAll() }, delay))
}
// Một lượt đã xong tới graph trong vài giây; hồ sơ suy ra đến sau đó.
watch(() => props.busy, (busy, was) => { if (was && !busy) schedule(1500, 5000) })
watch(() => props.revision, () => { if (!props.busy) schedule(900) })

let chatObserver: ResizeObserver | undefined
function keydown(event: KeyboardEvent) { if (event.key === 'Escape') emit('close') }
onMounted(() => {
  refresh()
  window.addEventListener('keydown', keydown)
  window.addEventListener('resize', onResize)
  width.fit()
  // Khung chat co lại khi thanh bên của nó mở; giữ cho bảng không chèn ép nó.
  const main = panel.value?.parentElement?.querySelector<HTMLElement>(':scope > main')
  if (main) {
    chatObserver = new ResizeObserver(() => { if (!width.dragging) width.fit() })
    chatObserver.observe(main)
  }
})
onUnmounted(() => {
  timers.forEach(clearTimeout)
  chatObserver?.disconnect()
  mapObserver?.disconnect()
  window.removeEventListener('keydown', keydown)
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <aside ref="panel" class="observatory" :class="{ resizing: width.dragging }" :style="panelStyle" aria-label="Bản đồ tri thức cá nhân">
    <span v-if="resizable" class="width-grip" role="separator" aria-orientation="vertical" tabindex="0"
          aria-label="Độ rộng bảng tri thức" aria-valuemin="380" :aria-valuemax="viewport" :aria-valuenow="width.size ?? naturalWidth"
          title="Kéo để đổi độ rộng · nhấp đúp để đặt lại" @pointerdown="width.start" @keydown="width.keydown" @dblclick="width.reset">
      <i aria-hidden="true" />
    </span>

    <header class="head">
      <div>
        <p class="eyeline">THE OLYMPUS OBSERVATORY · ATLAS CÁ NHÂN</p>
        <h2>Bản đồ <em>tri thức</em></h2>
        <p class="subtitle">Những gì trợ lý ghi nhớ về bạn, kết tinh từ bữa ăn, buổi tập, số đo và các cuộc trò chuyện.</p>
      </div>
      <button class="icon-button" type="button" aria-label="Đóng bản đồ" @click="emit('close')"><X :size="18" /></button>
    </header>

    <div class="status" aria-live="polite">
      <span class="status-dot" :class="{ ready: shown.status === 'ok', busy }" />
      <span class="status-text">{{ busy ? (activity || 'Trợ lý đang xử lý…') : statusText }}</span>
      <button class="icon-button refresh" type="button" aria-label="Cập nhật bản đồ" :disabled="refreshing" @click="refreshAll">
        <RefreshCw :size="13" :class="{ spinning: refreshing }" />
      </button>
    </div>

    <p v-if="healthSyncMessage" role="status" class="px-5 py-1 text-xs text-outline">{{ healthSyncMessage }}</p>
    <nav class="tabs" role="tablist" aria-label="Chế độ xem" :style="{ '--tabs': tabs.length }">
      <span class="tab-glider" :style="{ transform: `translateX(${activeTab * 100}%)` }" aria-hidden="true" />
      <button v-for="item in tabs" :key="item.id" type="button" role="tab" :aria-selected="tab === item.id"
              :class="{ active: tab === item.id }" @click="tab = item.id">
        <component :is="item.icon" :size="13" :stroke-width="1.7" />{{ item.label }}
      </button>
    </nav>

    <div class="content">
      <Transition name="swap" mode="out-in">
        <KnowledgeDashboard v-if="tab === 'overview'" key="overview" class="scroll" :graph="graph"
                            :revision="healthRevision + revision" @explore="reveal"
                            @connect="emit('open-settings', 'integrations')" @edit-profile="emit('open-settings', 'profile')" />
        <div v-else-if="tab === 'map'" key="map" ref="mapView" class="map-view">
          <div ref="toolbar" class="map-toolbar">
            <div class="legend" role="toolbar" aria-label="Nhóm tri thức">
              <button v-for="hub in hubs" :key="hub" type="button" :class="{ open: expanded.has('hub:' + hub) }"
                      :style="{ '--accent': hubColor(hub) }" :disabled="!index.byId.get('hub:' + hub)?.children"
                      :aria-pressed="expanded.has('hub:' + hub)" @click="activate('hub:' + hub)">
                <i />{{ hubTheme[hub].label }}<small>{{ index.byId.get('hub:' + hub)?.children ?? 0 }}</small>
              </button>
            </div>
            <TimeWindow v-model="range" :min="bounds.min" :max="bounds.max" :density="atlas.window?.density ?? NO_DENSITY"
                        :drawn="atlas.window" :loading="atlasLoading" :failed="atlasFailed" @retry="requestAtlas" />
          </div>
          <div class="map-area">
            <ConstellationCanvas ref="canvas" :index="index" :visible="visible" :expanded="expanded" :selected-id="selectedId"
                                 @activate="activate" @clear="selectedId = undefined" />
            <div v-if="atlas.status !== 'ok'" class="empty-sky">
              <Orbit :size="32" :stroke-width="1" />
              <p>{{ skyText }}</p>
              <small>{{ skyHint }}</small>
              <button v-if="atlas.status === 'unavailable'" type="button" @click="requestAtlas">Thử kết nối lại</button>
            </div>
            <div class="map-controls">
              <button type="button" aria-label="Phóng to" @click="canvas?.zoom(1.25)"><Plus :size="15" /></button>
              <button type="button" aria-label="Thu nhỏ" @click="canvas?.zoom(.8)"><Minus :size="15" /></button>
              <button type="button" aria-label="Xem toàn bộ" @click="canvas?.fit()"><Maximize2 :size="14" /></button>
              <button type="button" aria-label="Thu gọn tất cả nhánh" @click="collapseAll"><ChevronsDownUp :size="14" /></button>
            </div>
          </div>
          <section ref="dockPane" class="inspector-dock" :class="{ resizing: dock.dragging }" :style="dockStyle" aria-label="Chi tiết mục đang chọn">
            <div class="dock-bar">
              <span class="dock-grip" role="separator" aria-orientation="horizontal" tabindex="0" aria-label="Chiều cao khung chi tiết"
                    aria-valuemin="96" :aria-valuenow="dock.size ?? undefined" title="Kéo lên để mở rộng · nhấp đúp để mở rộng hoặc thu gọn"
                    @pointerdown="dock.start" @keydown="dock.keydown" @dblclick="toggleDock">
                <i aria-hidden="true" />
              </span>
              <button type="button" class="dock-toggle" :aria-label="tall ? 'Thu gọn khung chi tiết' : 'Mở rộng khung chi tiết'"
                      :aria-expanded="tall" :title="tall ? 'Thu gọn' : 'Mở rộng để đọc chi tiết'" @click="toggleDock">
                <component :is="tall ? ChevronsDown : ChevronsUp" :size="14" />
              </button>
            </div>
            <KnowledgeInspector :key="selectedId ?? 'none'" class="inspector-pane" :node="selected" :index="index" :expanded="expanded"
                                :roomy="roomy" @select="show" @toggle="toggle" @expand="expandDock" />
          </section>
        </div>
        <KnowledgeTimeline v-else key="timeline" class="scroll" :events="graph.timeline" @explore="reveal" />
      </Transition>
    </div>

    <footer>RIÊNG TƯ · CHỈ BẠN THẤY <span>{{ graph.lag_ms != null && graph.lag_ms > 5000 ? 'ĐANG ĐỒNG BỘ…' : 'OLYMPUS / ATLAS' }}</span></footer>
  </aside>
</template>

<style scoped>
.observatory { --gutter: clamp(16px, 3.2cqi, 30px); container: observatory / inline-size; position: relative; z-index: 30; display: flex; flex-direction: column; width: min(860px, 56vw); max-width: 100vw; height: 100dvh; background: light-dark(#f3f2ef, #101216); border-left: 1px solid light-dark(#87671a26, #d4b77d26); color: light-dark(#2f2d28, #e5e2dc); box-shadow: -30px 0 90px light-dark(#0000002a, #0005); animation: observatory-arrive 500ms cubic-bezier(.2,.8,.2,1) both; }
.width-grip { position: absolute; z-index: 6; top: 0; bottom: 0; left: -8px; width: 16px; display: flex; align-items: center; justify-content: center; cursor: col-resize; touch-action: none; outline: none; }
.width-grip::before { content: ''; position: absolute; top: 0; bottom: 0; left: 7px; width: 2px; background: linear-gradient(transparent, light-dark(#87671a80, #d4b77d80) 18%, light-dark(#87671a80, #d4b77d80) 82%, transparent); opacity: 0; transition: opacity 220ms; }
.width-grip i { position: relative; width: 4px; height: 44px; border-radius: 4px; background: light-dark(#87671a3d, #d4b77d3d); transition: height 260ms cubic-bezier(.2,.8,.2,1), background 220ms, box-shadow 220ms; }
.width-grip:hover::before, .width-grip:focus-visible::before, .resizing .width-grip::before { opacity: 1; }
.width-grip:hover i, .width-grip:focus-visible i, .resizing .width-grip i { height: 76px; background: light-dark(#886f35, #e6cf9e); box-shadow: 0 0 16px light-dark(#87671a99, #d4b77d99); }
.width-grip:focus-visible i { outline: 2px solid light-dark(#867854, #f3e6c6); outline-offset: 3px; }
.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: clamp(18px, 3cqi, 28px) var(--gutter) 14px; }
.eyeline { font: 8px 'JetBrains Mono', monospace; letter-spacing: .2em; color: light-dark(#7d6431, #bda77c); margin: 0 0 10px; }
.head h2 { font-family: 'Playfair Display', serif; font-size: clamp(24px, 3.5cqi, 38px); font-weight: 400; line-height: 1.15; letter-spacing: -.04em; margin: 0; }
.head h2 em { color: light-dark(#87671a, #d4b77d); font-weight: 400; }
.subtitle { font-size: 11px; color: light-dark(#6d6b67, #8e8c88); margin: 9px 0 0; max-width: 460px; line-height: 1.6; }
.icon-button { display: grid; place-items: center; flex-shrink: 0; width: 32px; height: 32px; border: 1px solid light-dark(#18181812, #ffffff12); border-radius: 50%; color: light-dark(#5a564d, #aca89e); background: transparent; transition: color 220ms, background 220ms, transform 300ms; }
.icon-button:hover { color: light-dark(#88754c, #f0dfba); background: light-dark(#87671a12, #d4b77d12); }
.icon-button:active { transform: scale(.9); }
.status { display: flex; align-items: center; gap: 8px; margin: 0 var(--gutter); padding: 9px 0; border-top: 1px solid light-dark(#18181809, #ffffff09); color: light-dark(#63605a, #9d9a93); font: 9px 'JetBrains Mono', monospace; min-width: 0; }
.status-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.status-dot { width: 6px; height: 6px; background: light-dark(#908f8a, #696863); border-radius: 50%; flex-shrink: 0; }
.status-dot.ready { background: light-dark(#87671a, #d4b77d); box-shadow: 0 0 8px light-dark(#87671a66, #d4b77d66); }
.status-dot.busy { background: light-dark(#715d9d, #b9a9e3); animation: pulse 1.4s ease-in-out infinite; }
.refresh { margin-left: auto; width: 26px; height: 26px; }
.tabs { position: relative; display: grid; grid-template-columns: repeat(var(--tabs, 3), 1fr); margin: 4px var(--gutter) 0; padding: 3px; border: 1px solid light-dark(#1818180c, #ffffff0c); border-radius: 12px; background: light-dark(#eeedeb, #0c0d11); }
.tabs button { position: relative; z-index: 1; display: flex; align-items: center; justify-content: center; gap: 7px; padding: 8px 6px; font-size: 11px; color: light-dark(#6e6b64, #8f8c84); border-radius: 9px; white-space: nowrap; transition: color 260ms; }
.tabs button.active { color: light-dark(#867854, #f3e6c6); }
.tabs button:focus-visible { outline: 1px solid light-dark(#87671a88, #d4b77d88); }
.tab-glider { position: absolute; top: 3px; bottom: 3px; left: 3px; width: calc((100% - 6px) / var(--tabs, 3)); border-radius: 9px; background: linear-gradient(135deg, light-dark(#87671a26, #d4b77d26), light-dark(#87671a10, #d4b77d10)); border: 1px solid light-dark(#87671a33, #d4b77d33); transition: transform 380ms cubic-bezier(.2,.8,.2,1); }
.content { position: relative; flex: 1; min-height: 0; display: flex; flex-direction: column; margin-top: 10px; }
.scroll { flex: 1; overflow-y: auto; }
.map-view { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.map-toolbar { flex-shrink: 0; }
.legend { display: flex; gap: 6px; overflow-x: auto; padding: 4px var(--gutter) 10px; scrollbar-width: none; }
.legend button { --accent: light-dark(#87671a, #d4b77d); display: flex; align-items: center; gap: 7px; white-space: nowrap; padding: 6px 11px; border: 1px solid light-dark(#1818180d, #ffffff0d); border-radius: 20px; font-size: 10px; color: light-dark(#605d55, #a29f96); transition: color 220ms, border-color 220ms, background 220ms; }
.legend button i { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 8px var(--accent); }
.legend button small { font: 9px 'JetBrains Mono', monospace; color: light-dark(#8d8982, #6f6c65); }
.legend button:hover:not(:disabled), .legend button.open { border-color: color-mix(in srgb, var(--accent) 45%, transparent); background: color-mix(in srgb, var(--accent) 8%, transparent); color: light-dark(#302919, #efe6d2); }
.legend button:disabled { opacity: .35; }
.map-area { position: relative; flex: 1; min-height: 120px; border-block: 1px solid light-dark(#18181809, #ffffff09); color-scheme: dark; }
/* Bản đồ sao là bầu trời đêm ở cả hai theme: các màu light-dark() bên trong lấy giá trị tối. */
.map-controls { position: absolute; right: 16px; bottom: 16px; display: flex; background: light-dark(#faf9f6e8, #13151be8); border: 1px solid light-dark(#18181815, #ffffff15); border-radius: 24px; overflow: hidden; backdrop-filter: blur(12px); box-shadow: 0 6px 24px light-dark(#0000001a, #0003); }
.map-controls button { padding: 10px; color: light-dark(#4e493a, #c1bba9); transition: color 220ms, background 220ms; }
.map-controls button:hover { color: light-dark(#88754c, #f0dfba); background: light-dark(#87671a12, #d4b77d12); }
.empty-sky { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 12px; text-align: center; pointer-events: none; padding: 35px; color: light-dark(#776641, #b9aa89); }
.empty-sky p { font: 20px 'Playfair Display', serif; max-width: 320px; margin: 0; }
.empty-sky small { font-size: 11px; color: light-dark(#74736d, #85847e); }
.empty-sky button { pointer-events: auto; border-bottom: 1px solid light-dark(#776641, #b9aa89); font-size: 11px; }
.inspector-dock { position: relative; flex: none; display: flex; flex-direction: column; min-height: 0; max-height: 38%; background: linear-gradient(light-dark(#faf9f6, #13151b), light-dark(#f3f2ef, #101216) 64px); box-shadow: 0 -18px 40px light-dark(#0000001a, #0003); transition: height 340ms cubic-bezier(.2,.8,.2,1); }
.inspector-dock.resizing { transition: none; }
.dock-bar { position: relative; flex: none; height: 22px; }
.dock-grip { position: absolute; inset: -8px 56px 0; display: flex; align-items: center; justify-content: center; padding-top: 8px; cursor: row-resize; touch-action: none; outline: none; }
.dock-grip i { width: 42px; height: 4px; border-radius: 4px; background: light-dark(#18181821, #ffffff21); transition: width 260ms cubic-bezier(.2,.8,.2,1), background 220ms, box-shadow 220ms; }
.dock-grip:hover i, .dock-grip:focus-visible i, .resizing .dock-grip i { width: 72px; background: light-dark(#886f35, #e6cf9e); box-shadow: 0 0 14px light-dark(#87671a99, #d4b77d99); }
.dock-grip:focus-visible i { outline: 2px solid light-dark(#867854, #f3e6c6); outline-offset: 3px; }
.dock-toggle { position: absolute; top: 3px; right: calc(var(--gutter) - 6px); display: grid; place-items: center; width: 26px; height: 22px; border-radius: 8px; color: light-dark(#605d55, #a29f96); transition: color 200ms, background 200ms; }
.dock-toggle:hover { color: light-dark(#88754c, #f0dfba); background: light-dark(#87671a14, #d4b77d14); }
.inspector-pane { flex: 1; min-height: 0; }
footer { display: flex; justify-content: space-between; padding: 12px var(--gutter); border-top: 1px solid light-dark(#1818180b, #ffffff0b); color: light-dark(#88877f, #706f67); font: 8px 'JetBrains Mono', monospace; letter-spacing: .12em; }
.spinning { animation: spin 1s linear infinite; }
.swap-enter-active, .swap-leave-active { transition: opacity 220ms ease, transform 260ms cubic-bezier(.2,.8,.2,1); }
.swap-enter-from { opacity: 0; transform: translateY(6px); }
.swap-leave-to { opacity: 0; transform: translateY(-4px); }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes pulse { 0%, 100% { opacity: .45; } 50% { opacity: 1; } }
@keyframes observatory-arrive { from { opacity: 0; transform: translateX(24px); } to { opacity: 1; transform: translateX(0); } }
/* Chính độ rộng của bảng, không phải của màn hình, quyết định cách sắp xếp nội dung. */
@container observatory (max-width: 480px) {
  .subtitle { display: none; }
  .tabs button { gap: 4px; font-size: 10px; padding: 8px 3px; }
}
@container observatory (min-width: 980px) {
  .subtitle { max-width: 620px; font-size: 12px; }
  .empty-sky p { font-size: 24px; max-width: 420px; }
}
@media (max-width: 1000px) { .observatory { position: fixed; inset: 0 0 0 auto; width: min(860px, 100vw); } }
@media (prefers-reduced-motion: reduce) {
  .observatory, .spinning, .status-dot.busy { animation: none; }
  .tab-glider, .swap-enter-active, .swap-leave-active, .inspector-dock, .width-grip i, .dock-grip i { transition: none; }
}
</style>
