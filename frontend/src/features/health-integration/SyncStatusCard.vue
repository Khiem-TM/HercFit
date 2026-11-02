<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { Activity, Loader2, RefreshCw } from 'lucide-vue-next'
import type { HealthConnection } from '@/types/api'
import { type HealthApi, HealthApiError, OWNERSHIP, syncAndWait, typeLabel } from './api'

const props = defineProps<{ api: HealthApi; connection: HealthConnection }>()
const emit = defineEmits<{ synced: [connection: HealthConnection] }>()

const syncing = ref(false)
const message = ref<{ tone: 'ok' | 'error'; text: string } | null>(null)
const expanded = ref(false)
const controller = new AbortController()
onUnmounted(() => controller.abort())

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

async function syncNow(): Promise<void> {
  if (syncing.value) return
  syncing.value = true
  message.value = null
  try {
    const result = await syncAndWait(props.api, { signal: controller.signal })
    if (controller.signal.aborted) return
    if (!result) {
      message.value = { tone: 'error', text: 'Đồng bộ đang chạy lâu hơn dự kiến; số liệu sẽ cập nhật khi xong.' }
      return
    }
    emit('synced', result)
    message.value = result.status !== 'ACTIVE'
      ? { tone: 'error', text: 'Kết nối đã hết hạn; hãy kết nối lại.' }
      : result.last_error_code
        ? { tone: 'error', text: 'Đã đồng bộ; một vài loại dữ liệu chưa đọc được.' }
        : { tone: 'ok', text: 'Đã đồng bộ với Google Health.' }
  } catch (err) {
    const text = err instanceof HealthApiError && err.status === 429
      ? 'Bạn vừa đồng bộ; hãy thử lại sau ít phút.'
      : err instanceof Error ? err.message : 'Không đồng bộ được.'
    message.value = { tone: 'error', text }
  } finally {
    syncing.value = false
  }
}
</script>

<template>
  <div class="space-y-3 rounded-2xl border border-ink/[0.08] bg-panel p-4 text-xs">
    <div class="flex items-center gap-2">
      <Activity class="h-4 w-4 text-primary" />
      <h4 class="flex-1 text-sm font-medium text-primary">Dữ liệu đồng bộ theo loại</h4>
      <button
        type="button"
        :disabled="syncing || connection.status !== 'ACTIVE'"
        class="inline-flex items-center gap-1.5 rounded-lg border border-ink/20 px-2.5 py-1 text-[11px] text-primary hover:bg-ink/10 disabled:opacity-50"
        @click="syncNow"
      >
        <Loader2 v-if="syncing" class="h-3 w-3 animate-spin" />
        <RefreshCw v-else class="h-3 w-3" />
        {{ syncing ? 'Đang đồng bộ…' : 'Đồng bộ ngay' }}
      </button>
    </div>
    <p v-if="message" :class="message.tone === 'ok' ? 'text-emerald-300' : 'text-amber-300'">{{ message.text }}</p>

    <div class="grid gap-1">
      <div v-for="row in shown" :key="row.type" class="flex items-center justify-between gap-2">
        <span class="text-outline">{{ row.label }}</span>
        <span :class="row.error ? 'text-amber-300' : 'text-primary'">{{ state(row) }}</span>
      </div>
      <p v-if="!rows.length" class="text-outline">Chưa có lần đồng bộ nào. Lần đầu đọc lại 90 ngày gần nhất.</p>
    </div>
    <button v-if="rows.length > shown.length || expanded" type="button" class="text-[11px] text-outline underline-offset-2 hover:underline" @click="expanded = !expanded">
      {{ expanded ? 'Thu gọn' : `Xem tất cả ${rows.length} loại` }}
    </button>
    <p v-if="failed" class="text-[11px] text-amber-300">{{ failed }} loại chưa đọc được ở lần gần nhất; dữ liệu cũ của chúng được giữ nguyên.</p>

    <dl class="grid gap-1.5 border-t border-ink/[0.06] pt-3">
      <div v-for="item in OWNERSHIP" :key="item.title">
        <dt class="font-medium text-primary">{{ item.title }}</dt>
        <dd class="text-outline">{{ item.detail }}</dd>
      </div>
    </dl>
  </div>
</template>
