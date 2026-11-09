<script setup lang="ts">
import { computed, nextTick, reactive, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { Download, Loader2, LogOut, Trash2, X } from 'lucide-vue-next'
import { AnimatePresence, motion } from 'motion-v'
import { indicatorTransition, modalTransition, presence } from '@/motion'
import type { BodyMetricRead } from '@/types/api'
import { useAuth } from '@/composables/useAuth'
import { type ThemeMode, useTheme } from '@/composables/useTheme'
import { activityChoices, goalChoices, todayInVietnam } from '@/features/onboarding/model'
import HealthIntegrationPanel from '@/components/chat/HealthIntegrationPanel.vue'
import NotificationSettingsPanel from '@/components/notifications/NotificationSettingsPanel.vue'
import BodyFigure from '@/components/dashboard/BodyFigure.vue'
import { bmiCategory, bmiOf } from '@/components/dashboard/bodyShape'
import { vn } from '@/components/dashboard/format'
import { num } from '@/components/knowledge/health/healthFormat'

type SettingsTab = 'profile' | 'integrations' | 'notifications' | 'account'

const props = defineProps<{
  open: boolean
  /** Tab hiển thị khi hộp thoại mở, ví dụ sau màn hình đồng ý của Google Health. */
  initialTab?: 'profile' | 'integrations' | 'notifications'
  integrationResult?: string | null
}>()
const emit = defineEmits<{ (e: 'close'): void }>()

const { user, latestBodyMetric, currentGoal, authFetch, updateProfile, recordBodyMetric, fetchProfileDetails,
        exportData, eraseAccount, logout } = useAuth()
const { mode: themeMode, setMode: setThemeMode } = useTheme()

const TABS: { id: SettingsTab; label: string; sub: string }[] = [
  { id: 'profile', label: 'Thông tin cá nhân', sub: 'Tên, tuổi, số đo và mục tiêu tập luyện' },
  { id: 'integrations', label: 'Kết nối dữ liệu', sub: 'Google Health và nguồn của từng chỉ số' },
  { id: 'notifications', label: 'Thông báo AI', sub: 'Cách trợ lý nhắc nhở và đề xuất điều chỉnh lịch' },
  { id: 'account', label: 'Tài khoản', sub: 'Giao diện, dữ liệu cá nhân và phiên đăng nhập' },
]
const THEME_OPTIONS: { value: ThemeMode; label: string }[] = [
  { value: 'light', label: 'Sáng' }, { value: 'dark', label: 'Tối' }, { value: 'system', label: 'Theo hệ thống' },
]
const EXPERIENCE = [{ value: 'BEGINNER', label: 'Mới bắt đầu' }, { value: 'INTERMEDIATE', label: 'Trung cấp' }, { value: 'ADVANCED', label: 'Nâng cao' }]
const PLACES = ['Phòng gym đầy đủ dụng cụ', 'Tại nhà – tạ đơn', 'Tại nhà – không dụng cụ', 'Ngoài trời']

const activeTab = ref<SettingsTab>('profile')
const current = computed(() => TABS.find(tab => tab.id === activeTab.value) ?? TABS[0])
const dialog = useTemplateRef<HTMLElement>('dialog')
const saving = ref(false)
const formError = ref<string | null>(null)
const saved = ref<string | null>(null)
const isExporting = ref(false)
const isErasing = ref(false)
const eraseEmail = ref('')
const accountMessage = ref<{ tone: 'ok' | 'error'; text: string } | null>(null)

const form = reactive({
  fullname: '', nick_name: '', age: '', sex: '' as '' | 'MALE' | 'FEMALE',
  height: '', weight: '', fat: '', muscle: '', chest: '', waist: '', hip: '',
  goal: '', activity: '', experience: '', place: '',
})
// Giá trị lúc mở hộp thoại: chỉ gửi những gì đã đổi (số đo là một lần đo mới).
let initial = { ...form }
const trainingProfile = shallowRef<Record<string, unknown> | null>(null)

function text(value: unknown, digits = 1): string {
  const parsed = num(value as number | string | null)
  return parsed == null ? '' : String(Math.round(parsed * 10 ** digits) / 10 ** digits)
}

async function loadExtras() {
  const [metrics, training] = await Promise.all([
    authFetch('/api/body-metrics?limit=100').then(r => (r.ok ? r.json() as Promise<BodyMetricRead[]> : [])).catch(() => []),
    authFetch('/api/training/profile').then(r => (r.ok ? r.json() : null)).catch(() => null),
  ])
  const sorted = [...metrics].sort((a, b) => b.recorded_at.localeCompare(a.recorded_at))
  const latest = (field: keyof BodyMetricRead) => sorted.find(metric => num(metric[field] as number | string | null) != null)?.[field]
  form.height = text(latest('height_cm'), 1)
  form.fat = text(latest('body_fat_pct'), 1)
  form.muscle = text(latest('muscle_mass_kg'), 1)
  form.chest = text(latest('chest_cm'), 1)
  form.waist = text(latest('waist_cm'), 1)
  form.hip = text(latest('hip_cm'), 1)
  trainingProfile.value = training?.profile ?? null
  form.experience = training?.configured ? String(training.profile.experience_level ?? '') : ''
  const equipment = (training?.profile?.equipment ?? []) as string[]
  form.place = PLACES.find(place => equipment.includes(place)) ?? ''
  initial = { ...form }
}

watch(() => props.open, async isOpen => {
  if (!isOpen) return
  activeTab.value = props.initialTab ?? 'profile'
  formError.value = saved.value = null
  accountMessage.value = null
  eraseEmail.value = ''
  const info = (user.value?.personal_info ?? {}) as Record<string, any>
  Object.assign(form, {
    fullname: user.value?.fullname ?? '', nick_name: user.value?.nick_name ?? '', age: user.value?.age?.toString() ?? '',
    sex: user.value?.sex ?? '', weight: text(latestBodyMetric.value?.weight_kg, 1), height: text(latestBodyMetric.value?.height_cm, 1),
    goal: currentGoal.value?.goal_types?.[0] ?? '', activity: String(info.activity?.level ?? ''),
    fat: '', muscle: '', chest: '', waist: '', hip: '', experience: '', place: '',
  })
  initial = { ...form }
  await nextTick()
  const node = dialog.value as unknown as HTMLElement & { $el?: HTMLElement }
  ;(node?.$el ?? node)?.focus?.({ preventScroll: true })
  await loadExtras()
}, { immediate: true })

const preview = computed(() => {
  const bmi = bmiOf(Number(form.height) || null, Number(form.weight) || null)
  return { bmi, label: bmi == null ? '—' : vn(bmi, 1), category: bmiCategory(bmi) }
})

const LIMITS: Record<string, [number, number, string]> = {
  height: [50, 260, 'Chiều cao cần trong khoảng 50–260 cm.'], weight: [20, 400, 'Cân nặng cần trong khoảng 20–400 kg.'],
  fat: [2, 75, 'Mỡ cơ thể cần trong khoảng 2–75%.'], muscle: [1, 200, 'Khối cơ cần trong khoảng 1–200 kg.'],
  chest: [30, 250, 'Vòng ngực cần trong khoảng 30–250 cm.'], waist: [30, 250, 'Vòng eo cần trong khoảng 30–250 cm.'],
  hip: [30, 250, 'Vòng hông cần trong khoảng 30–250 cm.'],
}

function validate(): string | null {
  if (!form.fullname.trim()) return 'Họ và tên không được để trống.'
  if (form.age && (!/^\d+$/.test(form.age) || Number(form.age) < 1 || Number(form.age) > 120)) return 'Tuổi phải là số nguyên từ 1 đến 120.'
  for (const [field, [min, max, message]] of Object.entries(LIMITS)) {
    const value = form[field as keyof typeof form]
    if (value === '' || value === initial[field as keyof typeof initial]) continue
    const parsed = Number(String(value).replace(',', '.'))
    if (!Number.isFinite(parsed) || parsed < min || parsed > max) return message
  }
  return null
}

async function save() {
  formError.value = validate()
  if (formError.value || saving.value) return
  saving.value = true
  saved.value = null
  const changed = (field: keyof typeof form) => form[field] !== initial[field]
  const value = (field: keyof typeof form) => (form[field] === '' ? null : Number(String(form[field]).replace(',', '.')))
  try {
    if (['fullname', 'nick_name', 'age', 'sex', 'activity'].some(field => changed(field as keyof typeof form))) {
      const info = (user.value?.personal_info ?? {}) as Record<string, any>
      const activity = { ...(info.activity ?? {}) }
      if (form.activity) activity.level = form.activity
      else delete activity.level
      await updateProfile({
        fullname: form.fullname.trim(), nick_name: form.nick_name.trim() || null, age: form.age ? Number(form.age) : null,
        sex: form.sex || null, ...(changed('activity') ? { personal_info: { activity } } : {}),
      })
    }
    const metricFields = { weight: 'weight_kg', height: 'height_cm', fat: 'body_fat_pct', muscle: 'muscle_mass_kg',
                           chest: 'chest_cm', waist: 'waist_cm', hip: 'hip_cm' } as const
    const metric = Object.fromEntries(Object.entries(metricFields)
      .filter(([field]) => changed(field as keyof typeof form) && form[field as keyof typeof form] !== '')
      .map(([field, column]) => [column, value(field as keyof typeof form)]))
    if (Object.keys(metric).length) await recordBodyMetric(metric)
    if (changed('goal') && form.goal) {
      const goal = currentGoal.value
      const response = goal
        ? await authFetch(`/api/goals/${goal.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                                                     body: JSON.stringify({ goal_types: [form.goal], expected_version_id: goal.version_id }) })
        : await authFetch('/api/goals/confirm', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
                                                  body: JSON.stringify({ title: goalChoices.find(choice => choice.id === form.goal)?.title ?? 'Mục tiêu',
                                                                         start_date: todayInVietnam(), goal_types: [form.goal], targets: {} }) })
      if (!response.ok) throw new Error('Không lưu được mục tiêu.')
    }
    if (changed('experience') || changed('place')) {
      const base = { ...(trainingProfile.value ?? {}) } as Record<string, any>
      if (form.experience) base.experience_level = form.experience
      const others = ((base.equipment ?? []) as string[]).filter(item => !PLACES.includes(item))
      base.equipment = form.place ? [...others, form.place] : others
      const response = await authFetch('/api/training/profile', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(base) })
      if (!response.ok) throw new Error('Không lưu được kinh nghiệm và điều kiện tập.')
    }
    await fetchProfileDetails()
    initial = { ...form }
    saved.value = 'Đã lưu hồ sơ.'
  } catch (err) {
    formError.value = err instanceof Error ? err.message : 'Lưu hồ sơ thất bại.'
  } finally {
    saving.value = false
  }
}

async function handleLogout(): Promise<void> {
  emit('close')
  await logout()
}

async function handleExport(): Promise<void> {
  isExporting.value = true
  accountMessage.value = null
  try {
    await exportData()
    accountMessage.value = { tone: 'ok', text: 'Đã tải xuống bản sao dữ liệu của bạn.' }
  } catch (err) {
    accountMessage.value = { tone: 'error', text: err instanceof Error ? err.message : 'Xuất dữ liệu thất bại.' }
  } finally {
    isExporting.value = false
  }
}

async function handleErase(): Promise<void> {
  if (eraseEmail.value.trim().toLowerCase() !== (user.value?.email || '').toLowerCase()) {
    accountMessage.value = { tone: 'error', text: 'Nhập đúng email tài khoản để xác nhận xoá vĩnh viễn.' }
    return
  }
  isErasing.value = true
  accountMessage.value = null
  try {
    await eraseAccount(eraseEmail.value.trim())
    emit('close')
  } catch (err) {
    accountMessage.value = { tone: 'error', text: err instanceof Error ? err.message : 'Xoá tài khoản thất bại.' }
  } finally {
    isErasing.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <AnimatePresence>
    <div v-if="open" class="hf hf-smodal" @keydown.esc="emit('close')">
      <motion.button type="button" class="hf-scrim scrim" aria-label="Đóng Hồ sơ và kết nối" v-bind="presence(modalTransition.scrim)"
                     @click="emit('close')" />
      <div class="center">
      <motion.div ref="dialog" class="smodal" role="dialog" aria-modal="true" aria-label="Hồ sơ và kết nối" tabindex="-1"
                  v-bind="presence(modalTransition.panel)">
        <nav class="snavcol" aria-label="Mục cài đặt">
          <h2>Hồ sơ &amp; kết nối</h2>
          <button v-for="tab in TABS" :key="tab.id" type="button" class="stab" :class="{ on: activeTab === tab.id }"
                  :aria-current="activeTab === tab.id ? 'page' : undefined" @click="activeTab = tab.id">
            <motion.span v-if="activeTab === tab.id" layout-id="settings-tab" class="stab-ind" :transition="indicatorTransition" />
            <span class="stab-label">{{ tab.label }}</span>
          </button>
        </nav>
        <div class="sbody">
          <div class="hf-hd shead">
            <div><h3>{{ current.label }}</h3><p class="hf-mut">{{ current.sub }}</p></div>
            <button type="button" class="hf-ib soft" aria-label="Đóng" @click="emit('close')"><X :size="18" aria-hidden="true" /></button>
          </div>

          <div class="sscroll">
            <!-- Thông tin cá nhân -->
            <form v-if="activeTab === 'profile'" id="profile-form" @submit.prevent="save">
              <div class="hf-fsec">Thông tin cơ bản</div>
              <div class="fgrid">
                <div class="hf-field"><label for="f-name">Họ và tên</label><input id="f-name" v-model="form.fullname" class="hf-inp" autocomplete="name" /></div>
                <div class="hf-field"><label for="f-nick">Biệt danh</label><input id="f-nick" v-model="form.nick_name" class="hf-inp" maxlength="100" /></div>
                <div class="hf-field"><label for="f-email">Email</label><input id="f-email" class="hf-inp" :value="user?.email" readonly aria-readonly="true" /></div>
                <div class="hf-field"><label for="f-age">Tuổi</label><input id="f-age" v-model="form.age" class="hf-inp" type="number" min="1" max="120" inputmode="numeric" /></div>
                <div class="hf-field"><label for="f-sex">Giới tính</label>
                  <select id="f-sex" v-model="form.sex" class="hf-inp"><option value="">Chưa khai báo</option><option value="MALE">Nam</option><option value="FEMALE">Nữ</option></select>
                </div>
              </div>

              <div class="hf-fsec">Số đo cơ thể</div>
              <div class="measure">
                <div class="fgrid">
                  <div class="hf-field"><label for="f-h">Chiều cao (cm)</label><input id="f-h" v-model="form.height" class="hf-inp" type="number" step="0.1" inputmode="decimal" /></div>
                  <div class="hf-field"><label for="f-w">Cân nặng (kg)</label><input id="f-w" v-model="form.weight" class="hf-inp" type="number" step="0.1" inputmode="decimal" /></div>
                  <div class="hf-field"><label for="f-chest">Vòng ngực (cm)</label><input id="f-chest" v-model="form.chest" class="hf-inp" type="number" step="0.1" inputmode="decimal" /></div>
                  <div class="hf-field"><label for="f-waist">Vòng eo (cm)</label><input id="f-waist" v-model="form.waist" class="hf-inp" type="number" step="0.1" inputmode="decimal" /></div>
                  <div class="hf-field"><label for="f-hip">Vòng hông (cm)</label><input id="f-hip" v-model="form.hip" class="hf-inp" type="number" step="0.1" inputmode="decimal" /></div>
                  <div class="hf-field"><label for="f-fat">Mỡ cơ thể (%)</label><input id="f-fat" v-model="form.fat" class="hf-inp" type="number" step="0.1" inputmode="decimal" /></div>
                  <div class="hf-field"><label for="f-muscle">Khối cơ (kg)</label><input id="f-muscle" v-model="form.muscle" class="hf-inp" type="number" step="0.1" inputmode="decimal" /></div>
                </div>
                <div class="figure">
                  <BodyFigure :bmi="preview.bmi ?? 22" :female="form.sex === 'FEMALE'" :label="`Xem trước mô hình theo BMI ${preview.label}`" style="height: 180px" />
                  <div class="fig-bmi">BMI {{ preview.label }}</div>
                  <div class="hf-mut tiny">{{ preview.category }}</div>
                </div>
              </div>

              <div class="hf-fsec">Mục tiêu &amp; tập luyện</div>
              <div class="fgrid">
                <div class="hf-field"><label for="f-goal">Mục tiêu</label>
                  <select id="f-goal" v-model="form.goal" class="hf-inp">
                    <option value="" :disabled="!!currentGoal">Chưa đặt</option>
                    <option v-for="choice in goalChoices" :key="choice.id" :value="choice.id">{{ choice.title }}</option>
                  </select>
                </div>
                <div class="hf-field"><label for="f-act">Mức vận động</label>
                  <select id="f-act" v-model="form.activity" class="hf-inp"><option value="">Chọn mức</option>
                    <option v-for="choice in activityChoices" :key="choice.value" :value="choice.value">{{ choice.label }}</option></select>
                </div>
                <div class="hf-field"><label for="f-exp">Kinh nghiệm tập</label>
                  <select id="f-exp" v-model="form.experience" class="hf-inp"><option value="">Chọn mức</option>
                    <option v-for="item in EXPERIENCE" :key="item.value" :value="item.value">{{ item.label }}</option></select>
                </div>
                <div class="hf-field"><label for="f-place">Điều kiện tập</label>
                  <select id="f-place" v-model="form.place" class="hf-inp"><option value="">Chọn điều kiện</option>
                    <option v-for="place in PLACES" :key="place" :value="place">{{ place }}</option></select>
                </div>
              </div>
              <p class="hf-mut note">Thay đổi chiều cao, cân nặng, mức vận động hoặc mục tiêu sẽ cập nhật mục tiêu dinh dưỡng và mô hình cơ thể.
                Mỗi lần lưu số đo là một lần đo mới, chỉ gồm những số bạn vừa đổi.</p>
            </form>

            <HealthIntegrationPanel v-else-if="activeTab === 'integrations'" :result="integrationResult" />
            <NotificationSettingsPanel v-else-if="activeTab === 'notifications'" />

            <!-- Tài khoản -->
            <div v-else class="account">
              <div class="hf-fsec">Giao diện</div>
              <div class="hf-srow">
                <span><b>Chế độ hiển thị</b><small>Sáng theo thiết kế, tối, hoặc theo cài đặt của thiết bị</small></span>
                <div class="hf-seg soft" role="radiogroup" aria-label="Giao diện">
                  <button v-for="option in THEME_OPTIONS" :key="option.value" type="button" role="radio" :aria-checked="themeMode === option.value"
                          :aria-pressed="themeMode === option.value" @click="setThemeMode(option.value)">{{ option.label }}</button>
                </div>
              </div>
              <div class="hf-fsec">Dữ liệu cá nhân</div>
              <div class="hf-srow">
                <span><b>Xuất dữ liệu cá nhân</b><small>Tải toàn bộ hồ sơ, số đo, nhật ký và kế hoạch dưới dạng JSON</small></span>
                <button type="button" class="hf-btn" :disabled="isExporting" @click="handleExport">
                  <Loader2 v-if="isExporting" :size="16" class="hf-spin" /><Download v-else :size="16" />Xuất dữ liệu</button>
              </div>
              <div class="danger">
                <b>Xoá vĩnh viễn tài khoản</b>
                <p>Xoá hội thoại, nhật ký, số đo, mục tiêu và ảnh. Không thể hoàn tác. Nhập email tài khoản để xác nhận.</p>
                <div class="erase">
                  <label for="erase-email" class="hf-sr">Email xác nhận</label>
                  <input id="erase-email" v-model="eraseEmail" class="hf-inp" type="email" autocomplete="off" :placeholder="user?.email || 'email@example.com'" />
                  <button type="button" class="hf-btn dng" :disabled="isErasing || !eraseEmail.trim()" @click="handleErase">
                    <Loader2 v-if="isErasing" :size="16" class="hf-spin" /><Trash2 v-else :size="16" />Xoá vĩnh viễn</button>
                </div>
              </div>
              <div class="hf-fsec">Phiên đăng nhập</div>
              <div class="hf-srow">
                <span><b>Đăng xuất</b><small>Thu hồi phiên làm việc hiện tại và quay về trang chủ</small></span>
                <button type="button" class="hf-btn" @click="handleLogout"><LogOut :size="16" />Đăng xuất</button>
              </div>
              <p v-if="accountMessage" class="msg" :class="accountMessage.tone" role="status">{{ accountMessage.text }}</p>
            </div>
          </div>

          <div v-if="activeTab === 'profile'" class="sfoot">
            <span v-if="formError" class="foot-msg bad" role="alert">{{ formError }}</span>
            <span v-else-if="saved" class="foot-msg ok" role="status">{{ saved }}</span>
            <button type="button" class="hf-btn" @click="emit('close')">Huỷ</button>
            <button type="submit" form="profile-form" class="hf-btn pri" :disabled="saving">
              <Loader2 v-if="saving" :size="16" class="hf-spin" />{{ saving ? 'Đang lưu…' : 'Lưu thay đổi' }}</button>
          </div>
          <div v-else-if="activeTab !== 'account'" class="sfoot between">
            <span class="hf-mut small">Thay đổi được lưu tự động</span>
            <button type="button" class="hf-btn pri" @click="emit('close')">Xong</button>
          </div>
        </div>
      </motion.div>
      </div>
    </div>
    </AnimatePresence>
  </Teleport>
</template>

<style scoped>
.hf-smodal { position: fixed; inset: 0; z-index: 60; }
.scrim { z-index: 0; }
.center { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; pointer-events: none; z-index: 1; }
.smodal {
  width: min(900px, 92vw); height: min(680px, 88vh); pointer-events: auto;
  background: var(--hf-card); border-radius: 28px; display: flex; overflow: hidden; box-shadow: 0 40px 120px rgba(0, 0, 0, .32); outline: none;
}
.snavcol { width: 232px; flex: none; background: var(--hf-fill-3); padding: 22px 12px; display: flex; flex-direction: column; gap: 4px; }
.snavcol h2 { margin: 0 12px 14px; font-size: 20px; font-weight: 700; }
.stab { position: relative; display: flex; align-items: center; gap: 10px; border: 0; background: transparent; border-radius: 12px; padding: 0 12px; min-height: 44px; font-size: 14px; font-weight: 500; color: var(--hf-sub); text-align: left; width: 100%; white-space: nowrap;
  transition: background-color var(--hf-dur-fast) var(--hf-ease-out), color var(--hf-dur-fast) var(--hf-ease-out); }
.stab:hover:not(.on) { background: var(--hf-hover); }
.stab.on { color: var(--hf-ink); font-weight: 600; }
.stab-ind { position: absolute; inset: 0; border-radius: 12px; background: var(--hf-card); box-shadow: 0 1px 3px rgba(0, 0, 0, .08); }
.stab-label { position: relative; }
.sbody { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.shead { padding: 18px 20px 6px 28px; align-items: flex-start; }
.shead h3 { margin: 0; font-size: 22px; font-weight: 700; }
.shead p { margin: 4px 0 0; font-size: 13px; }
.sscroll { flex: 1; overflow-y: auto; padding: 4px 28px 24px; }
.fgrid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 14px; }
.measure { display: grid; grid-template-columns: minmax(0, 1fr) 120px; gap: 16px; align-items: start; }
.figure { background: var(--hf-fill-3); border-radius: 18px; padding: 10px 6px; text-align: center; }
.fig-bmi { font-size: 12px; font-weight: 700; margin-top: 4px; }
.tiny { font-size: 11px; }
.note { font-size: 12px; margin: 16px 0 0; line-height: 1.5; }
.sfoot { display: flex; justify-content: flex-end; align-items: center; gap: 8px; padding: 14px 20px; border-top: 1px solid var(--hf-line-2); }
.sfoot.between { justify-content: space-between; }
.foot-msg { margin-right: auto; font-size: 13px; }
.foot-msg.bad { color: var(--hf-bad); }
.foot-msg.ok { color: var(--hf-ok-text); }
.small { font-size: 13px; }
.danger { margin-top: 16px; background: var(--hf-err-bg); color: var(--hf-err-text); border-radius: 18px; padding: 16px; display: flex; flex-direction: column; gap: 8px; }
.danger p { margin: 0; font-size: 13px; line-height: 1.5; }
.erase { display: flex; gap: 8px; flex-wrap: wrap; }
.erase .hf-inp { flex: 1; min-width: 200px; }
.msg { margin: 12px 0 0; font-size: 13px; }
.msg.ok { color: var(--hf-ok-text); }
.msg.error { color: var(--hf-bad); }
@media (max-width: 760px) {
  .smodal { width: 100%; height: 100%; border-radius: 0; flex-direction: column; }
  .snavcol { width: auto; flex-direction: row; overflow-x: auto; padding: 10px 12px; }
  .snavcol h2 { display: none; }
  .fgrid, .measure { grid-template-columns: minmax(0, 1fr); }
  .sscroll { padding: 4px 16px 20px; }
}
</style>
