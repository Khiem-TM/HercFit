<script setup lang="ts">
import { computed } from 'vue'
import { ChevronLeft, TriangleAlert } from 'lucide-vue-next'
import type { DailyAssessment, HealthConnection } from '@/types/api'
import SleepLogForm from '@/components/knowledge/health/SleepLogForm.vue'
import { longDate, ddmmyyyy, stamp } from './format'
import { metricRows, readinessView } from './today'

/** "Cơ sở đánh giá": số đo hôm nay so với mức nền, lý do và gợi ý — đều do backend tính. */
const props = defineProps<{ assessment: DailyAssessment | null; connection: HealthConnection | null }>()
const emit = defineEmits<{ back: []; ask: [text: string]; logged: [] }>()

const view = computed(() => readinessView(props.assessment, props.connection))
const rows = computed(() => (props.assessment ? metricRows(props.assessment) : []))
const reasons = computed(() => (props.assessment?.reasons ?? []).filter(reason => reason.kind !== 'data'))
const missing = computed(() => (props.assessment?.reasons ?? []).filter(reason => reason.kind === 'data'))
const badge = computed(() => ({ ready: 'b-ready', reduce: 'b-reduce', none: 'b-none' })[view.value.kind])
const sleepMissing = computed(() => !!props.assessment && !props.assessment.sleep?.last_night
  && props.connection?.status === 'ACTIVE')
const title = computed(() => (props.assessment ? `${longDate(props.assessment.date)}/${props.assessment.date.slice(0, 4)}` : ''))
</script>

<template>
  <div class="layer">
    <button type="button" class="hf-back" @click="emit('back')"><ChevronLeft :size="18" aria-hidden="true" />Hôm nay</button>
    <div class="hf-grid" style="margin-top: 16px">
      <section class="hf-card hf-c7">
        <span class="hf-lbl">Cơ sở đánh giá{{ assessment ? ` · ${title}` : '' }}</span>
        <div class="headline">
          <span class="badge" :class="badge" />
          <div class="hf-big" style="font-size: 30px">{{ view.title }}</div>
          <span v-if="view.confidence" class="hf-pill">{{ view.confidence }}</span>
          <span v-if="view.score != null" class="hf-pill ok">{{ view.score }} / 100</span>
        </div>
        <div>
          <div v-for="row in rows" :key="row.label" class="hf-kv">
            <div><b>{{ row.label }}</b><br><span>{{ row.context }}</span></div>
            <div class="right"><div class="v">{{ row.value }}</div><span>{{ row.base }}</span></div>
          </div>
        </div>
        <div class="hf-mut small">Thời điểm đồng bộ: {{ stamp(assessment?.data_quality.last_sync_at ?? connection?.last_sync_at) }}</div>
        <p v-if="assessment" class="hf-mut tiny">{{ assessment.disclaimer }}</p>
      </section>
      <div class="hf-c5 hf-stack">
        <section class="hf-card">
          <h3 class="hf-h3">Lý do tạo nên đánh giá</h3>
          <ul v-if="reasons.length" class="list"><li v-for="reason in reasons" :key="reason.code">{{ reason.text }}</li></ul>
          <p v-else class="hf-mut small">{{ assessment?.summary ?? 'Chưa có đánh giá hôm nay.' }}</p>
        </section>
        <section v-if="missing.length || sleepMissing" class="hf-card">
          <h3 class="hf-h3">Dữ liệu còn thiếu</h3>
          <div v-for="reason in missing" :key="reason.code" class="hf-warn"><TriangleAlert :size="16" aria-hidden="true" />{{ reason.text }}</div>
          <SleepLogForm v-if="sleepMissing && assessment" :day="assessment.date" @saved="emit('logged')" />
        </section>
        <section class="hf-card">
          <h3 class="hf-h3">Gợi ý từ hệ thống</h3>
          <ul v-if="assessment?.recommendations.length" class="list">
            <li v-for="tip in assessment.recommendations" :key="tip.code">{{ tip.text }}</li>
          </ul>
          <p v-else class="hf-mut small">Kết nối Google Health để nhận gợi ý mỗi ngày.</p>
          <button type="button" class="hf-btn" @click="emit('ask', 'Giải thích đánh giá sẵn sàng hôm nay của mình.')">Hỏi trợ lý về đánh giá này</button>
        </section>
      </div>
    </div>
    <p v-if="assessment" class="hf-mut tiny method">{{ assessment.method }} · ngày {{ ddmmyyyy(assessment.date) }}</p>
  </div>
</template>

<style scoped>
.headline { display: flex; align-items: center; gap: 14px 18px; flex-wrap: wrap; }
.badge { width: 14px; height: 14px; border-radius: 50%; flex: none; }
.b-ready { background: var(--hf-ink); box-shadow: 0 0 0 6px var(--hf-track); }
.b-reduce { background: #C2410C; box-shadow: 0 0 0 6px #FDE3D2; }
:root.dark .b-reduce { box-shadow: 0 0 0 6px #4A2614; }
.b-none { border: 2px dashed var(--hf-faint); }
.right { text-align: right; }
.small { font-size: 13px; margin: 0; }
.tiny { font-size: 12px; line-height: 1.5; margin: 0; }
.method { margin-top: 16px; }
.list { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 8px; font-size: 14px; line-height: 1.5; }
</style>
