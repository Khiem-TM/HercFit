<script setup lang="ts">
import { computed } from 'vue'
import { ChevronRight, Dumbbell, Footprints } from 'lucide-vue-next'
import { endedDay, taskState, type PlanEntry, type TrainingPlan } from '@/features/plan/model'
import { STATUS } from '@/features/plan/weeks'
import { sessionMeasure } from '@/features/plan/exercises'
import { longDate } from '../format'
const props = defineProps<{ plan: TrainingPlan; entries: PlanEntry[]; selectedId: string | null; today: string }>()
const emit = defineEmits<{ select: [id: string] }>()
const rows = computed(() => props.entries.map(entry => ({ entry, status: STATUS[taskState(entry, props.today, endedDay(props.plan))], measure: sessionMeasure(entry.items), running: entry.items.every(i => i.prescription.kind === 'ENDURANCE') })))
</script>
<template>
  <nav class="sessions" aria-label="Buổi tập trong tuần">
    <div class="list-heading"><h3>Buổi tập trong tuần</h3><span>{{ entries.length }} buổi</span></div>
    <p v-if="!rows.length" class="empty">Tuần này không có buổi tập. Bạn có thể chọn tuần khác để xem lịch.</p>
    <button v-for="{ entry, status, measure, running } in rows" :key="entry.id" type="button" class="session" :class="{ selected: selectedId === entry.id }" :aria-pressed="selectedId === entry.id" @click="emit('select', entry.id)">
      <span class="session-date">{{ longDate(entry.scheduled_date) }}</span>
      <span class="session-main"><span class="icon"><component :is="running ? Footprints : Dumbbell" :size="19" aria-hidden="true" /></span><strong>{{ entry.label }}</strong><ChevronRight class="chevron" :size="16" aria-hidden="true" /></span>
      <span class="session-meta">{{ entry.items.length }} bài<template v-if="measure"> · {{ measure }}</template></span>
      <span class="status" :class="status.tone"><span aria-hidden="true">{{ status.glyph }}</span> {{ status.text }}</span>
    </button>
  </nav>
</template>
<style scoped>
.sessions { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.list-heading { display: flex; justify-content: space-between; align-items: center; padding: 4px 2px 6px; }
h3 { font-size: 14px; font-weight: 700; margin: 0; }
.list-heading > span { font-size: 12px; color: var(--hf-muted); }
.session { display: flex; flex-direction: column; gap: 9px; width: 100%; text-align: left; border: 1px solid var(--hf-line); background: var(--hf-card); border-radius: 16px; padding: 16px; color: var(--hf-ink); }
.session.selected { border-color: var(--hf-acc); box-shadow: inset 3px 0 var(--hf-acc); }
.session:hover:not(.selected) { border-color: var(--hf-muted); }
.session-date { color: var(--hf-muted); font-size: 11px; }
.session-main { display: flex; align-items: center; gap: 10px; width: 100%; }
.session-main strong { font-size: 14px; line-height: 1.5; flex: 1; overflow-wrap: anywhere; }
.icon { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; flex: none; background: var(--hf-fill); }
.chevron { flex: none; color: var(--hf-muted); }
.session-meta { font-size: 12px; color: var(--hf-muted); }
.status { width: fit-content; font-size: 11px; background: var(--hf-fill); border-radius: 7px; padding: 4px 7px; }
.status.done { background: var(--hf-ok-bg); color: var(--hf-ok-text); }
.status.overdue { background: var(--hf-warn-bg); color: var(--hf-warn-text); }
.empty { color: var(--hf-muted); font-size: 14px; line-height: 1.7; background: var(--hf-card); padding: 20px; border-radius: 16px; }
</style>
