<script setup lang="ts">
import { computed, onUnmounted, shallowRef } from 'vue'
import { HeartPulse, Info, Link2, RefreshCw, RotateCw } from 'lucide-vue-next'
import { useHealthIntegration } from '@/composables/useHealthIntegration'
import ActivityCard from './ActivityCard.vue'
import DailyTable from './DailyTable.vue'
import EnergyCard from './EnergyCard.vue'
import HeartCard from './HeartCard.vue'
import ProfileCard from './ProfileCard.vue'
import RecordsCard from './RecordsCard.vue'
import SleepCard from './SleepCard.vue'
import SourceCard from './SourceCard.vue'
import { dayLabel, moment } from './healthFormat'
import { useHealthData } from './useHealthData'

const emit = defineEmits<{ connect: []; 'edit-profile': [] }>()
const RANGES = [7, 14, 28, 90]
const windowDays = shallowRef(28)
const { data, loading, failed, refresh } = useHealthData(() => windowDays.value)
const { syncNow, busy: syncing } = useHealthIntegration()
const syncNote = shallowRef<string | null>(null)
const timers: number[] = []

const connection = computed(() => data.value?.connection ?? null)
const connected = computed(() => connection.value?.status === 'ACTIVE' || connection.value?.status === 'NEEDS_REAUTH')
const hasDeviceData = computed(() => !!data.value && (data.value.daily.length + data.value.sleep.length + data.value.workouts.length
  + data.value.measurements.length + data.value.samples.length) > 0)
const FAILED: Record<string, string> = {
  connection: 'trạng thái kết nối', profile: 'hồ sơ', overview: 'phân tích', daily: 'số liệu ngày', sleep: 'giấc ngủ',
  workouts: 'buổi vận động', samples: 'chỉ số sinh tồn', progress: 'tiến độ', measurements: 'số đo',
}

async function sync() {
  syncNote.value = null
  if (await syncNow()) {
    syncNote.value = 'Đang đồng bộ, số liệu sẽ cập nhật sau ít giây.'
    for (const delay of [5000, 15000]) timers.push(window.setTimeout(refresh, delay))
  } else {
    syncNote.value = 'Chưa bắt đầu được đồng bộ. Mở Quản lý kết nối để kiểm tra.'
  }
}
onUnmounted(() => timers.forEach(window.clearTimeout))
</script>

<template>
  <div class="health">
    <div class="filters">
      <div class="picker" role="group" aria-label="Khoảng thời gian">
        <button v-for="days in RANGES" :key="days" type="button" :aria-pressed="windowDays === days" @click="windowDays = days">{{ days }} ngày</button>
      </div>
      <span v-if="data" class="window">{{ dayLabel(data.start) }} → {{ dayLabel(data.end) }}</span>
      <button type="button" class="icon" aria-label="Tải lại dữ liệu sức khoẻ" :disabled="loading" @click="refresh"><RefreshCw :size="13" :class="{ spinning: loading }" /></button>
      <button v-if="connection?.status === 'ACTIVE'" type="button" class="action" :disabled="syncing" @click="sync"><RotateCw :size="12" :class="{ spinning: syncing }" />Đồng bộ ngay</button>
    </div>
    <p v-if="syncNote" class="hint" role="status">{{ syncNote }}</p>
    <p v-if="connected && connection?.last_sync_at" class="hint">Đồng bộ gần nhất {{ moment(connection.last_sync_at) }} · dữ liệu từ thiết bị qua Google Health.</p>

    <div v-if="!data" class="loading" role="status">Đang tải dữ liệu sức khoẻ…</div>
    <template v-else>
      <section v-if="!connected || connection?.status === 'NEEDS_REAUTH'" class="cta">
        <HeartPulse :size="22" :stroke-width="1.4" />
        <div>
          <h3>{{ connection?.status === 'NEEDS_REAUTH' ? 'Kết nối Google Health đã hết hạn' : 'Kết nối Google Health' }}</h3>
          <p>{{ connection?.status === 'NEEDS_REAUTH'
            ? 'Google giới hạn quyền ở chế độ thử nghiệm trong 7 ngày. Kết nối lại để tiếp tục đồng bộ; dữ liệu cũ vẫn hiển thị bên dưới.'
            : 'Đồng bộ bước chân, giấc ngủ, nhịp tim nghỉ, HRV, SpO2, buổi vận động và số đo cơ thể từ đồng hồ, vòng đeo hoặc cân thông minh bằng chính Gmail bạn đăng nhập.' }}</p>
        </div>
        <button type="button" @click="emit('connect')"><Link2 :size="13" />{{ connection?.status === 'NEEDS_REAUTH' ? 'Kết nối lại' : 'Kết nối' }}</button>
      </section>
      <p v-if="failed.length" class="hint warn"><Info :size="12" />Chưa tải được: {{ failed.map(name => FAILED[name] ?? name).join(', ') }}.</p>
      <ul v-if="data.overview?.notes.length && hasDeviceData" class="notes">
        <li v-for="note in data.overview.notes" :key="note"><Info :size="12" />{{ note }}</li>
      </ul>

      <div class="grid" :class="{ refetching: loading }">
        <ProfileCard class="wide" :profile="data.profile" @edit="emit('edit-profile')" />
        <template v-if="hasDeviceData || connected">
          <ActivityCard class="wide" :data="data" />
          <SleepCard class="wide" :data="data" />
          <HeartCard :data="data" />
          <EnergyCard :data="data" />
          <RecordsCard class="wide" :data="data" />
          <DailyTable class="wide" :data="data" />
        </template>
        <SourceCard class="wide" :connection="connection" @manage="emit('connect')" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.health { display: flex; flex-direction: column; gap: 12px; padding: 14px var(--gutter, 26px) 26px; }
.filters { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.picker { display: flex; gap: 3px; padding: 3px; border: 1px solid #ffffff0e; border-radius: 9px; background: #0e1116; }
.picker button { padding: 6px 10px; border-radius: 6px; font-size: 10.5px; color: #9b9fa5; transition: background 180ms, color 180ms; }
.picker button[aria-pressed=true] { background: #8fc3d41c; color: #cfe7ef; }
.window { font: 10px 'JetBrains Mono', monospace; color: #8d949c; }
.icon { display: grid; place-items: center; width: 28px; height: 28px; margin-left: auto; border: 1px solid #ffffff13; border-radius: 50%; color: #a9c9d4; }
.icon:hover { background: #8fc3d412; }
.action { display: inline-flex; align-items: center; gap: 6px; padding: 6px 11px; border: 1px solid #8fc3d440; border-radius: 9px; font-size: 10.5px; color: #cfe7ef; }
.action:hover { background: #8fc3d412; }
.action:disabled, .icon:disabled { opacity: .5; }
.hint { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 10.5px; color: #8d949c; }
.hint.warn { color: #e8c07d; }
.notes { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 4px; }
.notes li { display: flex; align-items: flex-start; gap: 6px; font-size: 10.5px; line-height: 1.55; color: #c9b98f; }
.notes li svg { flex: none; margin-top: 2px; }
.loading { padding: 40px 0; text-align: center; font-size: 12px; color: #a3a8ae; }
.cta { display: flex; align-items: center; gap: 14px; padding: 16px 18px; border: 1px solid #3987e540; border-radius: 16px; background: linear-gradient(120deg, #3987e514, transparent 70%), #14171d; color: #a9c8f2; }
.cta h3 { margin: 0; font-size: 13.5px; font-weight: 500; color: #ecebe6; }
.cta p { margin: 4px 0 0; font-size: 11px; line-height: 1.6; color: #a3a8ae; }
.cta button { display: inline-flex; flex: none; align-items: center; gap: 6px; padding: 8px 13px; border-radius: 10px; background: #f1f0eb; color: #101216; font-size: 11px; font-weight: 600; }
.grid { display: grid; gap: 16px; grid-template-columns: minmax(0, 1fr); transition: opacity 200ms; }
/* A refetch keeps the previous frame, dimmed, instead of flashing skeletons. */
.grid.refetching { opacity: .55; }
.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@container observatory (max-width: 480px) { .cta { flex-direction: column; align-items: flex-start; } }
@container observatory (min-width: 960px) {
  .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .grid > .wide { grid-column: 1 / -1; }
}
@media (prefers-reduced-motion: reduce) { .spinning { animation: none; } .grid { transition: none; } }
</style>
