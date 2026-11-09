<script setup lang="ts">
import { computed, ref } from 'vue'
import type { HealthConnection } from '@/types/api'
import { OWNERSHIP, typeLabel } from './api'

/** Trạng thái đọc của từng loại dữ liệu Google Health ở lần đồng bộ gần nhất ("Đồng bộ ngay" nằm ở thẻ kết nối). */
const props = defineProps<{ connection: HealthConnection }>()

const expanded = ref(false)
// Các loại thường gặp được hiện trước; phần còn lại nằm sau "Xem tất cả".
const MAIN = ['steps', 'total-calories', 'sleep', 'exercise', 'daily-resting-heart-rate', 'daily-heart-rate-variability',
  'weight', 'hydration-log']
const ERROR_TEXT: Record<string, string> = { not_granted: 'chưa cấp quyền', incomplete: 'chưa đọc hết' }

const rows = computed(() => {
  const types = props.connection.types ?? {}
  const counts = props.connection.records ?? {}
  return [...new Set([...Object.keys(types), ...Object.keys(counts)])]
    .map(type => ({ type, label: typeLabel(type), count: counts[type] ?? 0, ...types[type] }))
    .sort((a, b) => (MAIN.indexOf(a.type) + 1 || 99) - (MAIN.indexOf(b.type) + 1 || 99) || a.label.localeCompare(b.label, 'vi'))
})
const shown = computed(() => (expanded.value ? rows.value : rows.value.filter(row => MAIN.includes(row.type) || row.error)))
const failed = computed(() => rows.value.filter(row => row.error).length)

const day = (value: string | null | undefined) => (value ? value.split('-').reverse().join('/') : '—')
function state(row: { error?: string | null; through?: string | null; count: number }): string {
  if (row.error) return ERROR_TEXT[row.error] ?? 'lỗi khi đọc'
  if (!row.through) return 'chờ đồng bộ'
  return row.count ? `${row.count} bản ghi · đến ${day(row.through)}` : `không có dữ liệu · đến ${day(row.through)}`
}
</script>

<template>
  <div class="status">
    <div v-for="row in shown" :key="row.type" class="hf-kv">
      <b>{{ row.label }}</b><span class="v small" :class="{ warn: row.error }">{{ state(row) }}</span>
    </div>
    <p v-if="!rows.length" class="hf-mut note">Chưa có lần đồng bộ nào. Lần đầu đọc lại 90 ngày gần nhất.</p>
    <button v-if="rows.length > shown.length || expanded" type="button" class="hf-lnk" @click="expanded = !expanded">
      {{ expanded ? 'Thu gọn' : `Xem tất cả ${rows.length} loại` }}
    </button>
    <p v-if="failed" class="hf-warn">{{ failed }} loại chưa đọc được ở lần gần nhất; dữ liệu cũ của chúng được giữ nguyên.</p>
    <dl class="owners">
      <div v-for="item in OWNERSHIP" :key="item.title"><dt>{{ item.title }}</dt><dd class="hf-mut">{{ item.detail }}</dd></div>
    </dl>
  </div>
</template>

<style scoped>
.status { display: flex; flex-direction: column; gap: 4px; }
.small { font-size: 13px !important; font-weight: 500 !important; }
.warn { color: var(--hf-warn-text) !important; }
.note { font-size: 13px; margin: 0; }
.owners { margin: 8px 0 0; padding-top: 10px; border-top: 1px solid var(--hf-line-2); display: flex; flex-direction: column; gap: 8px; }
.owners dt { font-size: 13px; font-weight: 600; }
.owners dd { margin: 2px 0 0; font-size: 12px; line-height: 1.45; }
</style>
