<script setup lang="ts">
import { computed } from 'vue'
import { Activity, Droplet, Ruler } from 'lucide-vue-next'
import { DETAIL_LABELS, SAMPLE_LABELS, detailValue, duration, exerciseLabel, fmt, moment, num } from './healthFormat'
import type { HealthData } from './useHealthData'

const props = defineProps<{ data: HealthData }>()
const workouts = computed(() => [...props.data.workouts].sort((a, b) => b.started_at.localeCompare(a.started_at)))
const measurements = computed(() => [...props.data.measurements].sort((a, b) => b.recorded_at.localeCompare(a.recorded_at)))
const samples = computed(() => [...props.data.samples].sort((a, b) => b.measured_at.localeCompare(a.measured_at)))
const types = computed(() => Object.entries(props.data.overview?.activity.workout_types ?? {}).sort((a, b) => b[1] - a[1]))

function pace(speed: unknown, type: string | null): string {
  const mps = num(speed as number | string | null)
  if (!mps) return '—'
  if (type?.includes('RUN') || type?.includes('WALK') || type === 'HIKING') {
    const seconds = Math.round(1000 / mps)
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}/km`
  }
  return `${fmt(mps * 3.6, 1)} km/h`
}
const zones = (record: Record<string, number>) => ['light', 'moderate', 'vigorous', 'peak']
  .filter(zone => record[zone]).map(zone => `${{ light: 'nhẹ', moderate: 'vừa', vigorous: 'mạnh', peak: 'đỉnh' }[zone]} ${Math.round(record[zone] / 60)}′`).join(' · ')
const details = (record: Record<string, string>) => Object.entries(record).map(([key, value]) => `${DETAIL_LABELS[key] ?? key}: ${detailValue(value)}`).join(' · ')
</script>

<template>
  <section class="card" aria-labelledby="records-title">
    <header class="card-head">
      <div><p class="eyeline"><Activity :size="13" /> BẢN GHI TỪ GOOGLE HEALTH</p><h3 id="records-title">Buổi vận động, số đo cơ thể và chỉ số sinh tồn</h3></div>
    </header>

    <h4><Activity :size="12" /> Buổi vận động <small>{{ workouts.length }}</small></h4>
    <div v-if="types.length" class="chips"><span v-for="[type, count] in types" :key="type">{{ exerciseLabel(type) }} × {{ count }}</span></div>
    <div v-if="workouts.length" class="table-wrap">
      <table>
        <thead><tr><th>Thời điểm</th><th>Hoạt động</th><th class="num">Thời lượng</th><th class="num">Quãng đường</th><th class="num">Năng lượng</th>
          <th class="num">Nhịp tim TB</th><th class="num">Phút vùng tim</th><th class="num">Pace/tốc độ</th><th class="num">Độ cao</th><th>Vùng tim</th><th>Nguồn</th></tr></thead>
        <tbody><tr v-for="workout in workouts" :key="workout.id">
          <td>{{ moment(workout.started_at) }}</td><td>{{ workout.display_name || exerciseLabel(workout.exercise_type) }}</td>
          <td class="num">{{ workout.active_seconds != null ? duration(workout.active_seconds / 60) : '—' }}</td>
          <td class="num">{{ num(workout.distance_m) != null ? `${fmt(num(workout.distance_m)! / 1000, 2)} km` : '—' }}</td>
          <td class="num">{{ num(workout.energy_kcal) != null ? `${fmt(workout.energy_kcal)} kcal` : '—' }}</td>
          <td class="num">{{ workout.avg_hr_bpm ?? '—' }}</td><td class="num">{{ workout.active_zone_minutes ?? '—' }}</td>
          <td class="num">{{ pace(workout.avg_speed_mps, workout.exercise_type) }}</td>
          <td class="num">{{ num(workout.elevation_gain_m) != null ? `${fmt(workout.elevation_gain_m)} m` : '—' }}</td>
          <td>{{ zones(workout.hr_zone_seconds) || '—' }}</td><td>{{ workout.data_source?.written_by_hercfit ? 'HercFit' : 'Thiết bị / Google' }}</td>
        </tr></tbody>
      </table>
    </div>
    <p v-else class="none">Chưa có buổi vận động nào trên Google Health trong khoảng này.</p>

    <h4><Ruler :size="12" /> Số đo cơ thể từ thiết bị <small>{{ measurements.length }}</small></h4>
    <div v-if="measurements.length" class="table-wrap">
      <table>
        <thead><tr><th>Thời điểm</th><th class="num">Cân nặng</th><th class="num">Mỡ cơ thể</th><th class="num">Chiều cao</th></tr></thead>
        <tbody><tr v-for="metric in measurements" :key="metric.id">
          <td>{{ moment(metric.recorded_at) }}</td>
          <td class="num">{{ metric.weight_kg != null ? `${fmt(metric.weight_kg, 1)} kg` : '—' }}</td>
          <td class="num">{{ metric.body_fat_pct != null ? `${fmt(metric.body_fat_pct, 1)}%` : '—' }}</td>
          <td class="num">{{ metric.height_cm != null ? `${fmt(metric.height_cm, 1)} cm` : '—' }}</td>
        </tr></tbody>
      </table>
    </div>
    <p v-else class="none">Chưa có số đo từ cân thông minh hoặc nhập trong app Google Health.</p>

    <h4><Droplet :size="12" /> Chỉ số sinh tồn rời <small>{{ samples.length }}</small></h4>
    <div v-if="samples.length" class="table-wrap">
      <table>
        <thead><tr><th>Thời điểm</th><th>Chỉ số</th><th class="num">Giá trị</th><th>Chi tiết</th></tr></thead>
        <tbody><tr v-for="sample in samples" :key="sample.id">
          <td>{{ moment(sample.measured_at) }}</td><td>{{ SAMPLE_LABELS[sample.sample_type] ?? sample.sample_type }}</td>
          <td class="num">{{ fmt(sample.value, 1) }} {{ sample.unit === 'C' ? '°C' : sample.unit }}</td><td>{{ details(sample.details) || '—' }}</td>
        </tr></tbody>
      </table>
    </div>
    <p v-else class="none">Chưa có đường huyết hay nhiệt độ cơ thể trong khoảng này.</p>
    <p class="note">Chỉ số sinh tồn rời chỉ hiển thị cho bạn; chúng không đưa vào bộ nhớ tri thức của trợ lý.</p>
  </section>
</template>

<style scoped src="./healthCard.css"></style>
<style scoped>
h4 { display: flex; align-items: center; gap: 6px; margin: 18px 0 0; font-size: 11.5px; font-weight: 500; color: light-dark(#363530, #d9d8d2); }
h4 small { font: 9.5px 'JetBrains Mono', monospace; color: light-dark(#60676e, #8d949c); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.chips span { padding: 4px 9px; border: 1px solid light-dark(#18181814, #ffffff14); border-radius: 14px; font-size: 10px; color: light-dark(#3d3f42, #c9cbcf); }
.none { margin: 8px 0 0; font-size: 10.5px; color: light-dark(#60676e, #8d949c); }
</style>
