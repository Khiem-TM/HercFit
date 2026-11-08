<script setup lang="ts">
import { onMounted, shallowRef } from 'vue'
import { Loader2 } from 'lucide-vue-next'
import type { NotificationKind, NotificationPreferences } from '@/types/api'
import { useNotifications } from '@/composables/useNotifications'

const { api, runBriefing } = useNotifications()
const prefs = shallowRef<NotificationPreferences | null>(null)
const busy = shallowRef(false)
const message = shallowRef<string | null>(null)
const failed = shallowRef(false)

const CATEGORIES: { kind: NotificationKind; label: string; hint: string }[] = [
  { kind: 'briefing', label: 'Bản tóm tắt buổi sáng', hint: 'Độ sẵn sàng tập, giấc ngủ đêm qua và gợi ý hôm nay.' },
  { kind: 'insight', label: 'Nhận xét trong tuần', hint: 'Tải tập tăng nhanh, nợ ngủ (tối đa một lần mỗi tuần).' },
  { kind: 'praise', label: 'Lời khen', hint: 'Khi HRV tăng hoặc nhịp tim nghỉ giảm rõ rệt.' },
  { kind: 'data_quality', label: 'Nhắc dữ liệu', hint: 'Khi thiếu dữ liệu đêm qua (tối đa một lần mỗi tuần).' },
]

async function load() {
  try {
    prefs.value = await api.preferences()
  } catch (error) {
    failed.value = true
    message.value = error instanceof Error ? error.message : 'Không đọc được tuỳ chọn.'
  }
}

async function save(patch: Partial<NotificationPreferences>) {
  if (!prefs.value) return
  busy.value = true
  try {
    prefs.value = await api.savePreferences({ ...prefs.value, ...patch })
    failed.value = false
    message.value = 'Đã lưu.'
  } catch (error) {
    failed.value = true
    message.value = error instanceof Error ? error.message : 'Không lưu được tuỳ chọn.'
  } finally {
    busy.value = false
  }
}

function toggle(kind: NotificationKind, on: boolean) {
  const current = prefs.value?.categories ?? []
  void save({ categories: on ? [...new Set([...current, kind])] : current.filter(item => item !== kind) })
}

async function briefNow() {
  busy.value = true
  try {
    await runBriefing()
    failed.value = false
    message.value = 'Đã tạo bản tóm tắt hôm nay; xem ở biểu tượng chuông.'
  } catch (error) {
    failed.value = true
    message.value = error instanceof Error ? error.message : 'Chưa tạo được bản tóm tắt.'
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-5">
    <div v-if="!prefs && !failed" class="flex items-center gap-2 text-xs text-outline"><Loader2 class="h-4 w-4 animate-spin" />Đang tải…</div>
    <template v-if="prefs">
      <div class="rounded-2xl border border-ink/[0.08] bg-panel p-4 space-y-3">
        <label class="flex items-start gap-2 text-xs text-on-surface-variant">
          <input type="checkbox" class="mt-0.5 accent-ink" :checked="prefs.enabled" :disabled="busy" @change="save({ enabled: ($event.target as HTMLInputElement).checked })" />
          <span><strong class="text-primary">Bật thông báo chủ động</strong><br />HercFit tự soạn bản tóm tắt từ dữ liệu thiết bị của bạn (không dùng AI để viết, không gửi ra ngoài ứng dụng).
            Đây là đánh giá độ sẵn sàng tập luyện, không phải chẩn đoán y khoa. Tắt bất cứ lúc nào.</span>
        </label>
        <div class="flex flex-wrap items-end gap-4 pl-5 text-xs" :class="{ 'opacity-50': !prefs.enabled }">
          <label class="flex flex-col gap-1 text-outline">Giờ tóm tắt buổi sáng
            <input type="time" class="rounded-lg border border-ink/[0.12] bg-transparent px-2 py-1 text-primary" :value="prefs.briefing_time" :disabled="busy || !prefs.enabled"
                   @change="save({ briefing_time: ($event.target as HTMLInputElement).value })" /></label>
          <label class="flex flex-col gap-1 text-outline">Giờ yên lặng từ
            <input type="time" class="rounded-lg border border-ink/[0.12] bg-transparent px-2 py-1 text-primary" :value="prefs.quiet_hours.start" :disabled="busy || !prefs.enabled"
                   @change="save({ quiet_hours: { ...prefs.quiet_hours, start: ($event.target as HTMLInputElement).value } })" /></label>
          <label class="flex flex-col gap-1 text-outline">đến
            <input type="time" class="rounded-lg border border-ink/[0.12] bg-transparent px-2 py-1 text-primary" :value="prefs.quiet_hours.end" :disabled="busy || !prefs.enabled"
                   @change="save({ quiet_hours: { ...prefs.quiet_hours, end: ($event.target as HTMLInputElement).value } })" /></label>
        </div>
      </div>
      <div class="rounded-2xl border border-ink/[0.08] bg-panel p-4 space-y-2" :class="{ 'opacity-50': !prefs.enabled }">
        <p class="font-label-telemetry text-[10px] text-outline">LOẠI THÔNG BÁO · TỐI ĐA {{ prefs.max_per_day }} MỖI NGÀY · {{ prefs.timezone }}</p>
        <label v-for="item in CATEGORIES" :key="item.kind" class="flex items-start gap-2 text-xs text-on-surface-variant">
          <input type="checkbox" class="mt-0.5 accent-ink" :checked="prefs.categories.includes(item.kind)" :disabled="busy || !prefs.enabled"
                 @change="toggle(item.kind, ($event.target as HTMLInputElement).checked)" />
          <span><span class="text-primary">{{ item.label }}</span> · {{ item.hint }}</span>
        </label>
      </div>
      <button type="button" class="rounded-full border border-ink/[0.12] px-4 py-2 text-xs text-primary hover:bg-ink/[0.05] disabled:opacity-50"
              :disabled="busy || !prefs.enabled" @click="briefNow">Tạo tóm tắt hôm nay</button>
    </template>
    <p v-if="message" class="text-xs" :class="failed ? 'text-error' : 'text-emerald-300'">{{ message }}</p>
  </div>
</template>
