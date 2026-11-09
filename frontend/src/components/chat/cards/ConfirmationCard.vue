<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { Activity, CalendarDays, Clock, Dumbbell, GlassWater, Loader2, Ruler, ShieldAlert, Target, Trash2, UserRound, UtensilsCrossed } from 'lucide-vue-next'
import type { PendingAction } from '@/types/api'
import CatalogCardBody from './CatalogCardBody.vue'
import FieldsCardBody from './FieldsCardBody.vue'
import MealCardBody from './MealCardBody.vue'
import PhotoAttachment from './PhotoAttachment.vue'
import PlanCardBody from './PlanCardBody.vue'
import SportCardBody from './SportCardBody.vue'
import TrainingCardBody from './TrainingCardBody.vue'
import { cardKind, catalogTitle, DISCIPLINE, fmt, TOOL_TITLES, when } from '@/features/chat/confirmation'

export interface ConfirmExtras {
  /** Ảnh của người dùng cho một bữa ăn/buổi tập, tải lên Cloudinary sau khi bản ghi được lưu. */
  photo?: File | null
  /** Ảnh từ tra cứu cho thực phẩm/bài tập tuỳ chỉnh, nhập lên Cloudinary sau khi lưu. */
  imageSource?: string | null
  /** Lịch tập người dùng đã sửa trên thẻ; server kiểm tra lại trước khi lưu. */
  payload?: Record<string, any> | null
}

const props = defineProps<{ action: PendingAction; busy: boolean }>()
const emit = defineEmits<{ confirm: [decision: 'approve' | 'reject', extras: ConfirmExtras] }>()

const display = computed(() => (props.action.display || null) as Record<string, any> | null)
const kind = computed(() => cardKind(props.action.tool, display.value))
const photo = shallowRef<File | null>(null)
const imageSource = shallowRef<string | null>(null)
const edited = shallowRef<Record<string, any> | null>(null)

// Hành động (hoặc bản sửa đổi) mới bắt đầu với lựa chọn mới; thẻ tra cứu chọn sẵn ảnh đầu tiên.
watch(() => `${props.action.action_id}:${props.action.revision}`, () => {
  photo.value = null
  edited.value = null
  imageSource.value = kind.value === 'catalog' ? (display.value?.image_candidates?.[0]?.url ?? null) : null
}, { immediate: true })

const title = computed(() => {
  const value = display.value
  if (kind.value === 'meal' || kind.value === 'training' || kind.value === 'plan') return value?.name || TOOL_TITLES[props.action.tool]
  if (kind.value === 'catalog') return catalogTitle(props.action.tool, value)
  if (kind.value === 'sport') return value?.data_point?.exercise?.displayName || TOOL_TITLES[props.action.tool]
  return TOOL_TITLES[props.action.tool] || props.action.tool
})
const subtitle = computed(() => {
  const value = display.value || {}
  if (kind.value === 'meal') return `${when(value.consumed_at, value.timezone)} · ${(value.items || []).length} món`
  if (kind.value === 'training') return `${when(value.started_at, value.timezone)} · ${DISCIPLINE[value.discipline] || ''}${value.session_rpe ? ` · RPE buổi ${fmt(value.session_rpe, 1)}` : ''}`
  if (kind.value === 'plan') return edited.value ? 'Đã sửa trên thẻ · lưu bản đã sửa' : 'Bấm “Sửa lịch” để chỉnh trước khi lưu'
  if (kind.value === 'sport') return 'Ghi lên Google Health'
  if (kind.value === 'catalog') return value.resolution === 'reuse' ? 'Không tạo bản ghi mới; lưu liên kết nguồn nghiên cứu' : 'Bản ghi CUSTOM chỉ bạn nhìn thấy'
  return ''
})
// Thẻ trường dữ liệu được đặt tên theo thứ nó thay đổi: xoá, số đo, mục tiêu, hồ sơ, nhật ký, kế hoạch.
function fieldsIcon(tool: string) {
  if (tool.startsWith('delete_')) return Trash2
  if (tool.endsWith('_water')) return GlassWater
  if (tool.endsWith('_sport_session')) return Activity
  if (tool.endsWith('_metrics')) return Ruler
  if (tool.includes('goal')) return Target
  if (tool.includes('profile') || tool === 'merge_personal_info' || tool === 'onboard') return UserRound
  if (tool.endsWith('_meals')) return UtensilsCrossed
  if (tool.endsWith('_trainings')) return Dumbbell
  if (tool.includes('plan')) return CalendarDays
  return ShieldAlert
}
const icon = computed(() => ({ meal: UtensilsCrossed, training: Dumbbell, plan: CalendarDays, catalog: kind.value === 'catalog' && display.value?.domain === 'exercises' ? Dumbbell : UtensilsCrossed, sport: Activity, fields: fieldsIcon(props.action.tool) })[kind.value])
const expires = computed(() => new Intl.DateTimeFormat('vi-VN', { hour: '2-digit', minute: '2-digit' }).format(new Date(props.action.expires_at)))
const photoLabel = computed(() => kind.value === 'meal' ? 'Ảnh bữa ăn của bạn' : 'Ảnh buổi tập của bạn')
const destructive = computed(() => props.action.tool.startsWith('delete_'))
const confirmLabel = computed(() => (props.busy ? 'Đang lưu…' : destructive.value ? 'Xác nhận xoá'
  : edited.value ? 'Lưu bản đã sửa' : photo.value || imageSource.value ? 'Xác nhận & lưu ảnh' : 'Xác nhận lưu'))

function decide(decision: 'approve' | 'reject') {
  emit('confirm', decision, decision === 'approve' ? { photo: photo.value, imageSource: imageSource.value, payload: edited.value } : {})
}
</script>

<template>
  <article class="hf cf" :aria-label="`Xác nhận: ${title}`" :data-card="kind" :aria-busy="busy">
    <header class="cfh">
      <span class="cfic" :class="{ danger: destructive, sport: kind === 'sport' }">
        <component :is="icon" :size="20" :stroke-width="1.8" aria-hidden="true" />
      </span>
      <div class="cft"><b>{{ title }}</b><span v-if="subtitle">{{ subtitle }}</span></div>
      <div class="cfm">
        <span class="rev hf-mono" :class="{ ed: edited }">Bản {{ action.revision }}{{ edited ? ' · đã sửa' : '' }}</span>
        <span class="exp"><Clock :size="12" aria-hidden="true" />Hết hạn {{ expires }}</span>
      </div>
    </header>

    <div class="cfb">
      <MealCardBody v-if="kind === 'meal'" :meal="display!" />
      <TrainingCardBody v-else-if="kind === 'training'" :training="display!" />
      <PlanCardBody v-else-if="kind === 'plan'" :plan="display!" :payload="action.payload || {}" :disabled="busy" @change="edited = $event" />
      <CatalogCardBody v-else-if="kind === 'catalog'" v-model="imageSource" :candidate="display!" :disabled="busy" />
      <SportCardBody v-else-if="kind === 'sport'" :preview="display!" :timezone="(action.payload?.timezone as string | undefined)" />
      <FieldsCardBody v-else :tool="action.tool" :payload="action.payload || {}" />

      <div v-if="kind === 'meal' || kind === 'training'" class="photo-wrap">
        <PhotoAttachment v-model="photo" :label="photoLabel" :disabled="busy" />
      </div>
    </div>

    <footer class="cff">
      <span class="note">Chỉ lưu khi bạn bấm xác nhận.</span>
      <button type="button" class="hf-btn ghost" :disabled="busy" @click="decide('reject')">{{ destructive ? 'Giữ lại' : 'Từ chối' }}</button>
      <button type="button" class="hf-btn" :class="destructive ? 'dng' : 'pri'" :disabled="busy" @click="decide('approve')">
        <Loader2 v-if="busy" :size="14" class="hf-spin" aria-hidden="true" />{{ confirmLabel }}
      </button>
    </footer>
  </article>
</template>

<style scoped>
.cf { background: var(--hf-card); border: 1px solid var(--hf-line); border-radius: 22px; display: flex; flex-direction: column; box-shadow: 0 8px 24px rgba(0, 0, 0, .06); overflow: hidden; }
.cfh { display: flex; align-items: flex-start; gap: 12px; padding: 16px 18px 12px; }
.cfic { width: 40px; height: 40px; border-radius: 12px; background: var(--hf-ink); color: var(--hf-on-ink); display: inline-flex; align-items: center; justify-content: center; flex: none; }
.cfic.danger { background: var(--hf-err-bg); color: var(--hf-bad); }
.cfic.sport { background: var(--hf-card); color: var(--hf-ink); border: 1px solid var(--hf-line); }
.cft { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.cft b { font-size: 16px; line-height: 1.3; overflow-wrap: anywhere; }
.cft span { font-size: 12.5px; color: var(--hf-muted); }
.cfm { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex: none; }
.rev { font-size: 11px; font-weight: 700; background: var(--hf-fill); border-radius: 6px; padding: 2px 7px; }
.rev.ed { background: var(--hf-plan-bg); color: var(--hf-plan); }
.exp { font-size: 11px; color: var(--hf-muted); display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
/* Phần thân của từng loại thẻ tự canh lề (px-5) để dải số liệu có thể tràn mép thẻ. */
.cfb { padding: 0 0 16px; display: flex; flex-direction: column; gap: 14px; }
.photo-wrap { padding: 0 20px; }
.cff { display: flex; justify-content: flex-end; align-items: center; gap: 8px; padding: 12px 14px; border-top: 1px solid var(--hf-line-2); background: var(--hf-fill-2); flex-wrap: wrap; }
.note { margin-right: auto; font-size: 12px; color: var(--hf-muted); }
</style>
