<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { BatteryMedium, Watch } from 'lucide-vue-next'
import type { DevicesRead } from '@/types/api'
import { HealthApiError, type HealthApi, sourceLabel } from './api'

const props = defineProps<{ api: HealthApi }>()

const data = ref<DevicesRead | null>(null)
const error = ref<string | null>(null)

const DEVICE_TEXT: Record<string, string> = { TRACKER: 'Thiết bị đeo', SCALE: 'Cân thông minh' }
const LABELS: Record<string, string> = {
  steps: 'bước chân', 'heart-rate': 'nhịp tim', sleep: 'giấc ngủ', exercise: 'buổi tập', weight: 'cân nặng',
  'total-calories': 'năng lượng', 'oxygen-saturation': 'SpO₂', 'hydration-log': 'nước uống',
}

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' }) : '—'
}

function types(list: string[]): string {
  const named = list.map(item => LABELS[item] ?? item)
  return named.length > 4 ? `${named.slice(0, 4).join(', ')} +${named.length - 4}` : named.join(', ')
}

async function load(): Promise<void> {
  try {
    data.value = await props.api.devices()
  } catch (err) {
    error.value = err instanceof HealthApiError && err.status === 403
      ? 'Chưa cho phép đọc dữ liệu thiết bị.'
      : err instanceof Error ? err.message : 'Không tải được thiết bị.'
  }
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <div class="space-y-3 rounded-2xl border border-ink/[0.08] bg-panel p-4 text-xs">
    <div class="flex items-center gap-2">
      <Watch class="h-4 w-4 text-primary" />
      <h4 class="text-sm font-medium text-primary">Nguồn dữ liệu và thiết bị</h4>
    </div>
    <p v-if="error" class="rounded-xl border border-error/40 bg-error/10 px-3 py-2 text-error">{{ error }}</p>
    <template v-else-if="data">
      <div v-if="data.devices.length" class="space-y-1">
        <div v-for="(device, index) in data.devices" :key="index" class="flex items-center justify-between gap-2">
          <span class="text-on-surface-variant">{{ device.device_version || DEVICE_TEXT[device.device_type ?? ''] || 'Thiết bị' }}</span>
          <span class="flex items-center gap-2 text-outline">
            <span v-if="device.battery_level !== null" class="inline-flex items-center gap-1">
              <BatteryMedium class="h-3.5 w-3.5" />{{ device.battery_level }}%
            </span>
            <span>đồng bộ {{ when(device.last_sync_at) }}</span>
          </span>
        </div>
      </div>
      <div v-if="data.sources.length" class="space-y-1.5">
        <p class="font-label-code text-[10px] text-outline">NGUỒN GHI (KHÔNG GỘP GIỮA CÁC NGUỒN)</p>
        <div v-for="source in data.sources" :key="source.source_key + source.records"
             class="rounded-xl border border-ink/[0.06] px-3 py-2">
          <p class="text-primary">{{ sourceLabel(source) }}</p>
          <p class="text-[11px] text-outline">{{ types(source.data_types) }} · {{ source.records }} bản ghi ·
            gần nhất {{ when(source.last_measured_at) }}</p>
        </div>
      </div>
      <p v-if="!data.devices.length && !data.sources.length" class="text-outline">
        Chưa có thiết bị hay nguồn nào; danh sách xuất hiện sau lần đồng bộ đầu tiên.</p>
    </template>
  </div>
</template>
