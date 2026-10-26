<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import {
  Activity,
  Check,
  Download,
  Loader2,
  LogOut,
  Settings,
  Trash2,
  User as UserIcon,
  X,
} from 'lucide-vue-next'
import { useAuth } from '@/composables/useAuth'

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const {
  user,
  latestBodyMetric,
  currentGoal,
  updateProfile,
  recordBodyMetric,
  exportData,
  eraseAccount,
  logout,
} = useAuth()

const isExporting = ref(false)
const isErasing = ref(false)
const eraseEmail = ref('')

const activeTab = ref<'profile' | 'metrics' | 'settings'>('profile')
const isSavingProfile = ref(false)
const isSavingMetric = ref(false)
const feedbackMessage = ref<string | null>(null)
const errorMessage = ref<string | null>(null)

const profileForm = reactive({
  fullname: '',
  nick_name: '',
  age: '' as string | number,
  sex: '' as '' | 'MALE' | 'FEMALE',
})

const metricForm = reactive({
  weight_kg: '' as string | number,
  height_cm: '' as string | number,
  body_fat_pct: '' as string | number,
  muscle_mass_kg: '' as string | number,
})

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      feedbackMessage.value = null
      errorMessage.value = null
      profileForm.fullname = user.value?.fullname || ''
      profileForm.nick_name = user.value?.nick_name || ''
      profileForm.age = user.value?.age ?? ''
      profileForm.sex = user.value?.sex ?? ''
      eraseEmail.value = ''

      metricForm.weight_kg = latestBodyMetric.value?.weight_kg ?? ''
      metricForm.height_cm = latestBodyMetric.value?.height_cm ?? ''
      metricForm.body_fat_pct = latestBodyMetric.value?.body_fat_pct ?? ''
      metricForm.muscle_mass_kg = latestBodyMetric.value?.muscle_mass_kg ?? ''
    }
  },
  { immediate: true },
)

async function handleSaveProfile(): Promise<void> {
  if (!profileForm.fullname.trim()) {
    errorMessage.value = 'Họ và tên không được để trống.'
    return
  }
  isSavingProfile.value = true
  feedbackMessage.value = null
  errorMessage.value = null
  try {
    const parsedAge =
      profileForm.age !== '' && profileForm.age !== null
        ? Number(profileForm.age)
        : null
    await updateProfile({
      fullname: profileForm.fullname.trim(),
      nick_name: profileForm.nick_name.trim() || null,
      age: Number.isFinite(parsedAge) ? parsedAge : null,
      sex: profileForm.sex || null,
    })
    feedbackMessage.value = 'Đã lưu thông tin hồ sơ cá nhân.'
  } catch (err) {
    errorMessage.value =
      err instanceof Error ? err.message : 'Cập nhật hồ sơ thất bại.'
  } finally {
    isSavingProfile.value = false
  }
}

async function handleSaveMetric(): Promise<void> {
  const weight = Number(metricForm.weight_kg)
  if (!Number.isFinite(weight) || weight < 20 || weight > 400) {
    errorMessage.value = 'Cân nặng cần nằm trong khoảng 20–400 kg.'
    return
  }
  const heightValue = metricForm.height_cm !== '' ? Number(metricForm.height_cm) : null
  if (heightValue !== null && (!Number.isFinite(heightValue) || heightValue < 50 || heightValue > 260)) {
    errorMessage.value = 'Chiều cao cần nằm trong khoảng 50–260 cm.'
    return
  }
  isSavingMetric.value = true
  feedbackMessage.value = null
  errorMessage.value = null
  try {
    const height =
      metricForm.height_cm !== '' ? Number(metricForm.height_cm) : null
    const bodyFat =
      metricForm.body_fat_pct !== '' ? Number(metricForm.body_fat_pct) : null
    const muscle =
      metricForm.muscle_mass_kg !== '' ? Number(metricForm.muscle_mass_kg) : null

    await recordBodyMetric({
      weight_kg: weight,
      height_cm: height && Number.isFinite(height) ? height : null,
      body_fat_pct: bodyFat && Number.isFinite(bodyFat) ? bodyFat : null,
      muscle_mass_kg: muscle && Number.isFinite(muscle) ? muscle : null,
    })
    feedbackMessage.value = 'Đã ghi nhận bản ghi chỉ số cơ thể mới.'
  } catch (err) {
    errorMessage.value =
      err instanceof Error ? err.message : 'Lưu chỉ số cơ thể thất bại.'
  } finally {
    isSavingMetric.value = false
  }
}

async function handleLogout(): Promise<void> {
  emit('close')
  await logout()
}

async function handleExport(): Promise<void> {
  isExporting.value = true
  errorMessage.value = null
  try {
    await exportData()
    feedbackMessage.value = 'Đã tải xuống bản sao dữ liệu của bạn.'
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Xuất dữ liệu thất bại.'
  } finally {
    isExporting.value = false
  }
}

async function handleErase(): Promise<void> {
  if (eraseEmail.value.trim().toLowerCase() !== (user.value?.email || '').toLowerCase()) {
    errorMessage.value = 'Nhập đúng email tài khoản để xác nhận xoá vĩnh viễn.'
    return
  }
  isErasing.value = true
  errorMessage.value = null
  try {
    await eraseAccount(eraseEmail.value.trim())
    emit('close')
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Xoá tài khoản thất bại.'
  } finally {
    isErasing.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-md"
      @click.self="emit('close')"
    >
      <div
        class="relative flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden rounded-3xl border border-white/15 bg-[#121212] text-primary shadow-[0_32px_90px_rgba(0,0,0,0.85)]"
      >
        <!-- Modal Header -->
        <div
          class="flex items-center justify-between border-b border-white/[0.08] px-6 py-4"
        >
          <div class="flex items-center gap-3">
            <div
              class="h-10 w-10 overflow-hidden rounded-full border border-white/20 bg-[#1c1b1b]"
            >
              <img
                v-if="user?.avatar_url"
                :src="user.avatar_url"
                :alt="user.fullname"
                class="h-full w-full object-cover"
                referrerpolicy="no-referrer"
              />
              <div
                v-else
                class="flex h-full w-full items-center justify-center font-label-code text-xs font-bold"
              >
                {{ (user?.fullname || 'HF').slice(0, 2).toUpperCase() }}
              </div>
            </div>
            <div>
              <h2 class="text-base font-semibold text-primary">
                {{ user?.fullname || 'Hồ sơ người dùng' }}
              </h2>
              <p class="font-label-telemetry text-xs text-outline">
                {{ user?.email }}
              </p>
            </div>
          </div>

          <button
            type="button"
            class="flex h-8 w-8 items-center justify-center rounded-full text-outline transition-colors hover:bg-white/10 hover:text-primary"
            @click="emit('close')"
          >
            <X class="h-4 w-4" />
          </button>
        </div>

        <!-- Tabs Navigation -->
        <div class="flex border-b border-white/[0.08] bg-[#0e0e0e] px-6">
          <button
            type="button"
            class="flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-medium transition-colors"
            :class="
              activeTab === 'profile'
                ? 'border-white text-primary'
                : 'border-transparent text-outline hover:text-on-surface-variant'
            "
            @click="activeTab = 'profile'"
          >
            <UserIcon class="h-3.5 w-3.5" />
            <span>Hồ sơ cá nhân</span>
          </button>

          <button
            type="button"
            class="flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-medium transition-colors"
            :class="
              activeTab === 'metrics'
                ? 'border-white text-primary'
                : 'border-transparent text-outline hover:text-on-surface-variant'
            "
            @click="activeTab = 'metrics'"
          >
            <Activity class="h-3.5 w-3.5" />
            <span>Chỉ số &amp; Mục tiêu</span>
          </button>

          <button
            type="button"
            class="flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-medium transition-colors"
            :class="
              activeTab === 'settings'
                ? 'border-white text-primary'
                : 'border-transparent text-outline hover:text-on-surface-variant'
            "
            @click="activeTab = 'settings'"
          >
            <Settings class="h-3.5 w-3.5" />
            <span>Cài đặt &amp; Phiên</span>
          </button>
        </div>

        <!-- Body Content -->
        <div class="flex-1 overflow-y-auto p-6">
          <!-- Status Alerts -->
          <div
            v-if="feedbackMessage"
            class="mb-4 flex items-center gap-2 rounded-xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-2.5 text-xs text-emerald-200"
          >
            <Check class="h-4 w-4 shrink-0" />
            <span>{{ feedbackMessage }}</span>
          </div>

          <div
            v-if="errorMessage"
            class="mb-4 rounded-xl border border-error/40 bg-error/10 px-4 py-2.5 text-xs text-error"
          >
            {{ errorMessage }}
          </div>

          <!-- TAB 1: Profile -->
          <form
            v-if="activeTab === 'profile'"
            class="space-y-4"
            @submit.prevent="handleSaveProfile"
          >
            <div>
              <label class="mb-1.5 block font-label-telemetry text-[11px] uppercase tracking-wider text-outline">
                Họ và tên
              </label>
              <input
                v-model="profileForm.fullname"
                type="text"
                required
                class="w-full rounded-xl border border-white/10 bg-[#181818] px-3.5 py-2.5 text-sm text-primary focus:border-white/30 focus:outline-none"
                placeholder="Nguyễn Văn A"
              />
            </div>

            <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label class="mb-1.5 block font-label-telemetry text-[11px] uppercase tracking-wider text-outline">
                  Biệt danh (Nickname)
                </label>
                <input
                  v-model="profileForm.nick_name"
                  type="text"
                  class="w-full rounded-xl border border-white/10 bg-[#181818] px-3.5 py-2.5 text-sm text-primary focus:border-white/30 focus:outline-none"
                  placeholder="Tên gọi trong đoạn chat"
                />
              </div>

              <div>
                <label class="mb-1.5 block font-label-telemetry text-[11px] uppercase tracking-wider text-outline">
                  Tuổi
                </label>
                <input
                  v-model="profileForm.age"
                  type="number"
                  min="1"
                  max="120"
                  class="w-full rounded-xl border border-white/10 bg-[#181818] px-3.5 py-2.5 text-sm text-primary focus:border-white/30 focus:outline-none"
                  placeholder="25"
                />
              </div>

              <div>
                <label for="profile-sex" class="mb-1.5 block font-label-telemetry text-[11px] uppercase tracking-wider text-outline">
                  Giới tính sinh học
                </label>
                <select
                  id="profile-sex"
                  v-model="profileForm.sex"
                  class="w-full rounded-xl border border-white/10 bg-[#181818] px-3.5 py-2.5 text-sm text-primary focus:border-white/30 focus:outline-none"
                >
                  <option value="">Không cung cấp</option>
                  <option value="MALE">Nam</option>
                  <option value="FEMALE">Nữ</option>
                </select>
                <p class="mt-1 text-[11px] text-outline">Chỉ dùng để tính năng lượng nền (BMR).</p>
              </div>
            </div>

            <div class="flex justify-end pt-2">
              <button
                type="submit"
                :disabled="isSavingProfile"
                class="inline-flex items-center gap-2 rounded-xl bg-white px-5 py-2.5 text-xs font-semibold text-[#0e0e0e] transition-transform hover:scale-[1.02] disabled:opacity-50"
              >
                <Loader2 v-if="isSavingProfile" class="h-3.5 w-3.5 animate-spin" />
                <span>Lưu hồ sơ</span>
              </button>
            </div>
          </form>

          <!-- TAB 2: Body Metrics & Goal -->
          <div v-else-if="activeTab === 'metrics'" class="space-y-6">
            <form class="space-y-4" @submit.prevent="handleSaveMetric">
              <div class="grid grid-cols-2 gap-4">
                <div>
                  <label class="mb-1.5 block font-label-telemetry text-[11px] uppercase tracking-wider text-outline">
                    Cân nặng (kg) *
                  </label>
                  <input
                    v-model="metricForm.weight_kg"
                    type="number"
                    step="0.1"
                    min="20"
                    max="300"
                    required
                    class="w-full rounded-xl border border-white/10 bg-[#181818] px-3.5 py-2.5 text-sm text-primary focus:border-white/30 focus:outline-none"
                    placeholder="68.5"
                  />
                </div>

                <div>
                  <label class="mb-1.5 block font-label-telemetry text-[11px] uppercase tracking-wider text-outline">
                    Chiều cao (cm)
                  </label>
                  <input
                    v-model="metricForm.height_cm"
                    type="number"
                    step="0.1"
                    min="80"
                    max="250"
                    class="w-full rounded-xl border border-white/10 bg-[#181818] px-3.5 py-2.5 text-sm text-primary focus:border-white/30 focus:outline-none"
                    placeholder="172"
                  />
                </div>

                <div>
                  <label class="mb-1.5 block font-label-telemetry text-[11px] uppercase tracking-wider text-outline">
                    Tỷ lệ mỡ Body Fat (%)
                  </label>
                  <input
                    v-model="metricForm.body_fat_pct"
                    type="number"
                    step="0.1"
                    min="2"
                    max="70"
                    class="w-full rounded-xl border border-white/10 bg-[#181818] px-3.5 py-2.5 text-sm text-primary focus:border-white/30 focus:outline-none"
                    placeholder="16.5"
                  />
                </div>

                <div>
                  <label class="mb-1.5 block font-label-telemetry text-[11px] uppercase tracking-wider text-outline">
                    Khối lượng cơ (kg)
                  </label>
                  <input
                    v-model="metricForm.muscle_mass_kg"
                    type="number"
                    step="0.1"
                    min="10"
                    max="180"
                    class="w-full rounded-xl border border-white/10 bg-[#181818] px-3.5 py-2.5 text-sm text-primary focus:border-white/30 focus:outline-none"
                    placeholder="32.0"
                  />
                </div>
              </div>

              <div class="flex justify-end">
                <button
                  type="submit"
                  :disabled="isSavingMetric"
                  class="inline-flex items-center gap-2 rounded-xl bg-white px-5 py-2.5 text-xs font-semibold text-[#0e0e0e] transition-transform hover:scale-[1.02] disabled:opacity-50"
                >
                  <Loader2 v-if="isSavingMetric" class="h-3.5 w-3.5 animate-spin" />
                  <span>Ghi nhận chỉ số mới</span>
                </button>
              </div>
            </form>

            <!-- Active Goal Summary -->
            <div class="rounded-2xl border border-white/[0.08] bg-[#161616] p-4">
              <p class="font-label-telemetry text-[10px] uppercase tracking-[0.18em] text-outline">
                MỤC TIÊU HIỆN TẠI
              </p>
              <div v-if="currentGoal" class="mt-2">
                <h4 class="text-sm font-semibold text-primary">
                  {{ currentGoal.title }}
                </h4>
                <p v-if="currentGoal.description" class="mt-1 text-xs text-on-surface-variant">
                  {{ currentGoal.description }}
                </p>
                <p class="mt-2 font-label-code text-[11px] text-outline">
                  Bắt đầu: {{ currentGoal.start_date }}
                  <span v-if="currentGoal.target_date">
                    → Đích: {{ currentGoal.target_date }}
                  </span>
                </p>
              </div>
              <p v-else class="mt-2 text-xs text-outline">
                Chưa có mục tiêu đang hoạt động. Bạn có thể yêu cầu AI Agent thiết lập mục tiêu trực tiếp trong khung chat!
              </p>
            </div>
          </div>

          <!-- TAB 3: Settings & Session -->
          <div v-else class="space-y-5">
            <div class="rounded-2xl border border-white/[0.08] bg-[#161616] p-4 space-y-2">
              <div class="flex items-center justify-between text-xs">
                <span class="text-outline">Trạng thái xác thực Google OAuth</span>
                <span class="font-label-code text-emerald-400">ĐÃ ĐỒNG BỘ</span>
              </div>
              <div class="flex items-center justify-between text-xs">
                <span class="text-outline">Mô hình điều phối Agent</span>
                <span class="font-label-code text-primary">DeepSeek-V4-Flash // LangGraph</span>
              </div>
              <div class="flex items-center justify-between text-xs">
                <span class="text-outline">Giao diện</span>
                <span class="font-label-code text-primary">Olympus Kinetic Obsidian</span>
              </div>
            </div>

            <div class="space-y-3 rounded-2xl border border-white/[0.08] bg-[#161616] p-4">
              <div class="flex items-center justify-between gap-3">
                <div>
                  <h4 class="text-sm font-medium text-primary">Xuất dữ liệu cá nhân</h4>
                  <p class="mt-0.5 text-xs text-outline">Tải toàn bộ hồ sơ, số đo, nhật ký và kế hoạch dưới dạng JSON.</p>
                </div>
                <button
                  type="button"
                  :disabled="isExporting"
                  class="inline-flex shrink-0 items-center gap-2 rounded-xl border border-white/20 px-4 py-2 text-xs font-semibold text-primary transition-colors hover:bg-white/10 disabled:opacity-50"
                  @click="handleExport"
                >
                  <Loader2 v-if="isExporting" class="h-3.5 w-3.5 animate-spin" />
                  <Download v-else class="h-3.5 w-3.5" />
                  <span>Xuất dữ liệu</span>
                </button>
              </div>
            </div>

            <div class="space-y-3 rounded-2xl border border-error/25 bg-error/[0.06] p-4">
              <div>
                <h4 class="text-sm font-medium text-primary">Xoá vĩnh viễn tài khoản</h4>
                <p class="mt-0.5 text-xs text-outline">
                  Xoá hội thoại, nhật ký, số đo, mục tiêu và ảnh. Không thể hoàn tác. Nhập email tài khoản để xác nhận.
                </p>
              </div>
              <div class="flex flex-col gap-2 sm:flex-row">
                <label for="erase-email" class="sr-only">Email xác nhận</label>
                <input
                  id="erase-email"
                  v-model="eraseEmail"
                  type="email"
                  autocomplete="off"
                  :placeholder="user?.email || 'email@example.com'"
                  class="min-w-0 flex-1 rounded-xl border border-white/10 bg-[#181818] px-3.5 py-2 text-sm text-primary focus:border-white/30 focus:outline-none"
                />
                <button
                  type="button"
                  :disabled="isErasing || !eraseEmail.trim()"
                  class="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl border border-error/40 bg-error/15 px-4 py-2 text-xs font-semibold text-error transition-colors hover:bg-error/25 disabled:opacity-50"
                  @click="handleErase"
                >
                  <Loader2 v-if="isErasing" class="h-3.5 w-3.5 animate-spin" />
                  <Trash2 v-else class="h-3.5 w-3.5" />
                  <span>Xoá vĩnh viễn</span>
                </button>
              </div>
            </div>

            <div class="flex items-center justify-between rounded-2xl border border-error/25 bg-error/[0.06] p-4">
              <div>
                <h4 class="text-sm font-medium text-primary">Đăng xuất tài khoản</h4>
                <p class="mt-0.5 text-xs text-outline">
                  Thu hồi phiên làm việc hiện tại và quay về trang chủ.
                </p>
              </div>

              <button
                type="button"
                class="inline-flex items-center gap-2 rounded-xl border border-error/40 bg-error/15 px-4 py-2 text-xs font-semibold text-error transition-colors hover:bg-error/25"
                @click="handleLogout"
              >
                <LogOut class="h-3.5 w-3.5" />
                <span>Đăng xuất</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

