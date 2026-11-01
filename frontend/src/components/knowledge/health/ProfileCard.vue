<script setup lang="ts">
import { computed } from 'vue'
import { AlertTriangle, IdCard } from 'lucide-vue-next'
import type { HealthProfile, ProfileValue, ValueSource } from '@/types/api'
import { ACTIVITY_LABELS, SEX_LABELS, SOURCE_LABELS, dayLabel, fmt } from './healthFormat'

/** `traits` (thói quen tập từ hồ sơ tri thức) và `map` đưa phần hồ sơ của tổng quan vào đây. */
const props = defineProps<{ profile: HealthProfile | null; traits?: string[] }>()
const emit = defineEmits<{ edit: []; map: [] }>()

const FIELDS: { key: keyof HealthProfile; label: string; unit?: string; digits?: number }[] = [
  { key: 'age', label: 'Tuổi' }, { key: 'sex', label: 'Giới tính' },
  { key: 'height_cm', label: 'Chiều cao', unit: 'cm', digits: 1 }, { key: 'weight_kg', label: 'Cân nặng', unit: 'kg', digits: 1 },
  { key: 'body_fat_pct', label: 'Mỡ cơ thể', unit: '%', digits: 1 }, { key: 'bmi', label: 'BMI', digits: 1 },
  { key: 'resting_hr_bpm', label: 'Nhịp tim nghỉ', unit: 'bpm' }, { key: 'max_hr_bpm', label: 'Nhịp tim tối đa', unit: 'bpm' },
  { key: 'hrv_ms', label: 'HRV', unit: 'ms', digits: 1 }, { key: 'vo2_max', label: 'VO2max', unit: 'ml/kg/phút', digits: 1 },
]
const MISSING: Record<string, string> = { age: 'tuổi', sex: 'giới tính', height_cm: 'chiều cao', weight_kg: 'cân nặng', activity_level: 'mức vận động' }

function noteOf(item: ProfileValue): string | null {
  // "overweight (thừa cân, ngưỡng châu Á)" keeps only the Vietnamese part.
  const label = item.label?.includes('(') ? item.label.slice(item.label.indexOf('(') + 1, -1) : item.label
  const when = item.observed_at ? `đo ${dayLabel(String(item.observed_at).slice(0, 10))}` : null
  return [label, when].filter(Boolean).join(' · ') || null
}

const tiles = computed(() => FIELDS.flatMap(field => {
  const item = props.profile?.[field.key] as ProfileValue | null | undefined
  if (!item || item.value == null) return []
  const value = field.key === 'sex' ? SEX_LABELS[String(item.value)] ?? String(item.value)
    : typeof item.value === 'number' ? fmt(item.value, field.digits ?? 0) : String(item.value)
  return [{ ...field, value, source: item.source, note: noteOf(item) }]
}))
const level = computed(() => {
  const declared = props.profile?.activity_level?.value
  const observed = props.profile?.observed_activity_level
  if (!declared && !observed) return null
  return { declared: declared ? ACTIVITY_LABELS[String(declared)] ?? String(declared) : null,
           observed: observed?.value ? ACTIVITY_LABELS[String(observed.value)] ?? String(observed.value) : null,
           note: observed?.label?.split(', ').slice(1).join(', ') ?? null }
})
const missing = computed(() => (props.profile?.missing_fields ?? []).map(key => MISSING[key] ?? key))
const sourceClass = (source: ValueSource) => source.toLowerCase()
</script>

<template>
  <section class="card" aria-labelledby="health-profile-title">
    <header class="card-head">
      <div><p class="eyeline"><IdCard :size="13" /> HỒ SƠ SỨC KHOẺ HỢP NHẤT</p><h3 id="health-profile-title">Khai báo, đo lường và suy luận</h3></div>
      <span class="actions">
        <button type="button" class="link" @click="emit('map')">Xem trên bản đồ</button>
        <button type="button" class="link" @click="emit('edit')">Sửa hồ sơ</button>
      </span>
    </header>
    <p v-if="!profile" class="empty">Chưa đọc được hồ sơ sức khoẻ.</p>
    <template v-else>
      <div class="tiles">
        <div v-for="tile in tiles" :key="tile.key" class="tile">
          <span class="tile-label">{{ tile.label }}<b :class="['source', sourceClass(tile.source)]">{{ SOURCE_LABELS[tile.source] }}</b></span>
          <strong>{{ tile.value }}<small v-if="tile.unit">{{ tile.unit }}</small></strong>
          <em v-if="tile.note">{{ tile.note }}</em>
        </div>
      </div>
      <div v-if="traits?.length" class="traits" aria-label="Thói quen tập luyện">
        <span v-for="trait in traits" :key="trait">{{ trait }}</span>
      </div>
      <div v-if="level" class="level">
        <span>Mức vận động</span>
        <p><b class="source declared">Khai báo</b>{{ level.declared ?? 'chưa khai báo' }}</p>
        <p><b class="source derived">Thực tế</b>{{ level.observed ?? 'chưa đủ 7 ngày có đeo thiết bị' }}<small v-if="level.note"> · {{ level.note }}</small></p>
      </div>
      <ul v-if="profile.conflicts.length" class="signals" aria-label="Chênh lệch giữa khai báo và số đo">
        <li v-for="conflict in profile.conflicts" :key="conflict"><AlertTriangle :size="13" />{{ conflict }}</li>
      </ul>
      <p v-if="missing.length" class="note">Còn thiếu: {{ missing.join(', ') }}. Bổ sung trong Cài đặt hoặc nhắn cho trợ lý.</p>
      <p class="note">
        Nguồn: <b class="source declared">Khai báo</b> bạn nhập · <b class="source measured">Thiết bị</b> Google Health ·
        <b class="source provider">Google</b> hồ sơ Google · <b class="source derived">Suy luận</b> hệ thống tính.
      </p>
    </template>
  </section>
</template>

<style scoped src="./healthCard.css"></style>
<style scoped>
.actions { display: flex; gap: 14px; }
.link { font-size: 10px; color: light-dark(#2d4952, #a9c9d4); border-bottom: 1px solid light-dark(#2d495255, #a9c9d455); }
.traits { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 16px; }
.traits span { padding: 4px 10px; border: 1px solid light-dark(#87671a2e, #d4b77d2e); border-radius: 20px; font-size: 10px; color: light-dark(#7f7049, #d9cba9); background: light-dark(#87671a0a, #d4b77d0a); }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(132px, 1fr)); gap: 14px 18px; margin-top: 18px; }
.tile { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.tile-label { display: flex; align-items: center; justify-content: space-between; gap: 6px; font-size: 10px; color: light-dark(#60676e, #8d949c); }
.tile strong { font: 600 clamp(18px, 4.6cqi, 22px) Geist, sans-serif; color: light-dark(#24231f, #f1f0eb); }
.tile strong small { margin-left: 4px; font-size: 10.5px; font-weight: 400; color: light-dark(#53575d, #a3a8ae); }
.tile em { font-style: normal; font-size: 10px; color: light-dark(#60676e, #8d949c); line-height: 1.45; }
.source { display: inline-block; padding: 1px 6px; border-radius: 10px; font: 500 8.5px Geist, sans-serif; letter-spacing: .02em; border: 1px solid light-dark(#1818181f, #ffffff1f); color: light-dark(#404246, #c3c6ca); white-space: nowrap; }
.source.measured { border-color: light-dark(#0d60b866, #3987e566); color: light-dark(#4f719f, #a9c8f2); }
.source.provider { border-color: light-dark(#624cc066, #9085e966); color: light-dark(#71679e, #c9c2f5); }
.source.derived { border-style: dashed; }
.level { display: grid; grid-template-columns: auto 1fr; gap: 6px 14px; align-items: baseline; margin-top: 18px; padding: 12px 0; border-block: 1px solid light-dark(#1818180c, #ffffff0c); font-size: 11px; color: light-dark(#363530, #d9d8d2); }
.level > span { grid-row: span 2; font-size: 10px; color: light-dark(#60676e, #8d949c); }
.level p { margin: 0; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.level small { color: light-dark(#60676e, #8d949c); font-size: 10px; }
.note .source { margin-right: 3px; }
</style>
