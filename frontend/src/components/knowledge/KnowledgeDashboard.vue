<script setup lang="ts">
import { computed, shallowRef, useTemplateRef, watch } from 'vue'
import { HeartPulse, Info, Link2, RefreshCw } from 'lucide-vue-next'
import { hubColor, type KnowledgeGraph } from '@/types/knowledge'
import EnergyTargets from './dashboard/EnergyTargets.vue'
import InsightCard from './dashboard/InsightCard.vue'
import InsightQuickView from './dashboard/InsightQuickView.vue'
import TrainingProgress from './dashboard/TrainingProgress.vue'
import WeightChart from './dashboard/WeightChart.vue'
import ActivityCard from './health/ActivityCard.vue'
import DailyTable from './health/DailyTable.vue'
import EnergyCard from './health/EnergyCard.vue'
import HeartCard from './health/HeartCard.vue'
import ProfileCard from './health/ProfileCard.vue'
import RecordsCard from './health/RecordsCard.vue'
import SleepCard from './health/SleepCard.vue'
import SourceCard from './health/SourceCard.vue'
import VitalsStrip from './health/VitalsStrip.vue'
import { dayLabel, moment } from './health/healthFormat'
import { useHealthData } from './health/useHealthData'

/**
 * Một bản tổng quan những gì HercFit biết về người dùng: hồ sơ, chỉ số sinh tồn, rồi chi tiết từng mảng.
 * Bản ghi từ knowledge graph (bữa ăn, buổi tập, lần cân) và dữ liệu thiết bị từ Google
 * Health nằm cạnh nhau theo từng mảng, mỗi thẻ ghi rõ nguồn của nó.
 */
const props = defineProps<{ graph: KnowledgeGraph; revision?: number }>()
const emit = defineEmits<{ explore: [id: string]; connect: []; 'edit-profile': [] }>()

const RANGES = [7, 14, 28, 90]
const windowDays = shallowRef(28)
const { data, loading, failed, refresh } = useHealthData(() => windowDays.value)
watch(() => props.revision, () => { void refresh() })
const root = useTemplateRef<HTMLElement>('root')

const connection = computed(() => data.value?.connection ?? null)
const connected = computed(() => connection.value?.status === 'ACTIVE' || connection.value?.status === 'NEEDS_REAUTH')
const hasDeviceData = computed(() => !!data.value && (data.value.daily.length + data.value.sleep.length + data.value.workouts.length
  + data.value.measurements.length + data.value.samples.length) > 0)
const device = computed(() => !!data.value && (hasDeviceData.value || connected.value))
const FAILED: Record<string, string> = {
  connection: 'trạng thái kết nối', profile: 'hồ sơ', overview: 'phân tích', daily: 'số liệu ngày', sleep: 'giấc ngủ',
  workouts: 'buổi vận động', samples: 'chỉ số sinh tồn', progress: 'tiến độ', measurements: 'số đo',
}

const traits = computed(() => {
  const p = props.graph.profile
  if (!p) return []
  return [
    p.experience ? `Trình độ ${p.experience}` : null, p.focus ? `Trọng tâm ${p.focus}` : null,
    p.available_days ? `${p.available_days} buổi/tuần${p.session_minutes ? ` × ${p.session_minutes} phút` : ''}` : null,
    ...p.equipment.map(item => `Dụng cụ: ${item}`),
  ].filter((item): item is string => !!item)
})
const selectedId = shallowRef<string>()
const selectedInsight = computed(() => props.graph.insights.find(item => item.id === selectedId.value))
const maxIntent = computed(() => Math.max(1, ...props.graph.intents.map(intent => intent.count)))

const sections = computed(() => [
  { id: 'profile', label: 'Hồ sơ' },
  { id: 'vitals', label: 'Nhịp sống' },
  { id: 'energy', label: 'Năng lượng' },
  { id: 'activity', label: 'Vận động' },
  ...(device.value ? [{ id: 'recovery', label: 'Giấc ngủ & tim' }] : []),
  { id: 'body', label: 'Cơ thể' },
  ...(device.value ? [{ id: 'days', label: 'Số liệu ngày' }] : []),
  ...(props.graph.intents.length ? [{ id: 'intents', label: 'Bạn hay hỏi' }] : []),
  { id: 'sources', label: 'Nguồn' },
])

function jump(id: string) {
  root.value?.querySelector<HTMLElement>(`[data-section="${id}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

</script>

<template>
  <div ref="root" class="dashboard">
    <div class="toolbar">
      <div class="filters">
        <div class="picker" role="group" aria-label="Khoảng thời gian">
          <button v-for="days in RANGES" :key="days" type="button" :aria-pressed="windowDays === days" @click="windowDays = days">{{ days }} ngày</button>
        </div>
        <span v-if="data" class="window">{{ dayLabel(data.start) }} → {{ dayLabel(data.end) }}</span>
        <button type="button" class="icon" aria-label="Tải lại dữ liệu" :disabled="loading" @click="refresh"><RefreshCw :size="13" :class="{ spinning: loading }" /></button>
      </div>
      <nav class="jump" aria-label="Đi tới mục">
        <button v-for="section in sections" :key="section.id" type="button" @click="jump(section.id)">{{ section.label }}</button>
      </nav>
    </div>

    <p v-if="connected && connection?.last_sync_at" class="hint">Đồng bộ gần nhất {{ moment(connection.last_sync_at) }} · dữ liệu thiết bị qua Google Health.</p>
    <section v-if="data && (!connected || connection?.status === 'NEEDS_REAUTH')" class="cta">
      <HeartPulse :size="22" :stroke-width="1.4" />
      <div>
        <h3>{{ connection?.status === 'NEEDS_REAUTH' ? 'Kết nối Google Health đã hết hạn' : 'Kết nối Google Health' }}</h3>
        <p>{{ connection?.status === 'NEEDS_REAUTH'
          ? 'Google giới hạn quyền ở chế độ thử nghiệm trong 7 ngày. Kết nối lại để tiếp tục đồng bộ; dữ liệu cũ vẫn hiển thị bên dưới.'
          : 'Thêm bước chân, giấc ngủ, nhịp tim nghỉ, HRV, SpO2, buổi vận động và số đo cơ thể từ đồng hồ, vòng đeo hoặc cân thông minh.' }}</p>
      </div>
      <button type="button" @click="emit('connect')"><Link2 :size="13" />{{ connection?.status === 'NEEDS_REAUTH' ? 'Kết nối lại' : 'Kết nối' }}</button>
    </section>
    <p v-if="failed.length" class="hint warn"><Info :size="12" />Chưa tải được: {{ failed.map(name => FAILED[name] ?? name).join(', ') }}.</p>
    <ul v-if="data?.overview?.notes.length && hasDeviceData" class="notes">
      <li v-for="note in data.overview.notes" :key="note"><Info :size="12" />{{ note }}</li>
    </ul>

    <section data-section="profile" class="block" aria-label="Hồ sơ">
      <ProfileCard :profile="data?.profile ?? null" :traits="traits" @edit="emit('edit-profile')" @map="emit('explore', 'me')" />
    </section>

    <section data-section="vitals" class="block" aria-labelledby="vitals-title">
      <div class="block-head"><p id="vitals-title" class="eyeline">NHỊP SỐNG CỦA BẠN</p>
        <span class="block-hint">Thiết bị: số gần nhất và xu hướng {{ windowDays }} ngày · Widget: chạm để xem nhanh</span></div>
      <div :class="{ refetching: loading }"><VitalsStrip v-if="data && hasDeviceData" :data="data" /></div>
      <div v-if="graph.insights.length" class="insights">
        <InsightCard v-for="(insight, i) in graph.insights" :key="insight.id" :insight="insight" :index="i" @open="selectedId = insight.id" />
      </div>
      <p v-if="!graph.insights.length && !hasDeviceData" class="hint">Ghi bữa ăn, số đo, buổi tập hoặc kết nối Google Health để thấy nhịp sống của bạn.</p>
    </section>

    <section data-section="energy" class="block" aria-labelledby="energy-head">
      <div class="block-head"><p id="energy-head" class="eyeline">NĂNG LƯỢNG &amp; DINH DƯỠNG</p></div>
      <div class="pair" :class="{ refetching: loading }">
        <EnergyTargets :graph="graph" />
        <EnergyCard v-if="data && device" :data="data" />
      </div>
    </section>

    <section data-section="activity" class="block" aria-labelledby="activity-head">
      <div class="block-head"><p id="activity-head" class="eyeline">VẬN ĐỘNG &amp; TẬP LUYỆN</p></div>
      <div class="pair" :class="{ refetching: loading }">
        <ActivityCard v-if="data && device" class="wide" :data="data" />
        <TrainingProgress v-if="graph.status !== 'loading'" :graph="graph" @explore="emit('explore', $event)" />
        <RecordsCard v-if="data && device" :data="data" />
      </div>
    </section>

    <section v-if="data && device" data-section="recovery" class="block" aria-labelledby="recovery-head">
      <div class="block-head"><p id="recovery-head" class="eyeline">GIẤC NGỦ &amp; TIM MẠCH</p></div>
      <div class="pair" :class="{ refetching: loading }">
        <SleepCard class="wide" :data="data" />
        <HeartCard class="wide" :data="data" />
      </div>
    </section>

    <section data-section="body" class="block" aria-labelledby="body-head">
      <div class="block-head"><p id="body-head" class="eyeline">CƠ THỂ</p></div>
      <WeightChart v-if="graph.status !== 'loading'" :graph="graph" @explore="emit('explore', $event)" />
      <p v-else class="hint">Đang tải số đo…</p>
    </section>

    <section v-if="data && device" data-section="days" class="block" aria-label="Số liệu theo ngày">
      <DailyTable :class="{ refetching: loading }" :data="data" />
    </section>

    <section v-if="graph.intents.length" data-section="intents" class="block intents" aria-labelledby="intents-title">
      <div class="block-head"><p id="intents-title" class="eyeline">BẠN HAY HỎI · 30 NGÀY</p></div>
      <button v-for="intent in graph.intents" :key="intent.intent" type="button" class="intent" @click="emit('explore', intent.node_id)">
        <span class="intent-label"><i :style="{ background: hubColor(intent.hub) }" />{{ intent.label }}</span>
        <span class="intent-bar"><span :style="{ width: `${(intent.count / maxIntent) * 100}%`, background: hubColor(intent.hub) }" /></span>
        <span class="intent-count">{{ intent.count }}</span>
      </button>
    </section>

    <section data-section="sources" class="block" aria-label="Nguồn dữ liệu">
      <SourceCard :connection="connection" @manage="emit('connect')" />
    </section>

    <InsightQuickView v-if="selectedInsight" :insight="selectedInsight" :graph="graph" @close="selectedId = undefined" @explore="emit('explore', $event)" />
  </div>
</template>

<style scoped>
.dashboard { display: flex; flex-direction: column; gap: clamp(18px, 2.4cqi, 26px); padding: 0 var(--gutter, 26px) 28px; }
.toolbar { position: sticky; top: 0; z-index: 4; display: flex; flex-direction: column; gap: 8px; margin: 0 calc(var(--gutter, 26px) * -1); padding: 10px var(--gutter, 26px) 10px; background: light-dark(#f3f2ef, #101216); border-bottom: 1px solid light-dark(#1818180a, #ffffff0a); box-shadow: 0 12px 16px -14px light-dark(#00000066, #000c); }
.filters { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.picker { display: flex; gap: 3px; padding: 3px; border: 1px solid light-dark(#1818180e, #ffffff0e); border-radius: 9px; background: light-dark(#f2f0ee, #0e1116); }
.picker button { padding: 6px 10px; border-radius: 6px; font-size: 10.5px; color: light-dark(#5a5e63, #9b9fa5); transition: background 180ms, color 180ms; }
.picker button[aria-pressed=true] { background: light-dark(#87671a1f, #d4b77d1f); color: light-dark(#867854, #f3e6c6); }
.window { font: 10px 'JetBrains Mono', monospace; color: light-dark(#60676e, #8d949c); }
.icon { display: grid; place-items: center; width: 28px; height: 28px; margin-left: auto; border: 1px solid light-dark(#18181813, #ffffff13); border-radius: 50%; color: light-dark(#7b6b43, #c9bb98); }
.icon:hover { background: light-dark(#87671a12, #d4b77d12); }
.action { display: inline-flex; align-items: center; gap: 6px; padding: 6px 11px; border: 1px solid light-dark(#87671a40, #d4b77d40); border-radius: 9px; font-size: 10.5px; color: light-dark(#857752, #f0e3c2); }
.action:hover { background: light-dark(#87671a12, #d4b77d12); }
.action:disabled, .icon:disabled { opacity: .5; }
.jump { display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none; }
.jump button { flex: none; padding: 4px 10px; border: 1px solid light-dark(#18181810, #ffffff10); border-radius: 20px; font-size: 10px; color: light-dark(#605d55, #a29f96); transition: color 200ms, border-color 200ms, background 200ms; }
.jump button:hover { color: light-dark(#302919, #efe6d2); border-color: light-dark(#87671a55, #d4b77d55); background: light-dark(#87671a0d, #d4b77d0d); }
.hint { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 10.5px; line-height: 1.55; color: light-dark(#60676e, #8d949c); }
.hint.warn { color: light-dark(#8f6817, #e8c07d); }
.notes { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 4px; }
.notes li { display: flex; align-items: flex-start; gap: 6px; font-size: 10.5px; line-height: 1.55; color: light-dark(#7c6a3a, #c9b98f); }
.notes li svg { flex: none; margin-top: 2px; }
.cta { display: flex; align-items: center; gap: 14px; padding: 16px 18px; border: 1px solid light-dark(#0d60b840, #3987e540); border-radius: 16px; background: linear-gradient(120deg, light-dark(#0d60b814, #3987e514), transparent 70%), light-dark(#fdfcf9, #14171d); color: light-dark(#4f719f, #a9c8f2); }
.cta h3 { margin: 0; font-size: 13.5px; font-weight: 500; color: light-dark(#272723, #ecebe6); }
.cta p { margin: 4px 0 0; font-size: 11px; line-height: 1.6; color: light-dark(#53575d, #a3a8ae); }
.cta button { display: inline-flex; flex: none; align-items: center; gap: 6px; padding: 8px 13px; border-radius: 10px; background: light-dark(#24231f, #f1f0eb); color: light-dark(#f3f2ef, #101216); font-size: 11px; font-weight: 600; }
.block { display: flex; flex-direction: column; gap: 12px; scroll-margin-top: 92px; }
.block-head { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 6px 12px; }
.eyeline { font: 8px 'JetBrains Mono', monospace; letter-spacing: .2em; color: light-dark(#7d6431, #bda77c); margin: 0; }
.block-hint { font-size: 10px; color: light-dark(#676963, #8f918a); }
.insights { display: flex; flex-wrap: wrap; gap: 12px; }
.insights > * { flex: 1 1 200px; }
.pair { display: grid; gap: 16px; grid-template-columns: minmax(0, 1fr); transition: opacity 200ms; }
.refetching { opacity: .55; }
.intents { gap: 4px; }
.intent { display: grid; grid-template-columns: minmax(120px, 1.1fr) 2fr 28px; align-items: center; gap: 12px; padding: 7px 8px; border-radius: 8px; text-align: left; transition: background 200ms; }
.intent:hover { background: light-dark(#18181806, #ffffff06); }
.intent-label { display: flex; align-items: center; gap: 8px; font-size: 11px; color: light-dark(#3b372e, #d9d4c8); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.intent-label i { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.intent-bar { height: 4px; border-radius: 4px; background: light-dark(#1818180a, #ffffff0a); overflow: hidden; }
.intent-bar span { display: block; height: 100%; border-radius: 4px; opacity: .75; animation: stretch 800ms cubic-bezier(.2,.8,.2,1) both; transform-origin: left; }
.intent-count { font: 10px 'JetBrains Mono', monospace; color: light-dark(#5d5950, #a8a49a); text-align: right; }
.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes stretch { from { transform: scaleX(0); } to { transform: scaleX(1); } }
/* Bố cục theo độ rộng của bảng, người dùng có thể kéo; xem KnowledgePanel. */
@container observatory (max-width: 480px) { .cta { flex-direction: column; align-items: flex-start; } }
@container observatory (max-width: 520px) { .intent { grid-template-columns: minmax(100px, 1.1fr) 1fr 24px; gap: 8px; } }
@container observatory (min-width: 760px) {
  .pair { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pair > .wide { grid-column: 1 / -1; }
}
@container observatory (min-width: 900px) {
  .intents { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 28px; row-gap: 4px; }
  .intents > .block-head { grid-column: 1 / -1; }
}
@container observatory (min-width: 1180px) {
  .pair { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (prefers-reduced-motion: reduce) { .spinning, .intent-bar span { animation: none; } .pair { transition: none; } }
</style>
