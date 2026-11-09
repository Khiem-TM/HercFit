<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, shallowRef, watch } from 'vue'
import { Maximize, Minimize2, Minus, Plus, Scan } from 'lucide-vue-next'
import ConstellationCanvas from '@/components/knowledge/ConstellationCanvas.vue'
import KnowledgeInspector from '@/components/knowledge/KnowledgeInspector.vue'
import TimeWindow from '@/components/knowledge/TimeWindow.vue'
import { localDay, shiftDay } from '@/components/knowledge/dashboard/dashboardData'
import { ancestors, collapse, indexTree, visibleIds } from '@/components/knowledge/knowledgeTree'
import { dayDiff, recentRange, sameRange } from '@/components/knowledge/timeWindow'
import { useKnowledgeGraph, type DayRange } from '@/composables/useKnowledgeGraph'
import { hubColor, hubTheme, type KnowledgeHub } from '@/types/knowledge'

/** Bản đồ dữ liệu: mọi điều trợ lý biết về bạn theo nhóm, vẽ lại theo khoảng thời gian đã chọn. */
const props = defineProps<{ busy: boolean; revision: number }>()
const emit = defineEmits<{ ask: [text: string] }>()

const hubs = Object.keys(hubTheme) as KnowledgeHub[]
const today = localDay(new Date())
// Cho đến khi server báo lịch sử còn lưu, giả định mặc định là 90 ngày.
const fallbackMin = shiftDay(today, -90)
const NO_DENSITY = {}
const range = shallowRef<DayRange>(recentRange(fallbackMin, today, 15))
const { graph: atlas, loading, failed, refresh } = useKnowledgeGraph(() => range.value)
const expanded = shallowRef<Set<string>>(new Set())
const selectedId = shallowRef<string>()
const canvas = shallowRef<InstanceType<typeof ConstellationCanvas>>()
const wide = shallowRef(false)
const index = computed(() => indexTree(atlas.value))
const visible = computed(() => visibleIds(index.value, expanded.value))
const selected = computed(() => (selectedId.value ? index.value.byId.get(selectedId.value) : undefined))
const bounds = computed(() => ({ min: atlas.value.window?.min ?? fallbackMin, max: atlas.value.window?.max ?? today }))
const quiet = computed(() => atlas.value.status === 'empty' && Object.keys(atlas.value.window?.density ?? {}).length > 0)
const sparse = computed(() => atlas.value.status === 'empty' && !quiet.value)
const skyText = computed(() => quiet.value ? 'Những ngày này chưa có hoạt động nào' : ({
  loading: 'Đang đọc bản đồ…', warming: 'Đang xây dựng bản đồ dữ liệu', unavailable: 'Chưa kết nối được bản đồ',
  blocked: 'Bản đồ hiện không khả dụng', empty: 'Bản đồ đang chờ những dữ liệu đầu tiên',
} as Record<string, string>)[atlas.value.status] ?? '')

/* ---------- một request cho mỗi lần đổi khoảng, nhận khoảng server kẹp lại ---------- */
let queued = false
let requested: DayRange | undefined
let adopted: DayRange | undefined
function request() {
  if (queued) return
  queued = true
  queueMicrotask(() => { queued = false; requested = range.value; void refresh() })
}
watch(range, value => {
  if (sameRange(value, adopted)) { adopted = undefined; return }
  request()
})
watch(() => atlas.value.window, (window, previous) => {
  if (!window || !sameRange(requested, range.value)) return
  if (previous && range.value.end === previous.max && window.max > previous.max) {
    range.value = { start: shiftDay(range.value.start, dayDiff(previous.max, window.max)), end: window.max }
    return
  }
  const drawn = { start: window.start, end: window.end }
  if (!sameRange(drawn, range.value)) { adopted = drawn; range.value = drawn }
})
watch(index, current => {
  if (selectedId.value && !current.byId.has(selectedId.value)) selectedId.value = undefined
  const kept = [...expanded.value].filter(id => current.byId.has(id))
  if (kept.length !== expanded.value.size) expanded.value = new Set(kept)
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
function show(id: string) {
  const node = index.value.byId.get(id)
  if (!node) return
  const opened = ancestors(index.value, id).filter(item => item !== index.value.root)
  if (node.children && node.kind !== 'User') opened.push(id)
  expanded.value = new Set([...expanded.value, ...opened])
  selectedId.value = id
  nextTick(() => setTimeout(() => canvas.value?.focus(id), 120))
}
function fit() {
  expanded.value = new Set()
  selectedId.value = undefined
  setTimeout(() => canvas.value?.fit(), 600)
}
async function toggleWide() {
  wide.value = !wide.value
  await nextTick()
  setTimeout(() => canvas.value?.fit(), 120)
}

const askText = computed(() => {
  const node = selected.value
  const span = `${range.value.start.slice(8, 10)}/${range.value.start.slice(5, 7)} – ${range.value.end.slice(8, 10)}/${range.value.end.slice(5, 7)}`
  return node ? `Giải thích giúp mình về: ${node.label} (${span})` : `Tóm tắt dữ liệu của mình trong khoảng ${span}`
})

let timers: ReturnType<typeof setTimeout>[] = []
function schedule(...delays: number[]) {
  timers.forEach(clearTimeout)
  timers = delays.map(delay => setTimeout(() => { if (!props.busy) request() }, delay))
}
watch(() => props.busy, (busy, was) => { if (was && !busy) schedule(1500, 5000) })
watch(() => props.revision, () => { if (!props.busy) schedule(900) })
onMounted(request)
onUnmounted(() => timers.forEach(clearTimeout))
</script>

<template>
  <div class="map">
    <div class="groups" role="group" aria-label="Mở nhóm trên bản đồ">
      <button v-for="hub in hubs" :key="hub" type="button" class="gchip" :aria-pressed="expanded.has('hub:' + hub)"
              :disabled="!index.byId.get('hub:' + hub)?.children" @click="activate('hub:' + hub)">
        <span class="gdot" :style="{ background: hubColor(hub) }" />{{ hubTheme[hub].label }}
        <span class="gcount">{{ index.byId.get('hub:' + hub)?.children ?? 0 }}</span>
      </button>
    </div>

    <section class="hf-card timeline">
      <TimeWindow v-model="range" :min="bounds.min" :max="bounds.max" :density="atlas.window?.density ?? NO_DENSITY"
                  :drawn="atlas.window" :loading="loading" :failed="failed" @retry="request" />
    </section>

    <div class="hf-grid">
      <section class="hf-card graph" :class="wide ? 'hf-c12' : 'hf-c8'">
        <div v-if="sparse" class="hf-info sparse">Bản đồ sẽ được bổ sung khi bạn khai báo hồ sơ, ghi bữa ăn, lập lịch tập và trò chuyện với trợ lý.</div>
        <div class="kgw">
          <ConstellationCanvas ref="canvas" :index="index" :visible="visible" :expanded="expanded" :selected-id="selectedId"
                               @activate="activate" @clear="selectedId = undefined" />
          <div v-if="atlas.status !== 'ok'" class="overlay">
            <p>{{ skyText }}</p>
            <button v-if="atlas.status === 'unavailable'" type="button" class="hf-btn sm" @click="request">Thử kết nối lại</button>
          </div>
          <div class="zctl" role="group" aria-label="Điều khiển bản đồ">
            <button type="button" class="hf-ib" aria-label="Phóng to" @click="canvas?.zoom(1.25)"><Plus :size="18" aria-hidden="true" /></button>
            <button type="button" class="hf-ib" aria-label="Thu nhỏ" @click="canvas?.zoom(.8)"><Minus :size="18" aria-hidden="true" /></button>
            <button type="button" class="hf-ib" :aria-label="wide ? 'Thu hẹp bản đồ' : 'Mở rộng bản đồ'" @click="toggleWide">
              <component :is="wide ? Minimize2 : Maximize" :size="18" aria-hidden="true" /></button>
            <button type="button" class="hf-ib" aria-label="Về khung mặc định" @click="fit"><Scan :size="18" aria-hidden="true" /></button>
          </div>
        </div>
        <div class="hf-lg legend">
          <span><svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" class="edge" stroke-width="2" /></svg>Thuộc nhóm</span>
          <span><svg width="22" height="6" aria-hidden="true"><line x1="0" y1="3" x2="22" y2="3" class="edge" stroke-width="2" stroke-dasharray="4 4" /></svg>Có liên quan</span>
          <span>Nút viền nét đứt còn mục bên trong · số trên nhóm tính trong khoảng đã chọn</span>
        </div>
      </section>
      <section class="hf-card inspector" :class="wide ? 'hf-c12' : 'hf-c4'">
        <KnowledgeInspector :key="selectedId ?? 'none'" :node="selected" :index="index" :expanded="expanded" :roomy="wide"
                            @select="show" @toggle="toggle" />
        <div class="grow" />
        <button type="button" class="hf-btn" @click="emit('ask', askText)">Hỏi trợ lý về mục này</button>
      </section>
    </div>
  </div>
</template>

<style scoped>
.map { display: flex; flex-direction: column; gap: 14px; }
.groups { display: flex; flex-wrap: wrap; gap: 8px; }
.gchip { display: inline-flex; align-items: center; gap: 8px; border: 1px solid var(--hf-line-3); background: var(--hf-card); border-radius: 999px; padding: 0 16px; min-height: 44px; font-size: 14px; font-weight: 500; color: var(--hf-ink); }
.gchip:hover:not(:disabled):not([aria-pressed="true"]) { background: var(--hf-fill-3); }
.gchip[aria-pressed="true"] { background: var(--hf-ink); color: var(--hf-on-ink); border-color: var(--hf-ink); }
.gchip:disabled { opacity: .45; }
.gdot { width: 9px; height: 9px; border-radius: 50%; }
.gcount { font-size: 13px; color: var(--hf-faint); font-variant-numeric: tabular-nums; }
.gchip[aria-pressed="true"] .gcount { color: #C9C9CF; }
.timeline { padding: 18px 20px; gap: 12px; }
.graph { padding: 12px; position: relative; gap: 8px; }
.sparse { margin: 4px 4px 0; }
.kgw { position: relative; height: clamp(420px, 62vh, 680px); border-radius: 18px; overflow: hidden; }
.overlay { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; pointer-events: none; text-align: center; padding: 24px; }
.overlay p { margin: 0; font-size: 18px; font-weight: 600; color: var(--hf-sub); }
.overlay button { pointer-events: auto; }
.zctl { position: absolute; right: 16px; bottom: 16px; display: flex; gap: 4px; background: var(--hf-card); border-radius: 999px; padding: 4px; box-shadow: 0 6px 20px rgba(0, 0, 0, .12); }
.zctl .hf-ib { width: 40px; height: 40px; }
.legend { padding: 6px 6px 2px; }
.edge { stroke: var(--hf-ghost); }
.inspector { gap: 12px; }
.grow { flex: 1; }
</style>
