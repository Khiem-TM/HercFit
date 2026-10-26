<script setup lang="ts">
import { computed, shallowRef, useId } from 'vue'
import { ArrowUpRight, Check, Dumbbell, RefreshCw } from 'lucide-vue-next'
import type { KnowledgeGraph } from '@/types/knowledge'
import { number, shortDate } from './dashboardData'
import { useTrainingSummary } from './useTrainingSummary'

const props = defineProps<{ graph: KnowledgeGraph }>()
const emit = defineEmits<{ explore: [id: string] }>()
const titleId = useId()
const { summary, loading, error, refresh } = useTrainingSummary(() => props.graph.generated_at)
const selectedWeek = shallowRef<string>()
const week = computed(() => summary.value?.weeks.find(item => item.week_start === selectedWeek.value) ?? summary.value?.weeks.at(-1))
const progress = computed(() => week.value?.planned_sessions ? Math.min(100, Math.round(week.value.completed_planned_sessions / week.value.planned_sessions * 100)) : null)
const remaining = computed(() => Math.max(0, (week.value?.planned_sessions ?? 0) - (week.value?.completed_planned_sessions ?? 0)))
const maxSessions = computed(() => Math.max(1, ...(summary.value?.weeks.map(item => item.sessions) ?? [])))
</script>

<template>
  <section class="training-widget" :aria-labelledby="titleId" :aria-busy="loading">
    <header class="widget-head"><div><p class="eyeline"><Dumbbell :size="13" /> TẬP LUYỆN</p><h3 :id="titleId">Từng buổi, gần hơn mục tiêu</h3></div>
      <button class="refresh" type="button" aria-label="Cập nhật tiến trình tập luyện" :disabled="loading" @click="refresh"><RefreshCw :size="14" :class="{ spinning: loading }" /></button>
    </header>
    <p v-if="error" class="notice" role="status">{{ summary ? 'Chưa cập nhật được. Đang hiển thị dữ liệu lần trước.' : 'Chưa tải được tiến trình tập luyện.' }} <button type="button" @click="refresh">Thử lại</button></p>
    <div v-if="loading && !summary" class="loading-state" role="status">Đang đọc kế hoạch và các buổi tập…<span /></div>
    <template v-else-if="week">
      <div class="progress-heading"><div><span class="week-label">Tuần từ {{ shortDate(week.week_start) }}</span><p><strong>{{ week.completed_planned_sessions }}</strong><span> / {{ week.planned_sessions }} buổi đến hạn</span></p></div>
        <span v-if="progress != null" class="progress-percent" :class="{ complete: progress === 100 }"><Check v-if="progress === 100" :size="15" />{{ progress }}<small>%</small></span>
      </div>
      <div v-if="progress != null" class="progress-track" role="progressbar" aria-label="Hoàn thành kế hoạch tập luyện đến hạn" :aria-valuenow="progress" :aria-valuemin="0" :aria-valuemax="100" :aria-valuetext="`${week.completed_planned_sessions} trên ${week.planned_sessions} buổi đến hạn`">
        <span :style="{ transform: `scaleX(${progress / 100})` }" />
      </div>
      <p class="progress-note">{{ progress === 100 ? 'Đã hoàn thành các buổi đến hạn. Giữ nhịp nhé!' : progress != null ? `Còn ${remaining} buổi đến hạn chưa hoàn thành.` : 'Chưa có buổi tập đến hạn trong kế hoạch tuần này.' }}</p>
      <div class="training-stats"><div><strong>{{ week.sessions }}</strong><span>buổi đã ghi</span></div><div><strong>{{ number(Number(week.duration_seconds) / 60) }}</strong><span>phút tập</span></div><div><strong>{{ week.completed_planned_sessions }}</strong><span>theo kế hoạch</span></div></div>
      <div class="weekly-history"><p>NHỊP TẬP · 4 TUẦN <span>Chọn tuần để xem</span></p>
        <div class="weeks" role="group" aria-label="Lịch sử tập luyện theo tuần">
          <button v-for="item in summary?.weeks" :key="item.week_start" type="button" :aria-pressed="week.week_start === item.week_start" :aria-label="`Tuần từ ${shortDate(item.week_start)}: ${item.sessions} buổi`" @click="selectedWeek = item.week_start">
            <span class="week-count">{{ item.sessions }} <small>buổi</small></span><span class="week-track" aria-hidden="true"><i :style="{ width: `${Math.max(3, item.sessions / maxSessions * 100)}%` }" /></span><span class="week-date">{{ shortDate(item.week_start) }}</span>
          </button>
        </div>
      </div>
      <footer><span>Chỉ tính buổi trong kế hoạch đã đến hạn.</span><button v-if="graph.nodes.some(node => node.id === 'hub:training' && node.children)" type="button" @click="emit('explore', 'hub:training')">Buổi tập <ArrowUpRight :size="12" /></button></footer>
    </template>
  </section>
</template>

<style scoped>
.training-widget { container: training / inline-size; min-width: 0; padding: clamp(16px, 2.2cqi, 24px); border: 1px solid #e3a37f26; border-radius: 18px; background: linear-gradient(125deg, #e3a37f08, transparent 60%), #14171d; }
.widget-head { display: flex; justify-content: space-between; gap: 12px; }
.eyeline { display: flex; align-items: center; gap: 6px; margin: 0 0 7px; font: 9px 'JetBrains Mono', monospace; letter-spacing: .12em; color: #e3a37f; }
h3 { margin: 0; font-size: 14px; font-weight: 500; color: #e9e8e2; }
.refresh { align-self: flex-start; display: grid; place-items: center; width: 30px; height: 30px; border: 1px solid #ffffff13; border-radius: 50%; color: #c1a08b; }
.refresh:hover { background: #e3a37f12; }
.progress-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 23px 0 14px; }
.week-label { font-size: 10px; color: #a99c93; }
.progress-heading p { margin: 4px 0 0; }
.progress-heading p strong { font-family: 'Playfair Display', serif; font-size: clamp(28px, 8cqi, 42px); color: #f0e3d8; transition: font-size 200ms; }
.progress-heading p > span { color: #b3a69b; font-size: 11px; }
.progress-percent { display: flex; align-items: center; gap: 3px; font: 24px 'JetBrains Mono', monospace; color: #e3a37f; }
.progress-percent small { font-size: 12px; }.progress-percent.complete { color: #a8cf9a; }
.progress-track { height: 10px; border-radius: 8px; overflow: hidden; background: #ffffff0a; }
.progress-track > span { display: block; width: 100%; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #a86d4c, #edbb99); transform-origin: left; transition: transform 750ms cubic-bezier(.2,.8,.2,1); }
.progress-note { color: #b1a499; font-size: 11px; margin: 10px 0 20px; line-height: 1.6; }
.training-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; padding: 14px 0; border-block: 1px solid #ffffff0c; }
.training-stats > div { display: flex; flex-direction: column; gap: 5px; }
.training-stats strong { color: #f0e3d8; font: 18px 'JetBrains Mono', monospace; }.training-stats span { color: #a59c96; font-size: 10px; }
.weekly-history { margin-top: 18px; }.weekly-history > p { display: flex; justify-content: space-between; gap: 10px; color: #ba9b83; font: 9px 'JetBrains Mono', monospace; margin: 0 0 10px; }.weekly-history > p span { color: #8f8c86; font: 10px Geist, sans-serif; }
.weeks { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.weeks button { display: flex; flex-direction: column; gap: 8px; text-align: left; padding: 10px 8px; border: 1px solid transparent; border-radius: 9px; transition: background 200ms, border-color 200ms, transform 200ms; }
.weeks button:hover { background: #ffffff05; transform: translateY(-2px); }.weeks button[aria-pressed=true] { border-color: #e3a37f38; background: #e3a37f0a; }
.week-count { font: 13px 'JetBrains Mono', monospace; color: #e0c4af; }.week-count small { font: 9px Geist, sans-serif; color: #a8988d; }
.week-track { display: block; height: 4px; background: #ffffff08; border-radius: 4px; }.week-track i { display: block; height: 100%; background: #e3a37f; border-radius: inherit; transition: width 400ms; opacity: .65; }.week-date { font-size: 10px; color: #a99c93; }
footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 14px; font-size: 10px; color: #8f8c86; line-height: 1.6; } footer button { display: flex; align-items: center; gap: 4px; white-space: nowrap; color: #e3a37f; min-height: 26px; }
.notice { padding: 12px; border: 1px solid #e3a37f33; border-radius: 10px; font-size: 11px; color: #d4b69f; line-height: 1.6; }.notice button { text-decoration: underline; margin-left: 4px; }
.loading-state { padding: 35px 0; color: #b1a499; font-size: 11px; }.loading-state span { display: block; margin-top: 16px; height: 10px; border-radius: 6px; background: #e3a37f15; }
.spinning { animation: spin 1s linear infinite; }@keyframes spin { to { transform: rotate(360deg); } }
@container training (max-width: 360px) { .weeks { grid-template-columns: repeat(2, 1fr); } .training-stats strong { font-size: 16px; } }
@container training (min-width: 560px) { .training-stats strong { font-size: 22px; } .weeks button { padding: 12px 10px; } }
@media (prefers-reduced-motion: reduce) { .progress-track > span, .week-track i, .weeks button { transition: none; }.weeks button:hover { transform: none; }.spinning { animation: none; } }
</style>
