<script setup lang="ts">
import { computed, onUnmounted, shallowRef, watch } from 'vue'
import { CalendarCheck, Check, Flag, Loader2, Lock, Moon, Plus, RefreshCw } from 'lucide-vue-next'
import { useAuth } from '@/composables/useAuth'
import { setTarget, stepSummary, WORKOUT } from '@/features/chat/confirmation'
import {
  completionMessage, endedDay, planDays, planProgress, taskState, today,
  type CompletionResult, type PlanEntry, type TaskState, type TrainingPlan,
} from '@/features/plan/model'

/** Lịch tập thành checklist theo ngày. Tick buổi hôm nay = ghi buổi tập thật (calo, Google Health), không hoàn tác;
 * buổi đã qua bị khoá. Kết thúc sớm giữ mọi buổi đã tập; lịch vừa kết thúc vẫn hiện (chỉ đọc) tới khi có lịch mới. */
const props = defineProps<{ revision: number }>()
const emit = defineEmits<{ 'create-plan': [] }>()
const { authFetch } = useAuth()
const plan = shallowRef<TrainingPlan | null>(null)
const previous = shallowRef<TrainingPlan | null>(null)
const status = shallowRef<'loading' | 'ready' | 'error'>('loading')
const saving = shallowRef<string>()
const asking = shallowRef<string>()
const ending = shallowRef(false)
const notice = shallowRef('')
const saved = shallowRef<{ id: string; message: string; notices: string[] }>()
let controller: AbortController | undefined

const shown = computed(() => plan.value ?? previous.value)
const ended = computed(() => (shown.value ? endedDay(shown.value) : null))
const day = computed(() => (shown.value ? today(shown.value.timezone) : ''))
const days = computed(() => (shown.value ? planDays(shown.value) : []))
const progress = computed(() => (shown.value ? planProgress(shown.value, day.value) : null))
const state = (entry: PlanEntry) => taskState(entry, day.value, ended.value)
const REASON: Record<string, string> = { EXPIRED: 'hết hạn', ENDED_EARLY: 'kết thúc sớm', USER_ENDED: 'kết thúc sớm' }
const endLabel = computed(() => {
  const reason = shown.value?.end_reason || ''
  return REASON[reason] || (reason.startsWith('GOAL_') ? 'mục tiêu đã kết thúc' : 'đã kết thúc')
})

async function read(path: string, signal: AbortSignal): Promise<TrainingPlan | null> {
  const response = await authFetch(path, { signal })
  if (response.status === 404) return null
  if (!response.ok) throw new Error('Plan unavailable')
  return response.json()
}

async function load() {
  controller?.abort()
  const current = new AbortController()
  controller = current
  if (!shown.value) status.value = 'loading'
  try {
    const active = await read('/api/training-plans/current', current.signal)
    const last = active ? null : await read('/api/training-plans/previous', current.signal)
    if (current.signal.aborted) return
    plan.value = active
    previous.value = last
    status.value = 'ready'
  } catch {
    if (!current.signal.aborted) status.value = shown.value ? 'ready' : 'error'
  }
}

const HINT: Record<TaskState, string> = {
  done: 'Đã ghi buổi tập, không hoàn tác', overdue: 'Đã quá ngày của buổi này', upcoming: 'Chưa tới ngày của buổi này',
  cancelled: 'Đã huỷ khi kết thúc lịch', today: '',
}

/** Bấm vào buổi hôm nay chỉ mở bước xác nhận; buổi đã tick, quá hạn, bị huỷ hay chưa tới ngày không làm gì. */
function ask(entry: PlanEntry) {
  if (saving.value || !plan.value || state(entry) !== 'today') return
  asking.value = asking.value === entry.id ? undefined : entry.id
}

async function failed(response: Response) {
  const detail = await response.json().catch(() => ({}))
  return new Error(typeof detail?.detail === 'string' ? detail.detail : 'Chưa lưu được. Thử lại sau.')
}

async function complete(entry: PlanEntry) {
  if (!plan.value || saving.value || state(entry) !== 'today') return
  saving.value = entry.id
  notice.value = ''
  try {
    const response = await authFetch(`/api/training-plans/${plan.value.id}/entries/${entry.id}/complete`, { method: 'POST' })
    if (!response.ok) throw await failed(response)
    const result: CompletionResult = await response.json()
    plan.value = { ...plan.value, entries: plan.value.entries.map(item => (item.id === result.entry.id ? result.entry : item)) }
    saved.value = { id: entry.id, message: completionMessage(result), notices: result.notices }
    asking.value = undefined
  } catch (error) {
    notice.value = error instanceof Error ? error.message : 'Chưa lưu được. Thử lại sau.'
    // Lịch có thể vừa được thay hoặc kết thúc trong khung chat.
    load()
  } finally {
    saving.value = undefined
  }
}

/** Kết thúc trước hạn: buổi đã tập và nhật ký giữ nguyên, các buổi còn lại bị huỷ; có thể lập lịch mới ngay. */
async function endPlan(next: boolean) {
  if (!plan.value || saving.value) return
  saving.value = 'end'
  notice.value = ''
  try {
    const response = await authFetch(`/api/training-plans/${plan.value.id}/end`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_version_id: plan.value.version_id, reason: 'ENDED_EARLY' }),
    })
    if (!response.ok) throw await failed(response)
    previous.value = await response.json()
    plan.value = null
    ending.value = false
    asking.value = saved.value = undefined
    if (next) emit('create-plan')
  } catch (error) {
    notice.value = error instanceof Error ? error.message : 'Chưa kết thúc được lịch. Thử lại sau.'
    load()
  } finally {
    saving.value = undefined
  }
}

function heading(date: string) {
  if (date === day.value) return 'Hôm nay'
  const label = new Date(`${date}T00:00:00`).toLocaleDateString('vi-VN', { weekday: 'long', day: '2-digit', month: '2-digit' })
  return label.charAt(0).toUpperCase() + label.slice(1)
}

function shortDay(date: string | null) {
  return date ? new Date(`${date}T00:00:00`).toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' }) : ''
}

function detail(item: Record<string, any>) {
  const prescription = item.prescription || {}
  if (prescription.kind === 'STRENGTH') return (prescription.sets || []).map(setTarget).join(' · ')
  if (prescription.kind === 'ENDURANCE') return [WORKOUT[prescription.workout_type], stepSummary(prescription)].filter(Boolean).join(' · ')
  return ''
}

watch(() => props.revision, load, { immediate: true })
onUnmounted(() => controller?.abort())
</script>

<template>
  <div class="checklist" :aria-busy="status === 'loading'">
    <div v-if="status === 'loading'" class="empty" role="status">Đang đọc lịch tập…</div>
    <div v-else-if="status === 'error'" class="empty">
      <p>Chưa tải được lịch tập.</p>
      <button type="button" @click="load"><RefreshCw :size="12" /> Thử lại</button>
    </div>
    <div v-else-if="!shown" class="empty">
      <CalendarCheck :size="30" :stroke-width="1.2" />
      <p>Chưa có lịch tập đang chạy</p>
      <small>Nhờ trợ lý trong khung chat, ví dụ “Lên lịch tập Push Pull Legs 4 buổi/tuần”. Xác nhận trên thẻ là lịch hiện ở đây.</small>
      <button type="button" class="cta" @click="emit('create-plan')"><Plus :size="13" /> Lập lịch mới</button>
    </div>
    <template v-else>
      <header class="summary">
        <p class="eyeline">
          LỊCH TẬP · {{ shown.start_date }} → {{ shown.end_date }}<template v-if="ended"> · {{ endLabel.toUpperCase() }} {{ shortDay(ended) }}</template>
        </p>
        <div class="title">
          <h3>{{ shown.name }}</h3>
          <button v-if="plan && !ending" type="button" class="end" :disabled="!!saving" @click="ending = true"><Flag :size="12" /> Kết thúc sớm</button>
        </div>
        <div class="progress-heading">
          <p><strong>{{ progress!.done }}</strong><span> / {{ progress!.total }} buổi {{ ended ? 'hoàn thành trước khi kết thúc' : 'đã hoàn thành' }}</span></p>
          <span class="percent" :class="{ complete: progress!.percent === 100 }"><Check v-if="progress!.percent === 100" :size="15" />{{ progress!.percent }}<small>%</small></span>
        </div>
        <div class="track" role="progressbar" aria-label="Tiến trình hoàn thành lịch tập" :aria-valuenow="progress!.percent" aria-valuemin="0" aria-valuemax="100"
             :aria-valuetext="`${progress!.done} trên ${progress!.total} buổi`">
          <span :style="{ transform: `scaleX(${progress!.percent / 100})` }" />
          <i v-if="progress!.total && !ended" class="due" :style="{ left: `${(progress!.due / progress!.total) * 100}%` }" title="Số buổi đến hạn tới hôm nay" />
        </div>
        <p class="note">
          <template v-if="!ended">{{ progress!.due }} buổi đến hạn tới hôm nay</template>
          <template v-else>Lịch đã kết thúc; các buổi đã tập và nhật ký được giữ nguyên</template>
          <template v-if="progress!.missed"> · <em>{{ progress!.missed }} buổi quá hạn</em></template>
        </p>
        <div v-if="ending" class="confirm wide" role="group" aria-label="Xác nhận kết thúc lịch sớm">
          <p>Kết thúc lịch trước hạn? Buổi đã tập và nhật ký được giữ nguyên; các buổi còn lại (kể cả hôm nay nếu chưa tick) bị huỷ. <strong>Không hoàn tác được.</strong></p>
          <div>
            <button type="button" class="ghost" :disabled="!!saving" @click="ending = false">Huỷ</button>
            <button type="button" class="ghost" :disabled="!!saving" @click="endPlan(false)">Kết thúc</button>
            <button type="button" class="primary" :disabled="!!saving" @click="endPlan(true)">
              {{ saving === 'end' ? 'Đang kết thúc…' : 'Kết thúc & lập lịch mới' }}
            </button>
          </div>
        </div>
        <button v-if="ended" type="button" class="cta" @click="emit('create-plan')"><Plus :size="13" /> Lập lịch mới</button>
      </header>
      <p v-if="notice" class="notice" role="status">{{ notice }}</p>

      <section v-for="group in days" :key="group.date" class="day" :class="{ today: group.date === day && !ended }">
        <h4>{{ heading(group.date) }}</h4>
        <ul>
          <li v-for="entry in group.entries" :key="entry.id">
            <div v-if="entry.is_rest" class="rest"><Moon :size="13" /> Nghỉ hồi phục</div>
            <div v-else class="task" :class="state(entry)">
              <button type="button" class="row" role="checkbox" :aria-checked="!!entry.completed_at"
                      :aria-disabled="state(entry) !== 'today'" :aria-expanded="asking === entry.id"
                      :title="HINT[state(entry)]" @click="ask(entry)">
                <span class="box" aria-hidden="true">
                  <Loader2 v-if="saving === entry.id" :size="12" class="spin" />
                  <Lock v-else-if="state(entry) === 'overdue'" :size="10" />
                  <Check v-else :size="12" :stroke-width="3" />
                </span>
                <span class="text">
                  <strong>{{ entry.label }}<em v-if="state(entry) === 'overdue'" class="badge">Quá hạn</em><em v-else-if="state(entry) === 'cancelled'" class="badge muted">Đã huỷ</em></strong>
                  <span v-for="item in entry.items" :key="item.id" class="item">
                    {{ item.exercise_snapshot?.name_vi || 'Bài tập' }}<small v-if="detail(item)"> — {{ detail(item) }}</small>
                  </span>
                </span>
              </button>
              <div v-if="asking === entry.id" class="confirm" role="group" aria-label="Xác nhận hoàn thành buổi tập">
                <p>Ghi buổi tập này vào nhật ký theo lịch (calo ước tính) và đồng bộ Google Health nếu đã kết nối. <strong>Không hoàn tác được.</strong></p>
                <div>
                  <button type="button" class="ghost" :disabled="saving === entry.id" @click="asking = undefined">Huỷ</button>
                  <button type="button" class="primary" :disabled="saving === entry.id" @click="complete(entry)">
                    {{ saving === entry.id ? 'Đang ghi…' : 'Đã tập xong · Ghi lại' }}
                  </button>
                </div>
              </div>
              <div v-if="saved?.id === entry.id" class="result" role="status">
                <p>{{ saved.message }}</p>
                <small v-for="(text, index) in saved.notices" :key="index">{{ text }}</small>
              </div>
            </div>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.checklist { padding: 6px var(--gutter, 26px) 26px; }
.empty { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 48px 12px; text-align: center; color: light-dark(#776641, #b9aa89); }
.empty p { font: 18px 'Playfair Display', serif; margin: 0; }
.empty small { max-width: 320px; font-size: 11px; line-height: 1.6; color: light-dark(#74736d, #85847e); }
.empty button { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; border-bottom: 1px solid currentColor; }
.summary { position: sticky; top: 0; z-index: 2; padding: 8px 0 14px; background: linear-gradient(light-dark(#f3f2ef, #101216) 88%, transparent); }
.eyeline { font: 8px 'JetBrains Mono', monospace; letter-spacing: .18em; color: light-dark(#7d6431, #bda77c); margin: 0 0 6px; }
.summary h3 { margin: 0; font: 20px 'Playfair Display', serif; color: light-dark(#322820, #f0e3d8); }
.progress-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 10px; margin: 12px 0 8px; }
.progress-heading p { margin: 0; }
.progress-heading strong { font: 32px 'Playfair Display', serif; color: light-dark(#322820, #f0e3d8); }
.progress-heading p > span { font-size: 11px; color: light-dark(#5f544a, #b3a69b); }
.percent { display: flex; align-items: center; gap: 3px; font: 22px 'JetBrains Mono', monospace; color: light-dark(#87671a, #d4b77d); }
.percent small { font-size: 12px; }
.percent.complete { color: light-dark(#517c40, #a8cf9a); }
.track { position: relative; height: 10px; border-radius: 8px; overflow: hidden; background: light-dark(#1818180d, #ffffff0d); }
.track > span { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, light-dark(#87671a, #a88b4f), light-dark(#b08d3c, #e6cf9e)); transform-origin: left; transition: transform 600ms cubic-bezier(.2,.8,.2,1); }
.track .due { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: light-dark(#2f2d28, #e5e2dc); opacity: .45; }
.note { margin: 8px 0 0; font-size: 11px; color: light-dark(#61554b, #b1a499); }
.note em { font-style: normal; color: light-dark(#9b552a, #e3a37f); }
.notice { margin: 4px 0 8px; font-size: 11px; color: light-dark(#9b552a, #e3a37f); }
.day { margin-top: 8px; }
.day h4 { margin: 0; padding: 8px 0 6px; font: 14px 'Playfair Display', serif; font-weight: 400; color: light-dark(#362e1d, #e9dfca); }
.day.today h4 { color: light-dark(#87671a, #d4b77d); }
.day ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.rest { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border-radius: 10px; font-size: 11px; color: light-dark(#74736d, #85847e); background: light-dark(#18181805, #ffffff05); }
.task { border: 1px solid light-dark(#1818180f, #ffffff0f); border-radius: 12px; transition: background 200ms, border-color 200ms, opacity 200ms; }
.row { display: grid; grid-template-columns: 20px 1fr; gap: 10px; width: 100%; padding: 10px 12px; text-align: left; cursor: default; border-radius: inherit; }
.row:focus-visible { outline: 1px solid light-dark(#87671a, #d4b77d); }
.task.today { border-color: light-dark(#87671a40, #d4b77d40); }
.task.today .row { cursor: pointer; }
.task.today:hover { background: light-dark(#87671a0a, #d4b77d0a); }
.box { display: grid; place-items: center; width: 18px; height: 18px; margin-top: 1px; border: 1.5px solid light-dark(#87671a80, #d4b77d80); border-radius: 6px; color: transparent; transition: background 200ms, color 200ms; }
.task.done .box { background: light-dark(#87671a, #d4b77d); border-color: transparent; color: light-dark(#fff, #101216); }
.task.done strong { text-decoration: line-through; text-decoration-color: light-dark(#87671a99, #d4b77d99); }
.task.overdue, .task.upcoming, .task.cancelled { opacity: .6; }
.task.cancelled strong { text-decoration: line-through; text-decoration-color: light-dark(#18181840, #ffffff40); }
.badge.muted { color: light-dark(#74736d, #85847e); background: light-dark(#1818180d, #ffffff0d); }
.title { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.end { display: inline-flex; flex-shrink: 0; align-items: center; gap: 5px; padding: 4px 10px; border: 1px solid light-dark(#9b552a40, #e3a37f40); border-radius: 999px; font-size: 10.5px; color: light-dark(#9b552a, #e3a37f); }
.end:hover { background: light-dark(#9b552a0d, #e3a37f0d); }
.cta { display: inline-flex; align-items: center; gap: 6px; margin-top: 10px; padding: 6px 14px; border: 0; border-radius: 999px; font-size: 11px; font-weight: 600; background: light-dark(#87671a, #d4b77d); color: light-dark(#fff, #101216); }
.empty .cta { border-bottom: 0; }
.confirm.wide { margin: 10px 0 0; }
.task.overdue .box { border-color: light-dark(#9b552a99, #e3a37f99); color: light-dark(#9b552a, #e3a37f); }
.badge { margin-left: 8px; padding: 1px 6px; border-radius: 8px; font: 9px 'JetBrains Mono', monospace; font-style: normal; color: light-dark(#9b552a, #e3a37f); background: light-dark(#9b552a14, #e3a37f14); }
.spin { color: light-dark(#87671a, #d4b77d); animation: spin 1s linear infinite; }
.confirm, .result { margin: 0 12px 10px 42px; padding: 10px 12px; border-radius: 10px; font-size: 11px; line-height: 1.55; background: light-dark(#87671a0d, #d4b77d0d); color: light-dark(#4e4a40, #c9c4b8); }
.confirm p, .result p { margin: 0; }
.confirm div { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.confirm button { padding: 5px 12px; border-radius: 8px; font-size: 11px; }
.confirm .ghost { border: 1px solid light-dark(#18181820, #ffffff20); }
.confirm .primary { background: light-dark(#87671a, #d4b77d); color: light-dark(#fff, #101216); font-weight: 600; }
.confirm button:disabled { opacity: .6; }
.result small { display: block; margin-top: 4px; color: light-dark(#9b552a, #e3a37f); }
@keyframes spin { to { transform: rotate(360deg); } }
.text { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.text strong { font-size: 12px; font-weight: 500; color: light-dark(#312d25, #e6e1d6); }
.item { font-size: 10.5px; line-height: 1.5; color: light-dark(#5f5b52, #a19d93); }
.item small { font-size: 10px; color: light-dark(#7c786f, #87847b); }
@media (prefers-reduced-motion: reduce) { .track > span, .task, .box { transition: none; } .spin { animation: none; } }
</style>
