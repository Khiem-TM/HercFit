import { computed, shallowRef, watch } from 'vue'
import type { TrainingPlan } from './model'
import { currentWeekIndex, planWeeks, preferredSession } from './weeks'

export function usePlanBrowser(getPlan: () => TrainingPlan | null, getToday: () => string) {
  const index = shallowRef(0)
  const selectedId = shallowRef<string | null>(null)
  const selectedDate = shallowRef('')
  const weeks = computed(() => getPlan() ? planWeeks(getPlan()!, getToday()) : [])
  const week = computed(() => weeks.value[index.value])
  const entry = computed(() => week.value?.sessions.find(e => e.id === selectedId.value) ?? null)
  const day = computed(() => week.value?.days.find(d => d.date === selectedDate.value))
  const currentIndex = computed(() => currentWeekIndex(weeks.value, getToday()))
  function resetSelection() {
    const w = week.value
    const e = w ? preferredSession(w, getToday()) : null
    selectedId.value = e?.id ?? null
    selectedDate.value = e?.scheduled_date ?? w?.days.find(d => !d.outside)?.date ?? ''
  }
  function selectWeek(next: number) {
    index.value = Math.max(0, Math.min(weeks.value.length - 1, next))
    resetSelection()
  }
  function selectSession(id: string) {
    const e = week.value?.sessions.find(e => e.id === id)
    if (e) { selectedId.value = e.id; selectedDate.value = e.scheduled_date }
  }
  function selectDay(date: string) {
    const d = week.value?.days.find(d => d.date === date)
    if (!d || d.outside) return
    selectedDate.value = date
    selectedId.value = d.sessions[0]?.id ?? null
  }
  watch([getPlan, getToday], ([plan], previous) => {
    if (plan?.id !== previous?.[0]?.id) selectWeek(currentIndex.value)
    else {
      index.value = Math.min(index.value, Math.max(0, weeks.value.length - 1))
      if (selectedId.value ? !entry.value : !day.value || day.value.outside) resetSelection()
      else if (entry.value) selectedDate.value = entry.value.scheduled_date
    }
  }, { immediate: true })
  return { index, selectedId, selectedDate, weeks, week, entry, day, currentIndex, selectWeek, selectSession, selectDay }
}
