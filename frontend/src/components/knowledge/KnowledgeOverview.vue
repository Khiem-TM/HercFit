<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import type { KnowledgeGraph } from '@/types/knowledge'
import InsightCard from './dashboard/InsightCard.vue'
import InsightQuickView from './dashboard/InsightQuickView.vue'
import WeightChart from './dashboard/WeightChart.vue'
import TrainingProgress from './dashboard/TrainingProgress.vue'
import EnergyTargets from './dashboard/EnergyTargets.vue'
import { hubColor } from '@/types/knowledge'

const props = defineProps<{ graph: KnowledgeGraph }>()
const emit = defineEmits<{ explore: [id: string] }>()
const selectedId = shallowRef<string>()
const selectedInsight = computed(() => props.graph.insights.find(item => item.id === selectedId.value))

const profile = computed(() => props.graph.profile)
const stats = computed(() => {
  const p = profile.value
  if (!p) return []
  return [
    p.age ? { label: 'Tuổi', value: `${p.age}` } : null,
    p.height_cm ? { label: 'Chiều cao', value: `${p.height_cm} cm` } : null,
    p.weight_kg ? { label: 'Cân nặng', value: `${p.weight_kg} kg` } : null,
    p.bmi ? { label: 'BMI', value: `${p.bmi}` } : null,
  ].filter((item): item is { label: string; value: string } => item !== null)
})
const traits = computed(() => {
  const p = profile.value
  if (!p) return []
  return [
    p.experience ? `Trình độ ${p.experience}` : null, p.focus ? `Trọng tâm ${p.focus}` : null,
    p.available_days ? `${p.available_days} buổi/tuần${p.session_minutes ? ` × ${p.session_minutes} phút` : ''}` : null,
    ...p.equipment.map(item => `Dụng cụ: ${item}`),
  ].filter((item): item is string => !!item)
})
const maxIntent = computed(() => Math.max(1, ...props.graph.intents.map(intent => intent.count)))

</script>

<template>
  <div class="overview">
    <section class="profile" aria-labelledby="profile-title">
      <div class="section-head"><p id="profile-title" class="eyeline">HỒ SƠ CỦA BẠN</p>
        <button class="link" type="button" @click="emit('explore', 'me')">Xem trên bản đồ</button></div>
      <div v-if="stats.length" class="stats">
        <div v-for="item in stats" :key="item.label" class="stat"><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div>
      </div>
      <div v-if="traits.length" class="traits"><span v-for="trait in traits" :key="trait">{{ trait }}</span></div>
      <p v-if="!stats.length && !traits.length" class="hint">Ghi số đo cơ thể và hồ sơ tập luyện qua trò chuyện để trợ lý hiểu bạn hơn.</p>
    </section>

    <section v-if="graph.insights.length" aria-label="Điểm nổi bật">
      <div class="section-head"><p class="eyeline">NHỊP SỐNG CỦA BẠN</p><span class="section-hint">Chạm vào widget để xem nhanh</span></div>
      <div class="insights"><InsightCard v-for="(insight, i) in graph.insights" :key="insight.id" :insight="insight" :index="i" @open="selectedId = insight.id" /></div>
    </section>

    <div class="analytics">
      <!-- Typed targets from /api/nutrition/targets: works even when the graph is off. -->
      <EnergyTargets class="energy" :graph="graph" />
      <template v-if="graph.status !== 'loading'">
        <WeightChart :graph="graph" @explore="emit('explore', $event)" />
        <TrainingProgress :graph="graph" @explore="emit('explore', $event)" />
      </template>
      <div v-else class="loading-overview" role="status">Đang tải các chỉ số của bạn…</div>
    </div>

    <InsightQuickView v-if="selectedInsight" :insight="selectedInsight" :graph="graph" @close="selectedId = undefined" @explore="emit('explore', $event)" />

    <section v-if="graph.intents.length" class="intents" aria-labelledby="intents-title">
      <div class="section-head"><p id="intents-title" class="eyeline">BẠN HAY HỎI · 30 NGÀY</p></div>
      <button v-for="intent in graph.intents" :key="intent.intent" type="button" class="intent" @click="emit('explore', intent.node_id)">
        <span class="intent-label"><i :style="{ background: hubColor(intent.hub) }" />{{ intent.label }}</span>
        <span class="intent-bar"><span :style="{ width: `${(intent.count / maxIntent) * 100}%`, background: hubColor(intent.hub) }" /></span>
        <span class="intent-count">{{ intent.count }}</span>
      </button>
    </section>

    <p v-if="!graph.insights.length && !graph.intents.length" class="hint empty">
      Bản đồ sẽ tự hình thành khi bạn ghi bữa ăn, buổi tập, số đo hoặc trò chuyện với trợ lý.
    </p>
  </div>
</template>

<style scoped>
.overview { display: flex; flex-direction: column; gap: clamp(20px, 2.6cqi, 30px); padding: 18px var(--gutter, 26px) 26px; }
.eyeline { font: 8px 'JetBrains Mono', monospace; letter-spacing: .2em; color: #bda77c; margin: 0; }
.section-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.link { font-size: 10px; color: #a99a7a; border-bottom: 1px solid #a99a7a55; transition: color 200ms, border-color 200ms; }
.link:hover { color: #ecdcb6; border-color: #ecdcb6; }
.profile { padding: clamp(14px, 2cqi, 22px) clamp(16px, 2.4cqi, 26px); border: 1px solid #ffffff0d; border-radius: 14px; background: linear-gradient(140deg, #d4b77d0a, transparent 60%), #13151a; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(90px, 1fr)); gap: 10px 16px; }
.stat { display: flex; flex-direction: column; gap: 4px; }
.stat span { font-size: 10px; color: #8f8b82; }
.stat strong { font-family: 'Playfair Display', serif; font-size: clamp(20px, 2.8cqi, 32px); font-weight: 400; color: #f1e8d6; letter-spacing: -.02em; transition: font-size 200ms; }
.traits { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 14px; }
.traits span { padding: 5px 10px; border: 1px solid #d4b77d24; border-radius: 20px; font-size: 10px; color: #d9cba9; background: #d4b77d08; }
.hint { font-size: 11px; color: #85847e; line-height: 1.6; margin: 0; }
.hint.empty { text-align: center; padding: 30px 10px; }
/* Cards grow to fill each row, so a short last row stays as wide as the others. */
.insights { display: flex; flex-wrap: wrap; gap: 12px; }
.insights > * { flex: 1 1 200px; }
.analytics { display: grid; gap: 16px; grid-template-columns: minmax(0, 1fr); }
.section-hint { font-size: 10px; color: #8f918a; }
.loading-overview { padding: 35px 0; color: #aaa69a; font-size: 12px; text-align: center; }
.intents { display: flex; flex-direction: column; gap: 4px; }
.intent { display: grid; grid-template-columns: minmax(120px, 1.1fr) 2fr 28px; align-items: center; gap: 12px; padding: 7px 8px; border-radius: 8px; text-align: left; transition: background 200ms; }
.intent:hover { background: #ffffff06; }
.intent-label { display: flex; align-items: center; gap: 8px; font-size: 11px; color: #d9d4c8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.intent-label i { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.intent-bar { height: 4px; border-radius: 4px; background: #ffffff0a; overflow: hidden; }
.intent-bar span { display: block; height: 100%; border-radius: 4px; opacity: .75; animation: stretch 800ms cubic-bezier(.2,.8,.2,1) both; transform-origin: left; }
.intent-count { font: 10px 'JetBrains Mono', monospace; color: #a8a49a; text-align: right; }
@keyframes stretch { from { transform: scaleX(0); } to { transform: scaleX(1); } }
/* Arranged by the panel's width, which the user can drag; see KnowledgePanel. */
@container observatory (max-width: 520px) {
  .stats { grid-template-columns: repeat(2, 1fr); gap: 16px; }
  .intent { grid-template-columns: minmax(100px, 1.1fr) 1fr 24px; gap: 8px; }
}
@container observatory (min-width: 760px) {
  .analytics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .analytics > .energy, .analytics > .loading-overview { grid-column: 1 / -1; }
}
@container observatory (min-width: 900px) {
  .intents { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 28px; row-gap: 4px; }
  .intents > .section-head { grid-column: 1 / -1; }
}
@container observatory (min-width: 1180px) {
  .analytics { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .analytics > .energy { grid-column: auto; }
  .analytics > .loading-overview { grid-column: span 2; }
}
@media (prefers-reduced-motion: reduce) { .intent-bar span { animation: none; } }
</style>
