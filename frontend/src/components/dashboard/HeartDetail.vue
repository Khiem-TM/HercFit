<script setup lang="ts">
import { computed, onUnmounted, shallowRef, watch } from 'vue'
import { ChevronLeft, ChevronRight, RefreshCw } from 'lucide-vue-next'
import type { HeartRateHour } from '@/types/api'
import { useAuth } from '@/composables/useAuth'
import { dashboardTimezone, localDay, shiftDay } from '@/components/knowledge/dashboard/dashboardData'
import { createHealthApi } from '@/features/health-integration/api'
import { refreshKnowledgeHealth } from '@/features/health-integration/knowledgeSync'
import BarChart from './charts/BarChart.vue'
import { chart, distribution, hours, summary } from './heart'
import { longDate } from './format'

/** Nhịp tim từng giờ của một ngày (rollUp theo giờ của Google Health). Mở trang là yêu cầu một lượt đồng bộ. */
const emit = defineEmits<{ back: [] }>()
const { authFetch } = useAuth()

const today = localDay(new Date())
const day = shallowRef(today)
const rows = shallowRef<HeartRateHour[]>([])
const loading = shallowRef(true)
const error = shallowRef('')
const syncing = shallowRef(true)
let controller: AbortController | undefined
const syncControl = new AbortController()

async function load() {
  controller?.abort()
  const current = new AbortController()
  controller = current
  loading.value = true
  error.value = ''
  try {
    const query = new URLSearchParams({ date: day.value, timezone: dashboardTimezone })
    const response = await authFetch(`/api/health/heart-rate/hourly?${query}`, { signal: current.signal })
    if (!response.ok) throw new Error(String(response.status))
    rows.value = await response.json() as HeartRateHour[]
  } catch {
    if (current.signal.aborted) return
    rows.value = []
    error.value = 'Không tải được nhịp tim của ngày này.'
  }
  if (!current.signal.aborted) loading.value = false
}

watch(day, load, { immediate: true })
// Dữ liệu đã lưu hiện ngay; lượt đồng bộ xong thì tải lại để thấy các giờ mới nhất.
void refreshKnowledgeHealth(createHealthApi((url, init) => authFetch(url, init)), syncControl.signal)
  .then(synced => { if (synced) void load() })
  .catch(() => undefined)
  .finally(() => { syncing.value = false })
onUnmounted(() => { controller?.abort(); syncControl.abort() })

const parsed = computed(() => hours(rows.value))
const bars = computed(() => chart(parsed.value))
const spread = computed(() => distribution(parsed.value))
const stats = computed(() => summary(parsed.value))
const title = computed(() => (day.value === today ? 'Hôm nay' : longDate(day.value)))
</script>

<template>
  <div class="layer">
    <button type="button" class="hf-back" @click="emit('back')"><ChevronLeft :size="18" aria-hidden="true" />Hôm nay</button>
    <div class="hf-grid" style="margin-top: 16px">
      <div class="hf-c8 hf-stack">
        <section class="hf-card" aria-labelledby="hr-title">
          <div class="hf-hd">
            <h2 id="hr-title" class="hf-lbl">Nhịp tim theo giờ</h2>
            <span v-if="syncing" class="hf-pill sync"><RefreshCw :size="12" aria-hidden="true" class="spin" />Đang đồng bộ</span>
          </div>
          <div class="days">
            <button type="button" class="hf-btn icon" aria-label="Ngày trước" @click="day = shiftDay(day, -1)">
              <ChevronLeft :size="18" aria-hidden="true" /></button>
            <span class="day">{{ title }}</span>
            <button type="button" class="hf-btn icon" aria-label="Ngày sau" :disabled="day >= today" @click="day = shiftDay(day, 1)">
              <ChevronRight :size="18" aria-hidden="true" /></button>
          </div>
          <div v-if="error" class="hf-err" role="alert"><span>{{ error }}</span>
            <button type="button" class="hf-btn on-card" @click="load()">Thử lại</button></div>
          <div v-else-if="loading && !rows.length" class="hf-sk" style="height: 260px" aria-busy="true" />
          <template v-else-if="parsed.length">
            <BarChart v-bind="bars" />
            <p class="hf-mut note">Mỗi cột là một giờ: đáy cột là nhịp thấp nhất, đỉnh là cao nhất, chỗ đổi màu là nhịp trung bình.
              Giờ không có cột là giờ thiết bị không ghi nhịp tim.</p>
          </template>
          <div v-else class="empty">
            <div class="hf-sv2">Không có nhịp tim trong ngày này</div>
            <p class="hf-mut">Thiết bị chưa ghi hoặc chưa đồng bộ nhịp tim lên Google Health cho ngày này.</p>
          </div>
        </section>
      </div>
      <div class="hf-c4 hf-stack">
        <section class="hf-card tight">
          <h3 class="hf-h3 head">Tóm tắt</h3>
          <template v-if="stats">
            <div class="hf-kv"><b>Số giờ có dữ liệu</b><span class="v">{{ stats.hours }} / 24</span></div>
            <div class="hf-kv"><b>Trung bình các giờ</b><span class="v">{{ stats.meanOfHours }} bpm</span></div>
            <div class="hf-kv"><b>Thấp nhất</b><span class="v">{{ stats.low.bpm }} bpm · {{ stats.low.at }}</span></div>
            <div class="hf-kv"><b>Cao nhất</b><span class="v">{{ stats.high.bpm }} bpm · {{ stats.high.at }}</span></div>
          </template>
          <p v-else class="hf-mut note">Chưa có dữ liệu.</p>
        </section>
        <section class="hf-card tight">
          <h3 class="hf-h3 head">Phân bố theo nhịp trung bình mỗi giờ</h3>
          <div v-for="band in spread" :key="band.label" class="band">
            <div class="row"><span>{{ band.label }} bpm</span><b>{{ band.hours }} giờ</b></div>
            <div class="bar" role="img" :aria-label="`${band.label} nhịp mỗi phút: ${band.hours} giờ`">
              <i :style="{ width: `${(band.share * 100).toFixed(1)}%` }" /></div>
          </div>
          <p class="hf-mut note">Đếm theo nhịp trung bình của từng giờ có dữ liệu; các khoảng chỉ để so sánh, không phải ngưỡng y khoa.</p>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.days { display: flex; align-items: center; gap: 12px; }
.day { font-weight: 600; font-size: 15px; min-width: 150px; text-align: center; }
.icon { width: 40px; height: 40px; padding: 0; display: inline-flex; align-items: center; justify-content: center; }
.sync { display: inline-flex; align-items: center; gap: 6px; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
.note { font-size: 12px; margin: 8px 0 0; line-height: 1.5; }
.empty { display: flex; flex-direction: column; gap: 6px; padding: 32px 0; }
.empty p { margin: 0; }
.tight { gap: 4px; }
.head { margin-bottom: 6px; }
.band { display: flex; flex-direction: column; gap: 6px; padding: 6px 0; }
.row { display: flex; justify-content: space-between; font-size: 13px; }
.bar { height: 8px; border-radius: 8px; background: var(--hf-line-2); overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: 8px; background: var(--hf-ink); }
</style>
