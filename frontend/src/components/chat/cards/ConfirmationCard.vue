<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { Activity, CalendarDays, Check, Dumbbell, GlassWater, Loader2, Ruler, ShieldAlert, Target, Trash2, UserRound, UtensilsCrossed, X } from 'lucide-vue-next'
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
}

const props = defineProps<{ action: PendingAction; busy: boolean }>()
const emit = defineEmits<{ confirm: [decision: 'approve' | 'reject', extras: ConfirmExtras] }>()

const display = computed(() => (props.action.display || null) as Record<string, any> | null)
const kind = computed(() => cardKind(props.action.tool, display.value))
const photo = shallowRef<File | null>(null)
const imageSource = shallowRef<string | null>(null)

// Hành động (hoặc bản sửa đổi) mới bắt đầu với lựa chọn mới; thẻ tra cứu chọn sẵn ảnh đầu tiên.
watch(() => `${props.action.action_id}:${props.action.revision}`, () => {
  photo.value = null
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
  if (kind.value === 'plan') return 'Lịch là chỉ định, chưa phải buổi tập đã làm'
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

function decide(decision: 'approve' | 'reject') {
  emit('confirm', decision, decision === 'approve' ? { photo: photo.value, imageSource: imageSource.value } : {})
}
</script>

<template>
  <article class="overflow-hidden rounded-2xl border border-ink/[0.14] bg-panel-raised shadow-[0_20px_50px_rgb(var(--c-shadow)/calc(0.55*var(--shadow-k)))]" :aria-label="`Xác nhận: ${title}`" :data-card="kind">
    <header class="flex items-start gap-3.5 border-b border-ink/[0.08] px-5 py-4">
      <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-ink/[0.06] text-gold">
        <component :is="icon" class="h-5 w-5" :stroke-width="1.6" aria-hidden="true" />
      </div>
      <div class="min-w-0 flex-1">
        <p class="font-label-telemetry text-[10px] uppercase tracking-[0.16em] text-on-surface-variant">Xác nhận ghi dữ liệu · rev {{ action.revision }}</p>
        <h4 class="mt-1 truncate font-headline-md text-xl leading-tight text-primary">{{ title }}</h4>
        <p v-if="subtitle" class="mt-1 text-xs text-on-surface-variant">{{ subtitle }}</p>
      </div>
      <div class="flex shrink-0 flex-col items-end gap-1">
        <span class="rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 font-label-telemetry text-[10px] text-amber-300">Chờ xác nhận</span>
        <span class="font-label-code text-[10px] text-on-surface-variant">Hết hạn {{ expires }}</span>
      </div>
    </header>

    <MealCardBody v-if="kind === 'meal'" :meal="display!" />
    <TrainingCardBody v-else-if="kind === 'training'" :training="display!" />
    <PlanCardBody v-else-if="kind === 'plan'" :plan="display!" />
    <CatalogCardBody v-else-if="kind === 'catalog'" v-model="imageSource" :candidate="display!" :disabled="busy" />
    <SportCardBody v-else-if="kind === 'sport'" :preview="display!" :timezone="(action.payload?.timezone as string | undefined)" />
    <FieldsCardBody v-else :tool="action.tool" :payload="action.payload || {}" />

    <div v-if="kind === 'meal' || kind === 'training'" class="mx-5 mt-4">
      <PhotoAttachment v-model="photo" :label="photoLabel" :disabled="busy" />
    </div>

    <footer class="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-ink/[0.08] px-5 py-4">
      <p class="text-[11px] text-on-surface-variant">Chỉ lưu khi bạn bấm xác nhận.</p>
      <div class="flex gap-2">
        <button
          type="button"
          :disabled="busy"
          class="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-ink/15 bg-ink/[0.04] px-4 text-xs font-medium text-on-surface transition-colors hover:border-ink/30 hover:bg-ink/[0.08] disabled:opacity-50"
          @click="decide('reject')"
        >
          <X class="h-3.5 w-3.5" aria-hidden="true" />Từ chối
        </button>
        <button
          type="button"
          :disabled="busy"
          class="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl bg-ink px-4 text-xs font-semibold text-paper transition-transform hover:scale-[1.02] disabled:opacity-50 motion-reduce:transition-none motion-reduce:hover:scale-100"
          @click="decide('approve')"
        >
          <Loader2 v-if="busy" class="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
          <Check v-else class="h-3.5 w-3.5" aria-hidden="true" />
          {{ busy ? 'Đang lưu…' : photo || imageSource ? 'Xác nhận & lưu ảnh' : 'Xác nhận lưu' }}
        </button>
      </div>
    </footer>
  </article>
</template>
