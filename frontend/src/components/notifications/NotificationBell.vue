<script setup lang="ts">
import { computed, onMounted, onUnmounted, shallowRef, useTemplateRef, watch } from 'vue'
import { AnimatePresence, motion } from 'motion-v'
import {
  Bell, BellDot, CalendarClock, CalendarSync, ChevronDown, CircleDashed, ClipboardCheck, Droplets, Footprints, Gauge,
  HeartPulse, Lightbulb, Moon, NotebookPen, PartyPopper, Scale, Utensils, X,
} from 'lucide-vue-next'
import type { AlertGroup, AlertPayload, AppNotification, NotificationKind, ReviewPayload } from '@/types/api'
import { useNotifications } from '@/composables/useNotifications'
import { popover, presence, slideUp, SPRING } from '@/motion'
import { alertView, reviewView } from './notificationView'

const emit = defineEmits<{ ask: [text: string]; settings: [] }>()
const { items, unread, error, start, markSeen, dismiss } = useNotifications()
const open = shallowRef(false)
const why = shallowRef<string | null>(null)
const root = useTemplateRef<HTMLElement>('root')
const bump = shallowRef(0)

const ICONS: Record<NotificationKind, typeof Bell> = {
  alert: HeartPulse, review: ClipboardCheck, reminder: CalendarClock, proposal: CalendarSync,
  briefing: Gauge, insight: Lightbulb, praise: PartyPopper, data_quality: CircleDashed, summary: NotebookPen,
}
const GROUP_ICONS: Record<AlertGroup, typeof Bell> = {
  heart: HeartPulse, oxygen: Droplets, sleep: Moon, weight: Scale, nutrition: Utensils, activity: Footprints,
}
const FALLBACK_QUESTION = 'Giải thích giúp mình thông báo này.'
const time = (iso: string) => new Intl.DateTimeFormat('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit',
  month: '2-digit', timeZone: 'Asia/Ho_Chi_Minh' }).format(new Date(iso))

const views = computed(() => items.value.map(item => ({
  item,
  alert: item.kind === 'alert' ? alertView(item.payload as unknown as AlertPayload) : null,
  review: item.kind === 'review' ? reviewView(item.payload as unknown as ReviewPayload) : null,
})))

function icon(item: AppNotification) {
  const group = (item.payload as { group?: AlertGroup }).group
  return item.kind === 'alert' && group ? GROUP_ICONS[group] ?? HeartPulse : ICONS[item.kind] ?? Bell
}

/** Đề xuất mang sẵn câu hỏi cho trợ lý (payload.ask); "Giữ nguyên" chỉ bỏ qua thông báo. */
const proposal = (item: AppNotification) => item.kind === 'proposal' && typeof item.payload.ask === 'string'

async function ask(item: AppNotification) {
  open.value = false
  if (!item.seen_at) await markSeen(item.id).catch(() => undefined)
  emit('ask', typeof item.payload.ask === 'string' ? item.payload.ask : FALLBACK_QUESTION)
}

function onDocument(event: MouseEvent | KeyboardEvent) {
  if (!open.value) return
  if (event instanceof KeyboardEvent ? event.key === 'Escape' : !root.value?.contains(event.target as Node)) open.value = false
}

// Badge nảy nhẹ khi có thông báo mới (không nảy khi số giảm).
watch(unread, (now, before) => { if (now > (before ?? 0)) bump.value += 1 })

let stop: (() => void) | undefined
onMounted(() => {
  stop = start()
  document.addEventListener('click', onDocument)
  document.addEventListener('keydown', onDocument)
})
onUnmounted(() => {
  stop?.()
  document.removeEventListener('click', onDocument)
  document.removeEventListener('keydown', onDocument)
})

defineExpose({ open: () => { open.value = true } })
</script>

<template>
  <div ref="root" class="bell">
    <button type="button" class="hf-ib clear" style="width: 40px; height: 40px"
            :aria-label="unread ? `Thông báo, ${unread} chưa đọc` : 'Thông báo'" :aria-expanded="open" @click.stop="open = !open">
      <component :is="unread ? BellDot : Bell" :size="18" :stroke-width="1.8" />
      <motion.span v-if="unread" :key="bump" class="count" :initial="{ scale: 0.6 }" :animate="{ scale: 1 }"
                   :transition="SPRING.snappy">{{ unread }}</motion.span>
    </button>
    <AnimatePresence>
      <motion.div v-if="open" class="inbox" role="dialog" aria-label="Thông báo" v-bind="presence(popover)">
        <div class="inbox-head">
          <b>Thông báo</b>
          <button type="button" class="hf-lnk" @click="open = false; emit('settings')">Tuỳ chọn</button>
        </div>
        <p v-if="error" class="note bad">{{ error }}</p>
        <p v-else-if="!items.length" class="note">Chưa có thông báo. Bật thông báo trong Hồ sơ &amp; kết nối › Thông báo AI.</p>
        <ul class="list">
          <AnimatePresence :initial="false">
            <motion.li v-for="{ item, alert, review } in views" :key="item.id" layout class="item"
                       :class="[{ unread: !item.seen_at }, alert ? `sev-${alert.severity}` : '']" v-bind="presence(slideUp)">
              <div class="row">
                <span class="ic"><component :is="icon(item)" :size="15" aria-hidden="true" /></span>
                <div class="text">
                  <p v-if="alert" class="sev">{{ alert.label }}</p>
                  <p class="title">{{ item.title }}</p>
                  <p class="body">{{ item.body }}</p>

                  <template v-if="review">
                    <p v-if="review.score !== null" class="score"><b class="hf-dg">{{ review.score }}</b><span>/100 · {{ review.grade }}</span></p>
                    <ul v-if="review.dimensions.length" class="dims">
                      <li v-for="d in review.dimensions" :key="d.id" :class="d.rating">
                        <span>{{ d.label }}</span><b>{{ d.score ?? '—' }}</b>
                      </li>
                    </ul>
                    <p v-for="line in review.highlights" :key="'h' + line" class="point good">{{ line }}</p>
                    <p v-for="line in review.improvements" :key="'i' + line" class="point">{{ line }}</p>
                    <p v-if="review.tip" class="tip">{{ review.tip }}</p>
                  </template>

                  <template v-if="alert">
                    <ul v-if="alert.advice.length" class="advice"><li v-for="line in alert.advice" :key="line">{{ line }}</li></ul>
                    <button type="button" class="why-btn" :aria-expanded="why === item.id" @click="why = why === item.id ? null : item.id">
                      Vì sao?<ChevronDown :size="14" :class="{ flip: why === item.id }" aria-hidden="true" />
                    </button>
                    <AnimatePresence>
                      <motion.div v-if="why === item.id" class="why" :initial="{ opacity: 0, height: 0 }"
                                  :animate="{ opacity: 1, height: 'auto' }" :exit="{ opacity: 0, height: 0 }">
                        <p><b>{{ alert.metric }}:</b> {{ alert.value }} · ngưỡng {{ alert.threshold }} ({{ alert.window }})</p>
                        <p v-if="alert.basis.length" class="hf-mut">Theo thể trạng: {{ alert.basis.join(', ') }}</p>
                        <p v-for="source in alert.sources" :key="source.url" class="src">
                          Nguồn: <a :href="source.url" target="_blank" rel="noopener noreferrer">{{ source.org }} – {{ source.title }} ({{ source.year }})</a>
                        </p>
                      </motion.div>
                    </AnimatePresence>
                  </template>
                  <p class="when">{{ time(item.created_at) }}</p>
                </div>
                <button type="button" class="hf-ib clear sm" aria-label="Bỏ qua" @click="dismiss(item.id)"><X :size="14" /></button>
              </div>
              <div class="hf-acts acts">
                <template v-if="proposal(item)">
                  <button type="button" class="hf-btn sm pri" @click="ask(item)">Điều chỉnh lịch</button>
                  <button type="button" class="hf-btn sm" @click="dismiss(item.id)">Giữ nguyên</button>
                </template>
                <template v-else>
                  <button type="button" class="hf-btn sm" @click="ask(item)">{{ review ? 'Bàn với trợ lý' : alert ? 'Hỏi thêm' : 'Hỏi trợ lý' }}</button>
                  <button v-if="!item.seen_at" type="button" class="hf-btn sm ghost" @click="markSeen(item.id)">Đã xem</button>
                </template>
              </div>
            </motion.li>
          </AnimatePresence>
        </ul>
      </motion.div>
    </AnimatePresence>
  </div>
</template>

<style scoped>
.bell { position: relative; }
.count {
  position: absolute; top: 2px; right: 2px; min-width: 17px; height: 17px; border-radius: 999px; padding: 0 4px;
  background: var(--hf-acc); color: #fff; font-size: 10px; font-weight: 700; line-height: 17px; text-align: center;
}
.inbox {
  position: absolute; right: 0; top: 48px; z-index: 40; width: min(400px, calc(100vw - 32px));
  background: var(--hf-card); border: 1px solid var(--hf-line); border-radius: 22px; padding: 14px;
  box-shadow: 0 14px 36px rgba(0, 0, 0, .14); transform-origin: top right;
}
.inbox-head { display: flex; align-items: center; justify-content: space-between; padding: 0 4px 8px; font-size: 15px; }
.note { margin: 0; padding: 18px 6px; text-align: center; font-size: 13px; color: var(--hf-muted); }
.note.bad { color: var(--hf-bad); }
.list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; max-height: 64vh; overflow-y: auto; }
.item { border-radius: 16px; padding: 12px; background: var(--hf-fill-2); border-left: 3px solid transparent; }
.item.unread { background: var(--hf-fill); }
.item.sev-warn { border-left-color: var(--hf-warn-dot); }
.item.sev-urgent { border-left-color: var(--hf-bad); }
.row { display: flex; gap: 10px; align-items: flex-start; }
.ic {
  width: 28px; height: 28px; border-radius: 9px; background: var(--hf-card); flex: none;
  display: inline-flex; align-items: center; justify-content: center; color: var(--hf-ink);
}
.sev-warn .ic { color: var(--hf-warn-dot); }
.sev-urgent .ic { color: var(--hf-bad); }
.text { min-width: 0; flex: 1; }
.sev { margin: 0 0 2px; font-size: 11px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--hf-faint); }
.sev-warn .sev { color: var(--hf-warn-text); }
.sev-urgent .sev { color: var(--hf-bad); }
.title { margin: 0; font-size: 14px; font-weight: 600; color: var(--hf-ink); }
.body { margin: 4px 0 0; font-size: 13px; line-height: 1.5; color: var(--hf-sub); }
.advice { margin: 6px 0 0; padding-left: 18px; list-style: disc; font-size: 13px; line-height: 1.5; color: var(--hf-ink); }
.why-btn {
  margin-top: 6px; display: inline-flex; align-items: center; gap: 4px; border: 0; background: none; padding: 2px 0;
  font: inherit; font-size: 12px; font-weight: 600; color: var(--hf-sub); cursor: pointer;
}
.why-btn:hover { color: var(--hf-ink); }
.why-btn svg { transition: transform var(--hf-dur-base) var(--hf-ease-out); }
.why-btn .flip { transform: rotate(180deg); }
.why { overflow: hidden; font-size: 12px; line-height: 1.5; color: var(--hf-sub); }
.why p { margin: 4px 0 0; }
.why a { color: var(--hf-ink); text-decoration: underline; text-underline-offset: 2px; }
.score { margin: 8px 0 0; display: flex; align-items: baseline; gap: 4px; font-size: 13px; color: var(--hf-sub); }
.score b { font-size: 30px; color: var(--hf-ink); }
.dims { list-style: none; margin: 8px 0 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 6px; }
.dims li { display: flex; justify-content: space-between; gap: 6px; background: var(--hf-card); border-radius: 10px; padding: 6px 8px; font-size: 12px; }
.dims li.good b { color: var(--hf-ok-text); }
.dims li.poor b { color: var(--hf-bad); }
.dims li.missing { color: var(--hf-faint); }
.point { margin: 6px 0 0; font-size: 13px; line-height: 1.45; padding-left: 14px; position: relative; }
.point::before { content: '–'; position: absolute; left: 0; color: var(--hf-faint); }
.point.good::before { content: '+'; color: var(--hf-ok); }
.tip { margin: 8px 0 0; font-size: 13px; background: var(--hf-card); border-radius: 10px; padding: 8px 10px; }
.when { margin: 6px 0 0; font-size: 11px; color: var(--hf-faint); font-family: var(--hf-mono); }
.acts { padding: 10px 0 0 38px; }
.acts .hf-btn:not(.pri) { background: var(--hf-card); }
.acts .hf-btn:not(.pri):hover:not(:disabled) { background: var(--hf-press); }
</style>
