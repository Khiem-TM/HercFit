<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { X, RefreshCw, Plus, Minus, Maximize2, Orbit } from 'lucide-vue-next'
import ConstellationCanvas from './ConstellationCanvas.vue'
import { useKnowledgeGraph } from '@/composables/useKnowledgeGraph'
import { constellationKinds, type KnowledgeNode } from '@/types/knowledge'
const props = defineProps<{ busy: boolean; activity: string; revision: number }>()
const emit = defineEmits<{ close: [] }>()
const { graph, loading, refresh } = useKnowledgeGraph()
const selected = ref<KnowledgeNode>()
const filter = ref('all')
const canvas = ref<InstanceType<typeof ConstellationCanvas>>()
const kinds = computed(() => [...new Set(graph.value.nodes.map(n => n.kind))])
const visible = computed(() => {
  const nodes = graph.value.nodes.filter(n => filter.value === 'all' || n.kind === filter.value || n.kind === 'User')
  const ids = new Set(nodes.map(n => n.id))
  return { ...graph.value, nodes, edges: graph.value.edges.filter(e => ids.has(e.source) && ids.has(e.target)) }
})
const stateLabel = computed(() => ({ loading:'Đang tìm các vì sao…', warming:'Đang xây dựng bản đồ tri thức', unavailable:'Chưa kết nối được bản đồ', blocked:'Bản đồ hiện không khả dụng', empty:'Bầu trời của bạn đang chờ những dấu sao đầu tiên' })[graph.value.status] || '')
const detailLabels: Record<string,string> = { weight_kg:'Cân nặng (kg)',height_cm:'Chiều cao (cm)',consumed_at:'Thời gian bữa ăn',recorded_at:'Ngày ghi nhận',quantity:'Khẩu phần',unit:'Đơn vị',status:'Trạng thái',duration_ms:'Thời gian xử lý (ms)',start_date:'Bắt đầu',target_date:'Ngày mục tiêu',energy_kcal:'Năng lượng (kcal)',protein_g:'Protein (g)',serving_size:'Khẩu phần chuẩn',serving_unit:'Đơn vị khẩu phần' }
const relationships = computed(() => selected.value ? graph.value.edges.filter(e => e.source === selected.value?.id || e.target === selected.value?.id).map(e => {
  const other = graph.value.nodes.find(n => n.id === (e.source === selected.value?.id ? e.target : e.source))
  return other?.label
}).filter(Boolean) : [])
function keydown(e: KeyboardEvent) { if (e.key === 'Escape') emit('close') }
let timer: ReturnType<typeof setInterval>
onMounted(() => { refresh(); timer = setInterval(() => { if (!document.hidden && !loading.value) refresh() }, 10000); window.addEventListener('keydown',keydown) })
onUnmounted(() => { clearInterval(timer); window.removeEventListener('keydown',keydown) })
watch(() => props.revision, () => refresh())
watch(visible, () => { if (selected.value) selected.value = visible.value.nodes.find(n => n.id === selected.value?.id) })
</script>
<template>
  <aside class="observatory" aria-label="Bản đồ tri thức cá nhân">
    <header class="observatory-header">
      <div><p class="eyeline">THE OLYMPUS OBSERVATORY</p><h2>Bầu trời <em>tri thức</em></h2><p class="subtitle">Mỗi dấu sao là một phần hành trình của bạn.</p></div>
      <button class="icon-button" aria-label="Đóng bản đồ" @click="emit('close')"><X :size="18" /></button>
    </header>
    <div class="status-row"><span class="status-dot" :class="{ ready: graph.status === 'ok' }" /><span>{{ loading ? 'Đang cập nhật' : graph.status === 'ok' ? `${graph.nodes.length} dấu sao · ${graph.edges.length} liên kết` : 'Đang chờ dữ liệu' }}</span><button class="icon-button refresh" aria-label="Cập nhật bản đồ" :disabled="loading" @click="refresh"><RefreshCw :size="13" :class="{ spinning: loading }" /></button></div>
    <div class="filter-row"><button :class="{ active: filter === 'all' }" @click="filter='all'">Tất cả</button><button v-for="kind in kinds" :key="kind" :class="{active:filter===kind}" @click="filter=kind"><i :style="{background:constellationKinds[kind]?.color}" />{{ constellationKinds[kind]?.label || kind }}</button></div>
    <div class="map-area"><ConstellationCanvas ref="canvas" :graph="visible" :selected-id="selected?.id" @select="selected=$event" />
      <div v-if="!visible.nodes.length" class="empty-sky"><Orbit :size="32" :stroke-width="1" /><p>{{ stateLabel || 'Không có dữ liệu trong nhóm này' }}</p><small>Ghi nhận bữa ăn, số đo hoặc mục tiêu để bắt đầu.</small><button v-if="graph.status==='unavailable'" @click="refresh">Thử kết nối lại</button></div>
      <div class="map-controls"><button aria-label="Phóng to" @click="canvas?.zoom(1.25)"><Plus :size="15" /></button><button aria-label="Thu nhỏ" @click="canvas?.zoom(.8)"><Minus :size="15" /></button><button aria-label="Xem toàn bộ" @click="canvas?.fit()"><Maximize2 :size="14" /></button></div>
    </div>
    <div class="activity" aria-live="polite"><span class="status-dot" :class="{ ready:busy }" />{{ busy ? activity : 'Các liên kết thể hiện dữ liệu đã được ghi nhận' }}</div>
    <section class="inspector">
      <template v-if="selected"><p class="eyeline">{{ constellationKinds[selected.kind]?.label || selected.kind }}</p><h3>{{ selected.label }}</h3><dl><template v-for="(v,k) in selected.details" :key="k"><dt>{{ detailLabels[k] || k }}</dt><dd>{{ v }}</dd></template></dl><p class="provenance">Nguồn: {{ selected.source === 'agent' ? 'Kết quả thực thi' : 'Hồ sơ đã lưu' }}<span v-if="selected.updated_at"> · {{ new Date(selected.updated_at).toLocaleString('vi-VN') }}</span></p><p v-if="relationships.length" class="relations">Liên kết với: {{ relationships.join(' · ') }}</p></template>
      <template v-else><p class="eyeline">KHÁM PHÁ CHÒM SAO</p><h3>Chạm một vì sao để xem câu chuyện.</h3><p class="provenance">Kéo sao để lay chuyển chòm sao · Cuộn để phóng to</p></template>
    </section>
    <div class="node-index" aria-label="Chọn dữ liệu bằng danh sách"><button v-for="node in visible.nodes" :key="node.id" :aria-pressed="selected?.id===node.id" @click="selected=node"><i :style="{background:constellationKinds[node.kind]?.color}" />{{ node.label }}</button></div>
    <footer>HỒ SƠ RIÊNG CỦA BẠN <span>{{ graph.lag_ms != null && graph.lag_ms > 5000 ? 'Đang đồng bộ dữ liệu…' : 'OLYMPUS / ATLAS' }}</span></footer>
  </aside>
</template>
<style scoped>
.observatory{position:relative;z-index:30;display:flex;flex-direction:column;width:min(760px,52vw);height:100dvh;background:#101216;border-left:1px solid #d4b77d26;color:#e5e2dc;box-shadow:-30px 0 90px #0005}
.observatory-header{display:flex;align-items:flex-start;justify-content:space-between;padding:28px 26px 16px}.eyeline{font:8px 'JetBrains Mono',monospace;letter-spacing:.2em;color:#bda77c;margin:0 0 10px}.observatory h2{font:30px 'Playfair Display',serif;letter-spacing:-.04em;margin:0}.observatory h2 em{color:#d4b77d;font-weight:400}.subtitle{font-size:11px;color:#8e8c88;margin:9px 0 0}.icon-button{display:grid;place-items:center;width:32px;height:32px;border:1px solid #ffffff12;border-radius:50%;color:#aca89e;background:transparent}.status-row{display:flex;align-items:center;gap:8px;margin:0 26px;padding:8px 0;border-top:1px solid #ffffff09;color:#9d9a93;font:9px 'JetBrains Mono',monospace}.status-dot{width:5px;height:5px;background:#696863;border-radius:50%;flex-shrink:0}.status-dot.ready{background:#d4b77d;box-shadow:0 0 8px #d4b77d66}.refresh{margin-left:auto;width:25px;height:25px}.filter-row{display:flex;gap:6px;overflow-x:auto;padding:4px 26px 14px;flex-shrink:0}.filter-row button{white-space:nowrap;padding:6px 10px;border:1px solid #ffffff0c;border-radius:20px;font-size:10px;color:#99978e;display:flex;align-items:center;gap:6px}.filter-row button.active{border-color:#d4b77d55;background:#d4b77d0a;color:#ecdfc3}.filter-row i,.node-index i{width:4px;height:4px;border-radius:50%;flex-shrink:0}.map-area{position:relative;flex:1;min-height:270px;border-block:1px solid #ffffff09}.map-controls{position:absolute;right:16px;bottom:16px;display:flex;background:#13151be8;border:1px solid #ffffff15;border-radius:8px}.map-controls button{padding:10px;color:#c1bba9}.empty-sky{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:12px;text-align:center;pointer-events:none;padding:35px;color:#b9aa89}.empty-sky p{font:20px 'Playfair Display',serif;max-width:270px}.empty-sky small{font-size:11px;color:#85847e}.empty-sky button{pointer-events:auto;border-bottom:1px solid #b9aa89;font-size:11px}.activity{display:flex;align-items:center;gap:8px;padding:12px 26px;font-size:10px;color:#a09d95;border-bottom:1px solid #ffffff09}.inspector{padding:20px 26px 12px;max-height:190px;overflow:auto}.inspector h3{font:19px 'Playfair Display',serif;margin:0 0 10px}.provenance,.relations{font-size:10px;color:#8c8c86;line-height:1.8}.inspector dl{display:grid;grid-template-columns:1fr 1fr;gap:5px;font-size:11px;margin-bottom:10px}.inspector dt{color:#918e85}.inspector dd{text-align:right;color:#ded7c7}.node-index{display:flex;gap:5px;padding:0 26px 12px;overflow-x:auto;flex-shrink:0}.node-index button{display:flex;gap:6px;align-items:center;white-space:nowrap;font-size:10px;padding:5px 8px;border:1px solid #ffffff0c;border-radius:4px;color:#a4a099}.node-index button[aria-pressed=true]{border-color:#d4b77d77;color:#e7d6b3}footer{display:flex;justify-content:space-between;padding:12px 26px;border-top:1px solid #ffffff0b;color:#706f67;font:8px 'JetBrains Mono',monospace;letter-spacing:.12em}.spinning{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:1000px){.observatory{position:fixed;inset:0 0 0 auto;width:min(760px,100vw)}}@media(prefers-reduced-motion:reduce){.spinning{animation:none}}

/* Motion stays quiet around the constellation itself. */
.observatory { animation: observatory-arrive 500ms cubic-bezier(.2,.8,.2,1) both; }
.icon-button, .filter-row button, .node-index button, .map-controls button {
  transition: color 220ms ease, background 220ms ease, border-color 220ms ease, transform 300ms cubic-bezier(.2,.8,.2,1), box-shadow 300ms ease;
}
.icon-button:hover, .map-controls button:hover { color: #f0dfba; background: #d4b77d12; }
.filter-row button:hover, .node-index button:hover { border-color: #d4b77d45; background: #d4b77d08; color: #dfcfad; }
.map-controls { border-radius: 24px; overflow: hidden; backdrop-filter: blur(12px); box-shadow: 0 6px 24px #0003; }
.map-controls button:active, .icon-button:active { transform: scale(.9); }
.node-index button { border-radius: 20px; }
@keyframes observatory-arrive { from { opacity: 0; transform: translateX(24px); } to { opacity: 1; transform: translateX(0); } }
@media (prefers-reduced-motion: reduce) {
  .observatory { animation: none; }
  .icon-button, .filter-row button, .node-index button, .map-controls button { transition: none; transform: none; }
}
</style>
