<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { HeartPulse, Link2, Loader2, Unlink } from 'lucide-vue-next'
import { CONNECT_RESULT_TEXT, useHealthIntegration } from '@/composables/useHealthIntegration'
import { useAuth } from '@/composables/useAuth'
import type { HealthConnection } from '@/types/api'
import { createHealthApi } from '@/features/health-integration/api'
import HydrationCard from '@/features/health-integration/HydrationCard.vue'
import SyncStatusCard from '@/features/health-integration/SyncStatusCard.vue'
import { recordGroups, scopeLabel } from '@/components/knowledge/health/healthFormat'

const props = defineProps<{ result?: string | null }>()

const { connection, loading, busy, error, isConnected, needsReauth, refresh, connect, setConsent, disconnect } =
  useHealthIntegration()
const { authFetch } = useAuth()
const api = createHealthApi((url, init) => authFetch(url, init))
const share = ref(true)
const shareSensitive = ref(false)
const purge = ref(false)
const confirmDisconnect = ref(false)
const timers: number[] = []

const resultNotice = computed(() => (props.result ? CONNECT_RESULT_TEXT[props.result] ?? CONNECT_RESULT_TEXT.error : null))
const NUTRITION_WRITE = 'https://www.googleapis.com/auth/googlehealth.nutrition.writeonly'
const missing = computed(() => (connection.value?.missing_scopes ?? []).map(scopeLabel))
const records = computed(() => recordGroups(connection.value?.records).filter(group => group.count))
const canWriteWater = computed(() => (connection.value?.granted_scopes ?? []).includes(NUTRITION_WRITE))

function onSynced(value: HealthConnection): void {
  connection.value = value
}

function when(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' }) : '—'
}

async function handleDisconnect(): Promise<void> {
  await disconnect(purge.value)
  confirmDisconnect.value = false
  purge.value = false
}

async function saveConsent(): Promise<void> {
  await setConsent(share.value, shareSensitive.value)
  share.value = connection.value?.share_with_assistant ?? false
  shareSensitive.value = connection.value?.share_sensitive_with_assistant ?? false
}

onMounted(async () => {
  await refresh()
  share.value = connection.value?.connected ? connection.value.share_with_assistant : true
  shareSensitive.value = connection.value?.share_sensitive_with_assistant ?? false
  // Lần đồng bộ đầu bắt đầu ngay sau màn hình đồng ý; hiển thị kết quả khi nó tới.
  if (props.result === 'connected') for (const delay of [5000, 15000]) timers.push(window.setTimeout(refresh, delay))
})
onUnmounted(() => timers.forEach(window.clearTimeout))
</script>

<template>
  <div class="space-y-4">
    <div
      v-if="resultNotice"
      class="rounded-xl border px-4 py-2.5 text-xs"
      :class="resultNotice.tone === 'ok' ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200' : 'border-error/40 bg-error/10 text-error'"
    >
      {{ resultNotice.text }}
    </div>
    <div v-if="error" class="rounded-xl border border-error/40 bg-error/10 px-4 py-2.5 text-xs text-error">{{ error }}</div>

    <div class="space-y-3 rounded-2xl border border-ink/[0.08] bg-panel p-4">
      <div class="flex items-start gap-3">
        <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-ink/10 bg-ink/5">
          <HeartPulse class="h-4 w-4 text-primary" />
        </div>
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <h4 class="text-sm font-medium text-primary">Google Health</h4>
            <span
              v-if="connection?.status"
              class="rounded-full px-2 py-0.5 font-label-code text-[10px]"
              :class="needsReauth ? 'bg-amber-400/15 text-amber-300' : isConnected ? 'bg-emerald-400/15 text-emerald-300' : 'bg-ink/10 text-outline'"
            >
              {{ needsReauth ? 'CẦN KẾT NỐI LẠI' : isConnected ? 'ĐANG HOẠT ĐỘNG' : 'ĐÃ NGẮT' }}
            </span>
          </div>
          <p class="mt-0.5 text-xs text-outline">
            Google Health là nguồn dữ liệu sức khoẻ của HercFit: giấc ngủ, nhịp tim, HRV, bước chân và calo được đọc từ thiết bị;
            buổi thể thao, cân nặng và nước uống được ghi thẳng lên Google; buổi gym và bữa ăn được HercFit lưu rồi đẩy lên.
            Dùng chính Gmail bạn đăng nhập; cần app Google Health hoặc Fitbit.
          </p>
        </div>
      </div>

      <div v-if="loading && !connection" class="flex items-center gap-2 text-xs text-outline">
        <Loader2 class="h-3.5 w-3.5 animate-spin" /> Đang tải trạng thái…
      </div>

      <p v-else-if="connection && !connection.configured" class="text-xs text-amber-300">
        Máy chủ chưa cấu hình kết nối Google Health (thiếu OAuth client hoặc khoá mã hoá token).
      </p>

      <template v-else-if="connection">
        <div v-if="isConnected" class="grid gap-1.5 text-xs">
          <div class="flex justify-between gap-3"><span class="text-outline">Tài khoản</span><span class="truncate text-primary">{{ connection.account_email }}</span></div>
          <div class="flex justify-between gap-3"><span class="text-outline">Lần đồng bộ gần nhất</span>
            <span class="text-primary">{{ when(connection.last_sync_at) }}<template v-if="connection.last_error_code"> · chưa trọn</template></span></div>
          <div class="flex justify-between gap-3"><span class="text-outline">Lần thành công gần nhất</span><span class="text-primary">{{ when(connection.last_success_at) }}</span></div>
          <div v-if="records.length" class="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
            <div v-for="group in records" :key="group.label" class="rounded-xl border border-ink/[0.06] bg-ink/[0.03] px-3 py-2">
              <div class="font-label-code text-sm text-primary">{{ group.count }}</div>
              <div class="text-[11px] text-outline">{{ group.label }}</div>
            </div>
          </div>
          <p v-if="missing.length" class="mt-1 text-[11px] text-amber-300">Chưa cấp quyền: {{ missing.join(', ') }}. Bấm “Cấp thêm quyền” để bổ sung.</p>
          <p v-if="needsReauth" class="mt-1 text-[11px] text-amber-300">
            Quyền truy cập đã hết hạn (ở chế độ thử nghiệm, Google giới hạn 7 ngày). Hãy kết nối lại để tiếp tục đồng bộ.
          </p>
        </div>

        <label class="flex items-start gap-2 text-xs text-on-surface-variant">
          <input
            v-model="share"
            type="checkbox"
            class="mt-0.5 accent-ink"
            :disabled="busy"
            @change="isConnected && saveConsent()"
          />
          <span>Cho phép trợ lý AI dùng dữ liệu sức khoẻ <strong>tổng hợp theo ngày</strong> để cá nhân hoá câu trả lời.
            Mẫu thô và chỉ số sinh tồn rời không đưa vào bộ nhớ tri thức; có thể tắt bất cứ lúc nào.</span>
        </label>

        <label v-if="isConnected" class="flex items-start gap-2 text-xs text-on-surface-variant">
          <input v-model="shareSensitive" type="checkbox" class="mt-0.5 accent-ink" :disabled="busy"
            @change="saveConsent" />
          <span>Cho phép trợ lý AI đọc dữ liệu nhạy cảm: đường huyết, ECG và cảnh báo nhịp tim bất thường.</span>
        </label>

        <div class="flex flex-wrap gap-2">
          <button
            v-if="!isConnected || needsReauth || missing.length"
            type="button"
            :disabled="busy"
            class="inline-flex items-center gap-2 rounded-xl bg-ink px-4 py-2 text-xs font-semibold text-paper transition-colors hover:bg-ink/90 disabled:opacity-50"
            @click="connect(share)"
          >
            <Loader2 v-if="busy" class="h-3.5 w-3.5 animate-spin" />
            <Link2 v-else class="h-3.5 w-3.5" />
            <span>{{ needsReauth ? 'Kết nối lại' : isConnected ? 'Cấp thêm quyền' : 'Kết nối bằng Gmail đăng nhập' }}</span>
          </button>
          <button
            v-if="isConnected && !confirmDisconnect"
            type="button"
            :disabled="busy"
            class="inline-flex items-center gap-2 rounded-xl border border-error/40 px-4 py-2 text-xs font-semibold text-error transition-colors hover:bg-error/15 disabled:opacity-50"
            @click="confirmDisconnect = true"
          >
            <Unlink class="h-3.5 w-3.5" />
            <span>Ngắt kết nối</span>
          </button>
        </div>
        <p class="text-[11px] text-outline">Dữ liệu tự cập nhật khi bạn mở Tri thức. Buổi gym và bữa ăn bạn lưu ở HercFit được gửi lên Google ngay sau khi lưu.</p>

        <div v-if="confirmDisconnect" class="space-y-2 rounded-xl border border-error/25 bg-error/[0.06] p-3 text-xs">
          <p class="text-on-surface-variant">HercFit sẽ thu hồi quyền tại Google và xoá token đã lưu.</p>
          <label class="flex items-center gap-2 text-on-surface-variant">
            <input v-model="purge" type="checkbox" class="accent-ink" />
            <span>Xoá luôn dữ liệu đã đồng bộ (không thể hoàn tác)</span>
          </label>
          <div class="flex gap-2">
            <button type="button" :disabled="busy" class="rounded-xl border border-error/40 bg-error/15 px-3 py-1.5 font-semibold text-error hover:bg-error/25 disabled:opacity-50" @click="handleDisconnect">Xác nhận ngắt</button>
            <button type="button" class="rounded-xl border border-ink/15 px-3 py-1.5 text-primary hover:bg-ink/10" @click="confirmDisconnect = false">Huỷ</button>
          </div>
        </div>
      </template>
    </div>

    <template v-if="connection?.configured && isConnected">
      <SyncStatusCard :api="api" :connection="connection" @synced="onSynced" />
      <HydrationCard :api="api" :can-write="canWriteWater && !needsReauth" />
    </template>
  </div>
</template>
