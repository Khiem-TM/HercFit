<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Activity } from 'lucide-vue-next'
import type { Capability } from '@/types/api'
import { CURSOR_TEXT, type HealthApi } from './api'

const props = defineProps<{ api: HealthApi }>()

const capabilities = ref<Capability[]>([])
const ingestMode = ref('off')
const error = ref<string | null>(null)
const expanded = ref(false)

const LABELS: Record<string, string> = {
  steps: 'Bước chân', 'heart-rate': 'Nhịp tim', sleep: 'Giấc ngủ', exercise: 'Buổi tập', weight: 'Cân nặng',
  'daily-resting-heart-rate': 'Nhịp tim nghỉ', 'daily-heart-rate-variability': 'HRV', 'hydration-log': 'Nước uống',
  'total-calories': 'Năng lượng tiêu hao', 'oxygen-saturation': 'SpO₂', 'skin-temperature-sensors': 'Nhiệt độ da',
}
const tracked = computed(() => capabilities.value.filter(item => item.enabled && item.granted))
const shown = computed(() => (expanded.value ? tracked.value : tracked.value.filter(item => item.data_type in LABELS)))
function day(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleDateString('vi-VN') : '—'
}

async function load(): Promise<void> {
  try {
    const result = await props.api.capabilities()
    capabilities.value = result.capabilities
    ingestMode.value = result.ingest_mode
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Không tải được trạng thái đồng bộ.'
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-3 rounded-2xl border border-ink/[0.08] bg-panel p-4 text-xs">
    <div class="flex items-center gap-2">
      <Activity class="h-4 w-4 text-primary" />
      <h4 class="flex-1 text-sm font-medium text-primary">Tiến độ đồng bộ theo loại dữ liệu</h4>

    </div>
    <p v-if="error" class="rounded-xl border border-error/40 bg-error/10 px-3 py-2 text-error">{{ error }}</p>

    <div class="grid gap-1">
      <div v-for="item in shown" :key="item.data_type" class="flex items-center justify-between gap-2">
        <span class="text-outline">{{ LABELS[item.data_type] ?? item.data_type }}
          <span v-if="item.beta" class="rounded-full bg-sky-400/15 px-1.5 text-[10px] text-sky-300">thử nghiệm</span>
          <span v-if="item.sensitive" class="rounded-full bg-amber-400/15 px-1.5 text-[10px] text-amber-300">nhạy cảm</span>
        </span>
        <span class="text-primary">{{ item.cursor ? `${CURSOR_TEXT[item.cursor.status] ?? item.cursor.status} · đến ${day(item.cursor.complete_through)}` : 'Chờ đồng bộ' }}</span>
      </div>
      <p v-if="!tracked.length" class="text-outline">Chưa có loại dữ liệu nào được cấp quyền và bật.</p>
    </div>
    <button v-if="tracked.length > shown.length || expanded" type="button" class="text-[11px] text-outline underline-offset-2 hover:underline" @click="expanded = !expanded">
      {{ expanded ? 'Thu gọn' : `Xem tất cả ${tracked.length} loại` }}
    </button>
    <p v-if="ingestMode === 'off'" class="text-[11px] text-outline">Máy chủ đang dùng đồng bộ cũ; bảng trạng thái chi tiết đầy đủ khi bật pipeline mới.</p>
  </div>
</template>
