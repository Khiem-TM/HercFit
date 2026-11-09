<script setup lang="ts">
import { computed, onMounted, shallowRef } from 'vue'
import { Loader2 } from 'lucide-vue-next'
import type { AlertGroup, NotificationPreferences } from '@/types/api'
import { useNotifications } from '@/composables/useNotifications'
import HfLogo from '@/components/app/HfLogo.vue'

/** Tab "Thông báo AI": mọi thay đổi lưu ngay (PUT /api/v2/notifications/preferences). */
const { api, runReview } = useNotifications()
const prefs = shallowRef<NotificationPreferences | null>(null)
const busy = shallowRef(false)
const message = shallowRef<string | null>(null)
const failed = shallowRef(false)

const GROUPS: { id: AlertGroup; label: string }[] = [
  { id: 'heart', label: 'Nhịp tim' }, { id: 'oxygen', label: 'SpO2' }, { id: 'sleep', label: 'Giấc ngủ' },
  { id: 'weight', label: 'Cân nặng, BMI, vòng bụng' }, { id: 'nutrition', label: 'Dinh dưỡng' },
  { id: 'activity', label: 'Vận động' },
]
const REMINDER_TIMES = ['06:00', '07:00', '12:00', '17:30', '19:00', '20:00']
const REVIEW_TIMES = ['19:00', '20:00', '20:30', '21:00', '21:30', '22:00']
const reminderTimes = computed(() => [...new Set([...REMINDER_TIMES, prefs.value?.workout_reminder_time ?? '17:30'])].sort())
const reviewTimes = computed(() => [...new Set([...REVIEW_TIMES, prefs.value?.daily_review_time ?? '21:00'])].sort())

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
  const before = prefs.value
  prefs.value = { ...before, ...patch }
  busy.value = true
  try {
    prefs.value = await api.savePreferences({ ...before, ...patch })
    failed.value = false
    message.value = null
  } catch (error) {
    prefs.value = before
    failed.value = true
    message.value = error instanceof Error ? error.message : 'Không lưu được tuỳ chọn.'
  } finally {
    busy.value = false
  }
}

const checked = (event: Event) => (event.target as HTMLInputElement).checked
const picked = (event: Event) => (event.target as HTMLSelectElement | HTMLInputElement).value

function toggleGroup(group: AlertGroup) {
  const current = prefs.value?.alert_groups ?? []
  void save({ alert_groups: current.includes(group) ? current.filter(item => item !== group) : [...current, group] })
}

async function reviewNow() {
  busy.value = true
  try {
    await runReview()
    failed.value = false
    message.value = 'Đã tạo đánh giá hôm nay; xem ở biểu tượng chuông.'
  } catch (error) {
    failed.value = true
    message.value = error instanceof Error ? error.message : 'Chưa tạo được đánh giá hôm nay.'
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="notify">
    <div v-if="!prefs && !failed" class="loading"><Loader2 :size="16" class="hf-spin" />Đang tải…</div>
    <template v-if="prefs">
      <div class="hf-fsec">Thông báo chủ động</div>
      <label class="hf-srow"><span><b>Bật thông báo chủ động</b><small>HercFit tự kiểm tra chỉ số của bạn theo ngưỡng của Bộ Y tế, WHO và
        hội chuyên môn. Lời thông báo do trợ lý AI viết từ các con số đã tính (chỉ khi bạn cho trợ lý dùng dữ liệu thiết bị),
        không phải chẩn đoán y khoa. Tắt bất cứ lúc nào.</small></span>
        <span class="hf-sw"><input type="checkbox" :checked="prefs.enabled" :disabled="busy" @change="save({ enabled: checked($event) })"><i /></span></label>
      <div v-if="!prefs.enabled" class="hf-info">Đang tắt: các cài đặt bên dưới được lưu nhưng chưa có thông báo nào được gửi.</div>

      <div class="hf-fsec">Cảnh báo chỉ số</div>
      <label class="hf-srow"><span><b>Cảnh báo khi chỉ số vượt ngưỡng</b><small>Ngưỡng theo thể trạng và mục tiêu của bạn; mỗi cảnh báo
        ghi rõ nguồn. Cảnh báo khẩn (ví dụ SpO2 dưới 90%) luôn được gửi, kể cả khi đã đủ số thông báo trong ngày.</small></span>
        <span class="hf-sw"><input type="checkbox" :checked="prefs.health_alerts" @change="save({ health_alerts: checked($event) })"><i /></span></label>
      <div class="groups" role="group" aria-label="Nhóm chỉ số nhận cảnh báo">
        <button v-for="group in GROUPS" :key="group.id" type="button" class="hf-tog" :disabled="!prefs.health_alerts"
                :aria-pressed="prefs.alert_groups.includes(group.id)" @click="toggleGroup(group.id)">{{ group.label }}</button>
      </div>

      <div class="hf-fsec">Đánh giá cuối ngày</div>
      <label class="hf-srow"><span><b>Đánh giá chất lượng ngày</b><small>Trợ lý chấm dinh dưỡng, vận động, giấc ngủ, hồi phục và lịch tập
        của ngày, kèm gợi ý cho ngày mai. Tối đa một lần mỗi ngày.</small></span>
        <span class="hf-sw"><input type="checkbox" :checked="prefs.daily_review" @change="save({ daily_review: checked($event) })"><i /></span></label>
      <div class="hf-srow">
        <span><b>Giờ gửi đánh giá</b><small>Theo giờ địa phương ({{ prefs.timezone ?? 'Asia/Ho_Chi_Minh' }})</small></span>
        <label for="n-review" class="hf-sr">Giờ gửi đánh giá ngày</label>
        <select id="n-review" class="hf-nsel" :value="prefs.daily_review_time" :disabled="!prefs.daily_review"
                @change="save({ daily_review_time: picked($event) })">
          <option v-for="time in reviewTimes" :key="time" :value="time">{{ time }}</option>
        </select>
      </div>

      <div class="hf-fsec">Lịch tập</div>
      <label class="hf-srow"><span><b>Đề xuất điều chỉnh khi điểm sẵn sàng thấp</b><small>Trợ lý gợi ý giảm cường độ hoặc dời buổi tập. Bạn luôn là người xác nhận.</small></span>
        <span class="hf-sw"><input type="checkbox" :checked="prefs.adjust_on_low_readiness" @change="save({ adjust_on_low_readiness: checked($event) })"><i /></span></label>
      <div class="hf-srow">
        <span><b>Ngưỡng điểm sẵn sàng</b><small>Gửi đề xuất khi điểm hôm nay thấp hơn mức này</small></span>
        <label for="n-thr" class="hf-sr">Ngưỡng điểm sẵn sàng</label>
        <select id="n-thr" class="hf-nsel" :value="prefs.readiness_threshold" :disabled="!prefs.adjust_on_low_readiness"
                @change="save({ readiness_threshold: Number(picked($event)) as 50 | 60 | 70 })">
          <option :value="50">Dưới 50</option><option :value="60">Dưới 60</option><option :value="70">Dưới 70</option>
        </select>
      </div>
      <div class="hf-srow">
        <span><b>Khi lỡ một buổi tập</b><small>Cách trợ lý xử lý buổi đã qua ngày mà chưa ghi nhận</small></span>
        <label for="n-miss" class="hf-sr">Khi lỡ một buổi tập</label>
        <select id="n-miss" class="hf-nsel" :value="prefs.missed_session" @change="save({ missed_session: picked($event) as 'ask' | 'auto' | 'none' })">
          <option value="ask">Hỏi trước khi dời</option><option value="auto">Tự dời sang ngày nghỉ gần nhất</option><option value="none">Không dời</option>
        </select>
      </div>
      <label class="hf-srow"><span><b>Nhắc buổi tập</b><small>Gửi vào giờ bạn chọn trong ngày có lịch, khi buổi tập chưa được ghi nhận</small></span>
        <span class="hf-sw"><input type="checkbox" :checked="prefs.workout_reminder" @change="save({ workout_reminder: checked($event) })"><i /></span></label>
      <div class="hf-srow">
        <span><b>Giờ nhắc</b><small>Theo giờ địa phương</small></span>
        <label for="n-at" class="hf-sr">Giờ nhắc buổi tập</label>
        <select id="n-at" class="hf-nsel" :value="prefs.workout_reminder_time" :disabled="!prefs.workout_reminder"
                @change="save({ workout_reminder_time: picked($event) })">
          <option v-for="time in reminderTimes" :key="time" :value="time">{{ time }}</option>
        </select>
      </div>

      <div class="hf-fsec">Giờ yên lặng và giới hạn</div>
      <label class="hf-srow"><span><b>Giờ yên lặng</b><small>Không gửi thông báo nào (kể cả khẩn) từ {{ prefs.quiet_hours.start }} đến {{ prefs.quiet_hours.end }};
        thông báo đến sau khi hết giờ yên lặng</small></span>
        <span class="hf-sw"><input type="checkbox" :checked="prefs.quiet_hours.enabled" @change="save({ quiet_hours: { ...prefs.quiet_hours, enabled: checked($event) } })"><i /></span></label>
      <div v-if="prefs.quiet_hours.enabled" class="hf-srow times">
        <span><b>Khung giờ yên lặng</b></span>
        <span class="time-pair">
          <label for="q-start" class="hf-sr">Bắt đầu</label>
          <input id="q-start" type="time" class="hf-nsel" :value="prefs.quiet_hours.start" @change="save({ quiet_hours: { ...prefs.quiet_hours, start: picked($event) } })" />
          <span class="hf-mut">–</span>
          <label for="q-end" class="hf-sr">Kết thúc</label>
          <input id="q-end" type="time" class="hf-nsel" :value="prefs.quiet_hours.end" @change="save({ quiet_hours: { ...prefs.quiet_hours, end: picked($event) } })" />
        </span>
      </div>
      <div class="hf-srow">
        <span><b>Số thông báo tối đa mỗi ngày</b><small>Không tính cảnh báo khẩn</small></span>
        <label for="n-max" class="hf-sr">Số thông báo tối đa mỗi ngày</label>
        <select id="n-max" class="hf-nsel" :value="prefs.max_per_day" @change="save({ max_per_day: Number(picked($event)) })">
          <option v-for="count in 8" :key="count" :value="count">{{ count }}</option>
        </select>
      </div>

      <div class="hf-fsec">Xem trước thông báo</div>
      <div class="preview">
        <HfLogo :size="32" />
        <div class="preview-body">
          <div class="hf-mut tiny">Trợ lý HercFit · ví dụ cảnh báo</div>
          <div class="preview-text"><b>Nhịp tim nghỉ cao hơn bình thường.</b> Nhịp tim nghỉ 2 ngày gần nhất là 104 và 106 bpm,
            trên mức 100 bpm (bình thường ở người lớn là 60–100 bpm). Nghỉ ngơi và tránh tập nặng hôm nay.</div>
          <div class="hf-acts"><span class="hf-btn pri sm">Hỏi thêm</span><span class="hf-btn sm on-card">Đã xem</span></div>
        </div>
      </div>
      <button type="button" class="hf-btn brief" :disabled="busy || !prefs.enabled" :aria-busy="busy" @click="reviewNow">Tạo đánh giá hôm nay</button>
    </template>
    <p v-if="message" class="msg" :class="{ bad: failed }" role="status">{{ message }}</p>
  </div>
</template>

<style scoped>
.notify { display: flex; flex-direction: column; }
.loading { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--hf-muted); padding: 16px 0; }
.times { padding-top: 4px; }
.groups { display: flex; flex-wrap: wrap; gap: 8px; padding: 4px 0 8px; }
.time-pair { display: inline-flex; align-items: center; gap: 6px; }
.preview { background: var(--hf-fill-3); border-radius: 20px; padding: 16px; display: flex; gap: 12px; align-items: flex-start; }
.preview-body { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.preview-text { font-size: 14px; line-height: 1.5; }
.tiny { font-size: 12px; }
.brief { align-self: flex-start; margin-top: 16px; }
.msg { margin: 12px 0 0; font-size: 13px; color: var(--hf-ok-text); }
.msg.bad { color: var(--hf-bad); }
</style>
