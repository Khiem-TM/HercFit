<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { HeartPulse, Loader2 } from 'lucide-vue-next'
import { CONNECT_RESULT_TEXT, useHealthIntegration } from '@/composables/useHealthIntegration'
import { useAuth } from '@/composables/useAuth'
import type { SyncFrequency, SyncGroup } from '@/types/api'
import { createHealthApi, HealthApiError, syncAndWait } from '@/features/health-integration/api'
import HydrationCard from '@/features/health-integration/HydrationCard.vue'
import SyncStatusCard from '@/features/health-integration/SyncStatusCard.vue'
import { scopeLabel } from '@/components/knowledge/health/healthFormat'
import { stamp } from '@/components/dashboard/format'

const props = defineProps<{ result?: string | null }>()

const { connection, loading, busy, error, isConnected, needsReauth, refresh, connect, setConsent, disconnect } =
  useHealthIntegration()
const { authFetch } = useAuth()
const api = createHealthApi((url, init) => authFetch(url, init))
const share = ref(true)
const shareSensitive = ref(false)
const purge = ref(false)
const confirmDisconnect = ref(false)
const syncing = ref(false)
const saving = ref(false)
const notice = ref<{ tone: 'ok' | 'error'; text: string } | null>(null)
const timers: number[] = []
const controller = new AbortController()

const GROUPS: { id: SyncGroup; label: string; hint: string }[] = [
  { id: 'sleep', label: 'Giấc ngủ', hint: 'Thời lượng và giai đoạn ngủ mỗi đêm' },
  { id: 'rhr', label: 'Nhịp tim nghỉ', hint: 'Dùng cho điểm sẵn sàng và mức nền' },
  { id: 'hrv', label: 'HRV', hint: 'Dùng cho điểm sẵn sàng và mức nền' },
  { id: 'steps', label: 'Bước chân & vận động', hint: 'Hiển thị ở Tiến độ › Vận động' },
  { id: 'body', label: 'Cân nặng & mỡ cơ thể', hint: 'Cập nhật hồ sơ và mô hình cơ thể' },
]
const resultNotice = computed(() => (props.result ? CONNECT_RESULT_TEXT[props.result] ?? CONNECT_RESULT_TEXT.error : null))
const NUTRITION_WRITE = 'https://www.googleapis.com/auth/googlehealth.nutrition.writeonly'
const missing = computed(() => (connection.value?.missing_scopes ?? []).map(scopeLabel))
const canWriteWater = computed(() => (connection.value?.granted_scopes ?? []).includes(NUTRITION_WRITE))
const groups = computed(() => connection.value?.sync_groups ?? {})
const enabledCount = computed(() => GROUPS.filter(group => groups.value[group.id] !== false).length)
const status = computed(() => (needsReauth.value ? { text: 'Cần kết nối lại', cls: 'or' }
  : isConnected.value ? { text: 'Đã kết nối', cls: 'ok' } : { text: 'Chưa kết nối', cls: '' }))

async function syncNow(): Promise<void> {
  if (syncing.value) return
  syncing.value = true
  notice.value = null
  try {
    const result = await syncAndWait(api, { signal: controller.signal })
    if (controller.signal.aborted) return
    if (!result) {
      notice.value = { tone: 'error', text: 'Đồng bộ đang chạy lâu hơn dự kiến; số liệu sẽ cập nhật khi xong.' }
      return
    }
    connection.value = result
    notice.value = result.status !== 'ACTIVE' ? { tone: 'error', text: 'Kết nối đã hết hạn; hãy kết nối lại.' }
      : result.last_error_code ? { tone: 'error', text: 'Đã đồng bộ; một vài loại dữ liệu chưa đọc được.' }
        : { tone: 'ok', text: `Đã đồng bộ lúc ${stamp(result.last_sync_at)}` }
  } catch (err) {
    notice.value = { tone: 'error', text: err instanceof HealthApiError && err.status === 429
      ? 'Bạn vừa đồng bộ; hãy thử lại sau ít phút.' : err instanceof Error ? err.message : 'Không đồng bộ được.' }
  } finally {
    syncing.value = false
  }
}

async function saveSettings(settings: { groups?: Partial<Record<SyncGroup, boolean>>; frequency?: SyncFrequency }) {
  if (!connection.value) return
  saving.value = true
  notice.value = null
  try {
    connection.value = await api.updateSettings(settings)
  } catch (err) {
    notice.value = { tone: 'error', text: err instanceof Error ? err.message : 'Không lưu được cài đặt đồng bộ.' }
  } finally {
    saving.value = false
  }
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
onUnmounted(() => {
  timers.forEach(window.clearTimeout)
  controller.abort()
})
</script>

<template>
  <div class="connect">
    <div v-if="resultNotice" :class="resultNotice.tone === 'ok' ? 'hf-info ok' : 'hf-err'" role="status">{{ resultNotice.text }}</div>
    <div v-if="error" class="hf-err" role="alert">{{ error }}</div>

    <section class="hf-card provider">
      <div class="hf-hd">
        <div class="name">
          <span class="tile"><HeartPulse :size="22" :stroke-width="1.8" aria-hidden="true" /></span>
          <b>Google Health</b>
        </div>
        <span class="hf-pill" :class="status.cls">{{ status.text }}</span>
      </div>
      <p class="hf-mut desc">
        {{ isConnected ? 'Đang đồng bộ các loại dữ liệu bạn bật bên dưới. Buổi gym và bữa ăn lưu ở HercFit được gửi lên Google ngay sau khi lưu.'
          : needsReauth ? 'Không thể đồng bộ dữ liệu mới. Quyền truy cập có thể đã hết hạn (Google giới hạn 7 ngày ở chế độ thử nghiệm).'
            : 'Kết nối để có điểm sẵn sàng, dữ liệu giấc ngủ, nhịp tim, bước chân và cân nặng. Dùng chính Gmail bạn đăng nhập; cần app Google Health hoặc Fitbit.' }}
      </p>
      <div v-if="loading && !connection" class="loading"><Loader2 :size="16" class="hf-spin" />Đang tải trạng thái…</div>
      <p v-else-if="connection && !connection.configured" class="hf-warn">Máy chủ chưa cấu hình kết nối Google Health (thiếu OAuth client hoặc khoá mã hoá token).</p>
      <template v-else-if="connection">
        <div>
          <div v-if="connection.account_email" class="hf-kv"><b>Tài khoản</b><span class="v small">{{ connection.account_email }}</span></div>
          <div class="hf-kv"><b>{{ needsReauth ? 'Đồng bộ thành công gần nhất' : 'Đồng bộ gần nhất' }}</b>
            <span class="v small">{{ connection.last_sync_at ? stamp(needsReauth ? connection.last_success_at : connection.last_sync_at) : 'Chưa có' }}<template v-if="connection.last_error_code"> · chưa trọn</template></span></div>
          <div v-if="isConnected" class="hf-kv"><b>Loại dữ liệu đang bật</b><span class="v small">{{ enabledCount }} / {{ GROUPS.length }}</span></div>
        </div>
        <p v-if="missing.length && isConnected" class="hf-warn">Chưa cấp quyền: {{ missing.join(', ') }}. Bấm “Cấp thêm quyền” để bổ sung.</p>
        <p v-if="notice" :class="notice.tone === 'ok' ? 'hf-info' : 'hf-warn'" role="status">{{ notice.text }}</p>
        <div class="hf-acts">
          <button v-if="isConnected && !needsReauth" type="button" class="hf-btn pri" :disabled="syncing" @click="syncNow">
            <Loader2 v-if="syncing" :size="16" class="hf-spin" />{{ syncing ? 'Đang đồng bộ…' : 'Đồng bộ ngay' }}</button>
          <button v-if="!isConnected || needsReauth || missing.length" type="button" class="hf-btn" :class="{ pri: !isConnected || needsReauth }"
                  :disabled="busy" @click="connect(share)">
            {{ needsReauth ? 'Kết nối lại' : isConnected ? 'Cấp thêm quyền' : 'Kết nối Google Health' }}</button>
          <button v-if="isConnected && !confirmDisconnect" type="button" class="hf-btn on-card" :disabled="busy" @click="confirmDisconnect = true">Ngắt kết nối</button>
        </div>
        <div v-if="confirmDisconnect" class="confirm">
          <p>HercFit sẽ thu hồi quyền tại Google và xoá token đã lưu.</p>
          <label class="check"><input v-model="purge" type="checkbox" /> Xoá dữ liệu thiết bị đã đồng bộ (số đo bạn tự nhập được giữ lại)</label>
          <div class="hf-acts">
            <button type="button" class="hf-btn dng sm" :disabled="busy" @click="handleDisconnect">Xác nhận ngắt</button>
            <button type="button" class="hf-btn sm on-card" @click="confirmDisconnect = false">Huỷ</button>
          </div>
        </div>
      </template>
    </section>

    <template v-if="connection?.configured">
      <div class="hf-fsec">Dữ liệu được đồng bộ</div>
      <label v-for="group in GROUPS" :key="group.id" class="hf-srow">
        <span><b>{{ group.label }}</b><small>{{ group.hint }}</small></span>
        <span class="hf-sw"><input type="checkbox" :checked="groups[group.id] !== false" :disabled="!isConnected || saving"
                                   @change="saveSettings({ groups: { [group.id]: ($event.target as HTMLInputElement).checked } })"><i /></span>
      </label>
      <p class="hf-mut tiny">Tắt một nhóm chỉ dừng đọc nhóm đó; dữ liệu đã đồng bộ được giữ nguyên.</p>

      <div class="hf-fsec">Tần suất đồng bộ</div>
      <div class="hf-srow">
        <span><b>Tự động đồng bộ</b><small>Mỗi giờ chạy nền trên máy chủ; "Khi mở ứng dụng" đồng bộ mỗi lần bạn mở HercFit</small></span>
        <label class="hf-sr" for="c-freq">Tần suất đồng bộ</label>
        <select id="c-freq" class="hf-nsel" :value="connection.sync_frequency ?? 'hourly'" :disabled="!isConnected || saving"
                @change="saveSettings({ frequency: ($event.target as HTMLSelectElement).value as SyncFrequency })">
          <option value="hourly">Mỗi giờ</option><option value="open">Khi mở ứng dụng</option><option value="manual">Thủ công</option>
        </select>
      </div>

      <div class="hf-fsec">Chia sẻ với trợ lý</div>
      <label class="hf-srow"><span><b>Cho trợ lý dùng dữ liệu sức khoẻ tổng hợp theo ngày</b><small>Để cá nhân hoá câu trả lời. Mẫu thô và chỉ số rời
        không đưa vào bộ nhớ tri thức; có thể tắt bất cứ lúc nào.</small></span>
        <span class="hf-sw"><input v-model="share" type="checkbox" :disabled="busy" @change="isConnected && saveConsent()"><i /></span></label>
      <label v-if="isConnected" class="hf-srow"><span><b>Cho trợ lý đọc dữ liệu nhạy cảm</b><small>Đường huyết, ECG và cảnh báo nhịp tim bất thường</small></span>
        <span class="hf-sw"><input v-model="shareSensitive" type="checkbox" :disabled="busy" @change="saveConsent"><i /></span></label>
    </template>

    <div class="hf-fsec">Nguồn của chỉ số</div>
    <div class="hf-kv"><div><b>Khai báo</b><br><span>Bạn nhập qua hồ sơ hoặc trợ lý</span></div><span class="src">Hồ sơ, bữa ăn, vòng đo</span></div>
    <div class="hf-kv"><div><b>Thiết bị</b><br><span>Đồng bộ từ Google Health</span></div><span class="src">Ngủ, nhịp tim, HRV, bước chân</span></div>
    <div class="hf-kv"><div><b>Hệ thống tính</b><br><span>Tính từ hồ sơ và dữ liệu đã ghi</span></div><span class="src">Mục tiêu, điểm sẵn sàng</span></div>

    <template v-if="connection?.configured && isConnected">
      <div class="hf-fsec">Trạng thái theo loại dữ liệu</div>
      <SyncStatusCard :connection="connection" />
      <div class="hf-fsec">Nước uống</div>
      <HydrationCard :api="api" :can-write="canWriteWater && !needsReauth" />
    </template>
  </div>
</template>

<style scoped>
.connect { display: flex; flex-direction: column; }
.connect > .hf-err, .connect > .hf-info { margin: 12px 0 0; }
.provider { background: var(--hf-fill-2); padding: 20px; margin-top: 12px; }
.name { display: flex; align-items: center; gap: 12px; }
.name b { font-size: 16px; }
.tile { width: 40px; height: 40px; border-radius: 12px; background: var(--hf-card); display: inline-flex; align-items: center; justify-content: center; color: var(--hf-ink); }
.desc { margin: 0; font-size: 14px; line-height: 1.5; }
.loading { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--hf-muted); }
.small { font-size: 14px; }
.tiny { font-size: 12px; margin: 6px 0 0; }
.confirm { display: flex; flex-direction: column; gap: 10px; background: var(--hf-err-bg); color: var(--hf-err-text); border-radius: 16px; padding: 12px 14px; font-size: 13px; }
.confirm p { margin: 0; }
.check { display: flex; align-items: center; gap: 8px; }
.src { font-size: 11px !important; font-weight: 600; border-radius: 999px; padding: 3px 8px; background: var(--hf-fill); color: var(--hf-sub) !important; white-space: nowrap; justify-self: end; }
.ok { color: var(--hf-ok-text); background: var(--hf-ok-bg); }
</style>
