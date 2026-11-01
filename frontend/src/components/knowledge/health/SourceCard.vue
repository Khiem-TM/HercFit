<script setup lang="ts">
import { computed } from 'vue'
import { Link2 } from 'lucide-vue-next'
import type { HealthConnection } from '@/types/api'
import { SCOPE_LABELS, UNIT_LABELS, fmt, moment, scopeKey } from './healthFormat'

const props = defineProps<{ connection: HealthConnection | null }>()
const emit = defineEmits<{ manage: [] }>()
const RECORDS: Record<string, string> = {
  daily_days: 'Ngày tổng hợp', sleep_sessions: 'Phiên ngủ', device_workouts: 'Buổi vận động',
  body_metrics: 'Số đo cơ thể', health_samples: 'Chỉ số sinh tồn',
}
const RUN: Record<string, string> = { RUNNING: 'đang chạy', SUCCEEDED: 'thành công', PARTIAL: 'một phần', FAILED: 'lỗi' }
const provider = computed(() => {
  const p = props.connection?.provider_profile ?? {}
  return [
    p.age != null ? ['Tuổi theo Google', `${p.age}`] : null,
    p.membership_start_date ? ['Thành viên từ', String(p.membership_start_date).split('-').reverse().join('/')] : null,
    p.walking_stride_mm ? ['Sải chân khi đi', `${fmt(Number(p.walking_stride_mm) / 10, 1)} cm`] : null,
    p.running_stride_mm ? ['Sải chân khi chạy', `${fmt(Number(p.running_stride_mm) / 10, 1)} cm`] : null,
    p.weight_unit ? ['Đơn vị cân nặng', UNIT_LABELS[String(p.weight_unit)] ?? String(p.weight_unit)] : null,
    p.height_unit ? ['Đơn vị chiều cao', UNIT_LABELS[String(p.height_unit)] ?? String(p.height_unit)] : null,
    p.distance_unit ? ['Đơn vị quãng đường', UNIT_LABELS[String(p.distance_unit)] ?? String(p.distance_unit)] : null,
    p.language_locale ? ['Ngôn ngữ', String(p.language_locale)] : null,
  ].filter((row): row is string[] => row !== null)
})
const scopes = computed(() => (props.connection?.granted_scopes ?? []).map(scope => SCOPE_LABELS[scopeKey(scope)] ?? scopeKey(scope)))
const missing = computed(() => (props.connection?.missing_scopes ?? []).map(scope => SCOPE_LABELS[scopeKey(scope)] ?? scopeKey(scope)))
const errors = computed(() => Object.keys((props.connection?.last_run?.counts?.errors as Record<string, string> | undefined) ?? {}))
</script>

<template>
  <section class="card" aria-labelledby="source-title">
    <header class="card-head">
      <div><p class="eyeline"><Link2 :size="13" /> NGUỒN DỮ LIỆU</p><h3 id="source-title">Google Health</h3></div>
      <button type="button" class="link" @click="emit('manage')">Quản lý kết nối</button>
    </header>
    <dl v-if="connection?.connected">
      <div><dt>Tài khoản</dt><dd>{{ connection.account_email }}</dd></div>
      <div><dt>Lần đồng bộ gần nhất</dt><dd>{{ moment(connection.last_sync_at) }}<template v-if="connection.last_run"> · {{ RUN[connection.last_run.status] }}</template></dd></div>
      <div><dt>Lần kế tiếp</dt><dd>{{ moment(connection.next_sync_at) }}</dd></div>
      <div><dt>Múi giờ</dt><dd>{{ connection.timezone ?? 'Asia/Ho_Chi_Minh (mặc định)' }}</dd></div>
      <div><dt>Trợ lý được dùng dữ liệu</dt><dd>{{ connection.share_with_assistant ? 'Có (tổng hợp theo ngày)' : 'Không' }}</dd></div>
      <div v-for="[label, value] in provider" :key="label"><dt>{{ label }}</dt><dd>{{ value }}</dd></div>
    </dl>
    <div v-if="connection?.connected" class="records">
      <span v-for="(label, key) in RECORDS" :key="key"><strong>{{ connection.records[key] ?? 0 }}</strong>{{ label }}</span>
    </div>
    <p v-if="scopes.length" class="note">Quyền đã cấp: {{ scopes.join(', ') }}.<template v-if="missing.length"> Chưa cấp: {{ missing.join(', ') }}.</template></p>
    <p v-if="errors.length" class="note">Lần đồng bộ gần nhất chưa đọc được: {{ errors.join(', ') }}.</p>
    <p v-if="!connection?.connected" class="note">Chưa kết nối. Dữ liệu ở trên chỉ gồm những gì bạn khai báo.</p>
  </section>
</template>

<style scoped src="./healthCard.css"></style>
<style scoped>
.link { font-size: 10px; color: light-dark(#2d4952, #a9c9d4); border-bottom: 1px solid light-dark(#2d495255, #a9c9d455); }
dl { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 10px 18px; margin: 16px 0 0; }
dl div { min-width: 0; }
dt { font-size: 10px; color: light-dark(#60676e, #8d949c); }
dd { margin: 3px 0 0; font-size: 11.5px; color: light-dark(#2d2d28, #e4e3dd); overflow-wrap: anywhere; }
.records { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.records span { display: flex; align-items: baseline; gap: 5px; padding: 6px 10px; border: 1px solid light-dark(#18181810, #ffffff10); border-radius: 10px; font-size: 10px; color: light-dark(#53575d, #a3a8ae); }
.records strong { font: 600 13px Geist, sans-serif; color: light-dark(#24231f, #f1f0eb); }
</style>
