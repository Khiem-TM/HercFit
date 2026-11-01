<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Activity, Loader2, RefreshCw } from 'lucide-vue-next'
import type { Capability, OperationRead } from '@/types/api'
import { CURSOR_TEXT, OPERATION_TEXT, type HealthApi, waitForOperation } from './api'

const props = defineProps<{ api: HealthApi; active: boolean }>()
const emit = defineEmits<{ synced: [] }>()

const capabilities = ref<Capability[]>([])
const ingestMode = ref('off')
const operation = ref<OperationRead | null>(null)
const busy = ref(false)
const error = ref<string | null>(null)
const expanded = ref(false)

const LABELS: Record<string, string> = {
  steps: 'Bước chân', 'heart-rate': 'Nhịp tim', sleep: 'Giấc ngủ', exercise: 'Buổi tập', weight: 'Cân nặng',
  'daily-resting-heart-rate': 'Nhịp tim nghỉ', 'daily-heart-rate-variability': 'HRV', 'hydration-log': 'Nước uống',
  'total-calories': 'Năng lượng tiêu hao', 'oxygen-saturation': 'SpO₂', 'skin-temperature-sensors': 'Nhiệt độ da',
}
const tracked = computed(() => capabilities.value.filter(item => item.enabled && item.granted))
const shown = computed(() => (expanded.value ? tracked.value : tracked.value.filter(item => item.data_type in LABELS)))
const progress = computed(() => {
  const jobs = operation.value?.jobs
  if (!jobs?.total) return null
  const done = Object.entries(jobs.by_state).filter(([state]) => !['QUEUED', 'RETRY', 'RUNNING'].includes(state))
    .reduce((sum, [, count]) => sum + count, 0)
  return `${done}/${jobs.total}`
})

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

async function sync(): Promise<void> {
  busy.value = true
  error.value = null
  try {
    const { operation_id: id } = await props.api.startSync()
    await waitForOperation(props.api, id, op => { operation.value = op })
    await load()
    emit('synced')
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Không đồng bộ được.'
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-3 rounded-2xl border border-ink/[0.08] bg-panel p-4 text-xs">
    <div class="flex items-center gap-2">
      <Activity class="h-4 w-4 text-primary" />
      <h4 class="flex-1 text-sm font-medium text-primary">Tiến độ đồng bộ theo loại dữ liệu</h4>
      <button
        v-if="active && ingestMode === 'primary'" type="button" :disabled="busy"
        class="inline-flex items-center gap-1.5 rounded-xl border border-ink/20 px-3 py-1.5 font-semibold text-primary hover:bg-ink/10 disabled:opacity-40"
        @click="sync"
      >
        <Loader2 v-if="busy" class="h-3.5 w-3.5 animate-spin" /><RefreshCw v-else class="h-3.5 w-3.5" />
        Đồng bộ và theo dõi
      </button>
    </div>
    <p v-if="error" class="rounded-xl border border-error/40 bg-error/10 px-3 py-2 text-error">{{ error }}</p>
    <p v-if="operation" class="text-on-surface-variant">
      {{ OPERATION_TEXT[operation.state] }}<template v-if="progress"> · {{ progress }} công việc</template>
    </p>
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
