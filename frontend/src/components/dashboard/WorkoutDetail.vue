<script setup lang="ts">
import { computed, nextTick, shallowRef, useTemplateRef } from 'vue'
import { Check, ChevronLeft } from 'lucide-vue-next'
import { useAuth } from '@/composables/useAuth'
import { completionMessage, type CompletionResult, type PlanEntry, type TrainingPlan } from '@/features/plan/model'
import { clockTime, ddmmyyyy, longDate } from './format'
import { exerciseKind, exerciseLine, exerciseName, workoutView } from './today'

/** Chi tiết buổi tập hôm nay. "Ghi nhận đã tập" = ghi một buổi tập thật (không hoàn tác), chỉ cho buổi của hôm nay. */
const props = defineProps<{ plan: TrainingPlan | null; today: string }>()
const emit = defineEmits<{ back: []; done: [message: string]; changed: [] }>()
const { authFetch } = useAuth()

const view = computed(() => workoutView(props.plan, props.today))
const sessions = computed(() => (view.value.entry ? [view.value.entry, ...view.value.others] : []))
const selected = shallowRef<string>()
const entry = computed(() => sessions.value.find(item => item.id === selected.value) ?? sessions.value[0] ?? null)
const confirming = shallowRef(false)
const saving = shallowRef(false)
const saveError = shallowRef<string | null>(null)
const confirmButton = useTemplateRef<HTMLButtonElement>('confirmButton')

async function ask() {
  saveError.value = null
  confirming.value = true
  await nextTick()
  confirmButton.value?.focus()
}

async function save(target: PlanEntry) {
  if (!props.plan || saving.value) return
  saving.value = true
  saveError.value = null
  try {
    const response = await authFetch(`/api/training-plans/${props.plan.id}/entries/${target.id}/complete`, { method: 'POST' })
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}))
      throw new Error(typeof detail?.detail === 'string' ? detail.detail : 'Chưa lưu được. Kiểm tra kết nối và thử lại.')
    }
    const result: CompletionResult = await response.json()
    confirming.value = false
    emit('done', `${completionMessage(result)} · ${target.label}`)
    emit('changed')
  } catch (error) {
    saveError.value = error instanceof Error ? error.message : 'Chưa lưu được. Kiểm tra kết nối và thử lại.'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="layer">
    <button type="button" class="hf-back" @click="emit('back')"><ChevronLeft :size="18" aria-hidden="true" />Hôm nay</button>
    <div v-if="!entry" class="hf-card empty">
      <div class="hf-sv2">Hôm nay không có buổi tập</div>
      <p class="hf-mut">Ngày nghỉ theo kế hoạch hoặc bạn chưa có lịch tập.</p>
    </div>
    <div v-else class="hf-grid" style="margin-top: 16px">
      <section class="hf-card hf-c8">
        <div class="hf-hd">
          <span class="hf-lbl">{{ longDate(entry.scheduled_date) }}/{{ entry.scheduled_date.slice(0, 4) }} · {{ plan?.name }}</span>
          <span class="hf-pill" :class="{ ok: entry.completed_at }">{{ entry.completed_at ? 'Đã ghi nhận hoàn thành' : 'Chưa ghi nhận hoàn thành' }}</span>
        </div>
        <div class="hf-big">{{ entry.label }}</div>
        <div v-if="entry.note" class="hf-info">Ghi chú: {{ entry.note }}</div>
        <div>
          <div v-for="(item, index) in entry.items" :key="index" class="ex">
            <span class="num">{{ index + 1 }}</span>
            <div class="ex-text"><div class="ex-name">{{ exerciseName(item) }}</div><div class="hf-mut ex-sub">{{ exerciseLine(item) }}</div></div>
            <span class="hf-pill">{{ exerciseKind(item) }}</span>
          </div>
        </div>
      </section>
      <div class="hf-c4 hf-stack">
        <section class="hf-card hf-inv">
          <span class="hf-lbl">Ghi nhận buổi tập</span>
          <template v-if="!entry.completed_at">
            <p class="hf-mut para">Khi tập xong, ghi nhận để cập nhật nhịp tập tuần và tiến độ kế hoạch. Buổi tập được ghi vào nhật ký và
              không hoàn tác được.</p>
            <button type="button" class="hf-btn lt" @click="ask">Ghi nhận đã tập</button>
          </template>
          <div v-else class="done">
            <span class="tick"><Check :size="18" :stroke-width="3" aria-hidden="true" /></span>
            <div><div class="done-title">Đã ghi nhận hoàn thành</div>
              <div class="hf-mut small">{{ entry.completed_at.slice(0, 10) === today ? `Hôm nay, lúc ${clockTime(entry.completed_at)}` : ddmmyyyy(entry.completed_at) }}</div></div>
          </div>
        </section>
        <section v-if="sessions.length > 1" class="hf-card">
          <span class="hf-lbl">Buổi khác hôm nay</span>
          <button v-for="other in sessions.filter(item => item.id !== entry?.id)" :key="other.id" type="button" class="other" @click="selected = other.id">
            <span><b>{{ other.label }}</b><br><span class="hf-mut small">{{ other.items.length }} bài</span></span>
            <span class="hf-pill" :class="{ ok: other.completed_at }">{{ other.completed_at ? 'Đã tập' : 'Chưa ghi nhận' }}</span>
          </button>
        </section>
        <section v-if="view.overdue" class="hf-card">
          <span class="hf-lbl">Buổi quá hạn</span>
          <div class="hf-kv"><div><b>{{ view.overdue.label }}</b><br><span>{{ longDate(view.overdue.scheduled_date) }} · không thể ghi nhận bù</span></div>
            <span class="hf-pill bad">Quá hạn</span></div>
        </section>
      </div>
    </div>

    <div v-if="confirming && entry" class="dlgwrap" @click.self="confirming = false" @keydown.esc.stop="confirming = false">
      <div class="dlg" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
        <h2 id="confirm-title">Ghi nhận đã tập {{ entry.label }}?</h2>
        <p class="hf-mut">Buổi tập ngày {{ ddmmyyyy(entry.scheduled_date) }} sẽ được ghi vào nhật ký, đánh dấu hoàn thành và cập nhật
          nhịp tập tuần, tiến độ kế hoạch. Thao tác này không hoàn tác được.</p>
        <div v-if="saveError" class="hf-err" role="alert">{{ saveError }}</div>
        <div class="hf-acts end">
          <button type="button" class="hf-btn" @click="confirming = false">Huỷ</button>
          <button ref="confirmButton" type="button" class="hf-btn pri" :disabled="saving" @click="save(entry)">
            {{ saving ? 'Đang lưu…' : saveError ? 'Thử lại' : 'Xác nhận ghi nhận' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.empty { margin-top: 16px; align-items: flex-start; padding: 40px; }
.empty p { margin: 0; }
.ex { display: grid; grid-template-columns: 36px minmax(0, 1fr) auto; gap: 14px; align-items: center; padding: 14px 0; border-top: 1px solid var(--hf-line-2); }
.ex:first-child { border-top: 0; }
.num { width: 36px; height: 36px; border-radius: 50%; background: var(--hf-fill); display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px; }
.ex-text { min-width: 0; }
.ex-name { font-weight: 600; font-size: 15px; }
.ex-sub { font-size: 13px; margin-top: 2px; }
.para { margin: 0; font-size: 14px; line-height: 1.5; }
.done { display: flex; gap: 12px; align-items: center; }
.tick { width: 38px; height: 38px; border-radius: 50%; background: #fff; color: #141416; display: flex; align-items: center; justify-content: center; flex: none; }
.done-title { font-weight: 700; }
.small { font-size: 13px; }
.other {
  display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; text-align: left;
  border: 0; background: var(--hf-fill-2); border-radius: 14px; padding: 10px 14px; font-size: 14px;
}
.other:hover { background: var(--hf-hover); }
.dlgwrap { position: fixed; inset: 0; background: var(--hf-scrim); display: flex; align-items: center; justify-content: center; z-index: 7; padding: 16px; }
.dlg { background: var(--hf-card); border-radius: 26px; padding: 26px; max-width: 460px; width: 100%; display: flex; flex-direction: column; gap: 14px; box-shadow: 0 30px 80px rgba(0, 0, 0, .25); }
.dlg h2 { margin: 0; font-size: 22px; }
.dlg p { margin: 0; font-size: 14px; line-height: 1.55; }
.dlg .hf-err { margin: 0; }
.end { justify-content: flex-end; }
</style>
