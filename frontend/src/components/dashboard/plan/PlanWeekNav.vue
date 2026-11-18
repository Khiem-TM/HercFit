<script setup lang="ts">
import { useTemplateRef } from 'vue'
import { ChevronLeft, ChevronRight, LocateFixed } from 'lucide-vue-next'
import { ddmm, WEEKDAY_SHORT, weekday, longDate } from '../format'
import type { PlanWeek } from '@/features/plan/weeks'
defineProps<{ weeks: PlanWeek[]; index: number; selectedDate: string; today: string; currentIndex: number }>()
const emit = defineEmits<{ week: [index: number]; day: [date: string] }>()
const picker = useTemplateRef<HTMLSelectElement>('picker')
defineExpose({ focus: () => { picker.value?.focus({ preventScroll: true }); picker.value?.scrollIntoView({ block: 'start', behavior: 'instant' }) } })
</script>
<template>
  <section class="week-nav" aria-label="Lịch tập theo tuần">
    <div class="toolbar">
      <div class="pager">
        <button type="button" class="arrow" aria-label="Tuần trước" :disabled="index === 0" @click="emit('week', index - 1)"><ChevronLeft :size="20" aria-hidden="true" /></button>
        <div class="week-picker">
          <label for="plan-week" class="hf-sr">Tuần {{ index + 1 }}<span> / {{ weeks.length }}</span></label>
          <select ref="picker" id="plan-week" :value="index" aria-label="Chọn tuần" @change="emit('week', Number(($event.target as HTMLSelectElement).value))">
            <option v-for="(week, i) in weeks" :key="week.start" :value="i">Tuần {{ i + 1 }}/{{ weeks.length }} · {{ ddmm(week.start) }}–{{ ddmm(week.end) }}/{{ week.end.slice(0, 4) }}</option>
          </select>
        </div>
        <button type="button" class="arrow" aria-label="Tuần sau" :disabled="index === weeks.length - 1" @click="emit('week', index + 1)"><ChevronRight :size="20" aria-hidden="true" /></button>
      </div>
      <button type="button" class="current" :disabled="index === currentIndex" @click="emit('week', currentIndex)"><LocateFixed :size="16" aria-hidden="true" />Tuần hiện tại</button>
    </div>
    <div v-if="weeks[index]" class="days">
      <button v-for="day in weeks[index].days" :key="day.date" type="button" class="day" :class="[day.tone, { selected: day.date === selectedDate, 'is-today': day.date === today }]"
        :disabled="day.outside" :aria-pressed="day.date === selectedDate" :aria-current="day.date === today ? 'date' : undefined"
        :aria-label="`${longDate(day.date)}: ${day.sessions.length ? `${day.sessions.length} buổi, ` : ''}${day.text}${day.date === today ? ', hôm nay' : ''}`" @click="emit('day', day.date)">
        <span class="weekday">{{ WEEKDAY_SHORT[weekday(day.date)] }}<i v-if="day.date === today" aria-label="Hôm nay" /></span>
        <strong class="date">{{ day.date.slice(8) }}</strong>
        <span class="day-count">{{ day.outside ? '—' : day.sessions.length ? `${day.sessions.length} buổi` : day.rest ? 'Nghỉ' : 'Trống' }}</span>
        <span class="day-status"><span aria-hidden="true">{{ day.glyph }}</span><span class="status-text">{{ day.text }}</span></span>
      </button>
    </div>
    <p class="mobile-legend"><span>✓ Đã tập</span><span>! Chưa hoàn thành</span><span>○ Sắp tới</span><span>× Đã hủy</span></p>
    <p class="week-caption" aria-live="polite">{{ weeks[index]?.sessions.length ?? 0 }} buổi trong tuần <span>· Chọn một ngày hoặc buổi tập bên dưới</span></p>
  </section>
</template>
<style scoped>
.week-nav { background: var(--hf-card); border: 1px solid var(--hf-line-2); border-radius: 22px; padding: 18px 22px 14px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 14px; }
.pager { display: flex; gap: 10px; align-items: center; min-width: 0; }
.arrow { display: grid; place-items: center; flex: none; width: 44px; height: 44px; background: var(--hf-fill-2); border: 1px solid var(--hf-line); border-radius: 12px; color: var(--hf-ink); }
.arrow:disabled, .current:disabled { opacity: .4; cursor: default; }
.week-picker { display: grid; min-width: 0; }
.week-picker select { min-height: 44px; max-width: 100%; background: var(--hf-card); color: var(--hf-ink); border: 0; font: inherit; font-size: 14px; font-weight: 600; cursor: pointer; padding-right: 4px; }
.current { min-height: 44px; display: flex; gap: 6px; align-items: center; border: 1px solid var(--hf-line); border-radius: 12px; background: var(--hf-card); color: var(--hf-ink); padding: 8px 14px; font-size: 12px; white-space: nowrap; }
.days { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 8px; }
.day { position: relative; display: flex; flex-direction: column; align-items: center; gap: 6px; min-height: 112px; padding: 10px 4px; border: 1px solid var(--hf-line-2); border-radius: 14px; color: var(--hf-ink); background: var(--hf-fill-2); }
.day:hover:not(:disabled) { border-color: var(--hf-muted); }
.day.selected { background: var(--hf-ink); border-color: var(--hf-ink); color: var(--hf-on-ink); }
.day.is-today:not(.selected) { border-color: var(--hf-acc); }
.day:disabled { opacity: .35; cursor: default; }
.weekday { font-size: 12px; display: flex; align-items: center; gap: 5px; }
.weekday i { width: 5px; height: 5px; border-radius: 50%; background: var(--hf-acc); }
.date { font-size: 27px; line-height: 1.2; font-family: var(--hf-mono); font-weight: 600; letter-spacing: -.06em; }
.day-count { font-size: 11px; opacity: .75; }
.day-status { display: flex; align-items: center; gap: 4px; font-size: 10px; text-align: center; margin-top: 2px; }
.done:not(.selected) .day-status { color: var(--hf-ok-text); }
.overdue:not(.selected) .day-status { color: var(--hf-warn-text); }
.mobile-legend { display: none; }
.week-caption { color: var(--hf-muted); font-size: 12px; margin: 14px 0 0; }
@media (max-width: 760px) {
  .week-nav { padding: 14px 8px; }
  .toolbar { flex-wrap: wrap; gap: 4px; margin-bottom: 12px; }
  .pager { flex: 1 1 100%; justify-content: space-between; gap: 5px; }
  .current { margin-left: auto; border: 0; }
  .week-picker select { font-size: 12px; }
  .days { gap: 2px; }
  .mobile-legend { display: flex; flex-wrap: wrap; gap: 4px 12px; color: var(--hf-muted); font-size: 10px; margin: 12px 4px 0; }
  .day { min-height: 105px; padding: 10px 2px; gap: 5px; border-radius: 10px; }
  .date { font-size: 21px; }
  .weekday, .day-count { font-size: 10px; }
  .status-text { display: none; }
  .day-status { font-size: 13px; }
  .week-caption span { display: none; }
}
</style>
