<script setup lang="ts">
import { onMounted, onUnmounted, shallowRef, useTemplateRef } from 'vue'
import { Bell, BellDot, CircleDashed, Gauge, Lightbulb, MessageCircle, PartyPopper, X } from 'lucide-vue-next'
import type { AppNotification, NotificationKind } from '@/types/api'
import { useNotifications } from '@/composables/useNotifications'

const emit = defineEmits<{ ask: [text: string]; settings: [] }>()
const { items, unread, error, start, markSeen, dismiss } = useNotifications()
const open = shallowRef(false)
const root = useTemplateRef<HTMLElement>('root')

const ICONS: Record<NotificationKind, typeof Bell> = { briefing: Gauge, insight: Lightbulb, praise: PartyPopper,
                                                       data_quality: CircleDashed }
const QUESTIONS: Record<NotificationKind, string> = {
  briefing: 'Giải thích bản tóm tắt sức khoẻ hôm nay của tôi và gợi ý buổi tập phù hợp.',
  insight: 'Giải thích kỹ hơn nhận xét về sức khoẻ tuần này của tôi.',
  praise: 'Xu hướng hồi phục của tôi tuần này thế nào?',
  data_quality: 'Vì sao hôm nay chưa đủ dữ liệu để đánh giá sức khoẻ của tôi?',
}
const time = (iso: string) => new Intl.DateTimeFormat('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit',
  month: '2-digit', timeZone: 'Asia/Ho_Chi_Minh' }).format(new Date(iso))

async function ask(item: AppNotification) {
  open.value = false
  if (!item.seen_at) await markSeen(item.id).catch(() => undefined)
  emit('ask', QUESTIONS[item.kind])
}

function onDocument(event: MouseEvent | KeyboardEvent) {
  if (!open.value) return
  if (event instanceof KeyboardEvent ? event.key === 'Escape' : !root.value?.contains(event.target as Node)) open.value = false
}

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
</script>

<template>
  <div ref="root" class="relative">
    <button type="button" class="relative flex h-8 w-8 items-center justify-center rounded-lg text-outline transition-colors hover:bg-ink/[0.06] hover:text-primary"
            :aria-label="unread ? `Thông báo, ${unread} chưa đọc` : 'Thông báo'" :aria-expanded="open" @click.stop="open = !open">
      <component :is="unread ? BellDot : Bell" class="h-4 w-4" />
      <span v-if="unread" class="absolute -right-0.5 -top-0.5 min-w-[16px] rounded-full bg-gold px-1 text-[9px] font-semibold leading-4 text-paper">{{ unread }}</span>
    </button>
    <div v-if="open" class="inbox absolute right-0 top-10 z-40 w-[min(360px,calc(100vw-32px))] rounded-2xl border border-ink/[0.08] bg-panel p-3 shadow-xl" role="dialog" aria-label="Thông báo">
      <div class="mb-2 flex items-center justify-between px-1">
        <p class="font-label-telemetry text-[10px] text-outline">THÔNG BÁO</p>
        <button type="button" class="text-[11px] text-outline hover:text-primary" @click="open = false; emit('settings')">Tuỳ chọn</button>
      </div>
      <p v-if="error" class="px-1 text-[11px] text-error">{{ error }}</p>
      <p v-else-if="!items.length" class="px-1 py-4 text-center text-[11px] text-outline">
        Chưa có thông báo. Bật bản tóm tắt buổi sáng trong Cài đặt → Thông báo.</p>
      <ul class="flex max-h-[60vh] flex-col gap-2 overflow-y-auto">
        <li v-for="item in items" :key="item.id" class="rounded-xl border border-ink/[0.06] p-3" :class="{ 'bg-ink/[0.03]': !item.seen_at }">
          <div class="flex items-start gap-2">
            <component :is="ICONS[item.kind]" class="mt-0.5 h-3.5 w-3.5 shrink-0 text-gold" />
            <div class="min-w-0 flex-1">
              <p class="text-xs font-medium text-primary">{{ item.title }}</p>
              <p class="mt-1 text-[11px] leading-relaxed text-on-surface-variant">{{ item.body }}</p>
              <p class="mt-1 font-label-code text-[9.5px] text-outline">{{ time(item.created_at) }}</p>
            </div>
            <button type="button" class="text-outline hover:text-primary" aria-label="Bỏ qua" @click="dismiss(item.id)"><X class="h-3.5 w-3.5" /></button>
          </div>
          <div class="mt-2 flex gap-3 pl-5 text-[11px]">
            <button type="button" class="inline-flex items-center gap-1 text-primary hover:underline" @click="ask(item)"><MessageCircle class="h-3 w-3" />Hỏi thêm</button>
            <button v-if="!item.seen_at" type="button" class="text-outline hover:text-primary" @click="markSeen(item.id)">Đã xem</button>
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>
