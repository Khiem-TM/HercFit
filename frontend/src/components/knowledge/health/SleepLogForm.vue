<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { MoonStar } from 'lucide-vue-next'
import { useAuth } from '@/composables/useAuth'
import { createHealthApi, HealthApiError } from '@/features/health-integration/api'
import { dashboardTimezone, shiftDay } from '../dashboard/dashboardData'

/** Ghi tay giấc ngủ đêm qua (giờ đi ngủ – giờ thức dậy) khi thiết bị không ghi; ghi thẳng lên Google Health. */
const props = defineProps<{ day: string }>()
const emit = defineEmits<{ saved: [] }>()
const api = createHealthApi((url, init) => useAuth().authFetch(url, init))

const bedtime = shallowRef('23:00')
const wake = shallowRef('06:30')
const busy = shallowRef(false)
const message = shallowRef<string | null>(null)
const failed = shallowRef(false)

// Giờ đi ngủ từ 12:00 trở đi thuộc tối hôm trước; giờ thức dậy thuộc ngày được đánh giá.
const startDay = computed(() => (Number(bedtime.value.slice(0, 2)) >= 12 ? shiftDay(props.day, -1) : props.day))
const valid = computed(() => `${startDay.value}T${bedtime.value}` < `${props.day}T${wake.value}`)

async function save() {
  if (!valid.value || busy.value) return
  busy.value = true
  message.value = null
  try {
    await api.createRecord('sleep', {
      started_at: `${startDay.value}T${bedtime.value}:00+07:00`, ended_at: `${props.day}T${wake.value}:00+07:00`,
      timezone: dashboardTimezone,
    })
    failed.value = false
    message.value = 'Đã ghi giấc ngủ lên Google Health.'
    emit('saved')
  } catch (error) {
    failed.value = true
    message.value = error instanceof HealthApiError ? error.message : 'Chưa ghi được giấc ngủ; hãy thử lại.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <form class="sleep-log" @submit.prevent="save">
    <p class="intro"><MoonStar :size="16" aria-hidden="true" />Thiết bị chưa ghi giấc ngủ đêm qua? Ghi tay giờ ngủ để đánh giá chính xác hơn.</p>
    <div class="fields">
      <div class="hf-field"><label for="sleep-bed">Đi ngủ</label><input id="sleep-bed" v-model="bedtime" class="hf-inp" type="time" required /></div>
      <div class="hf-field"><label for="sleep-wake">Thức dậy</label><input id="sleep-wake" v-model="wake" class="hf-inp" type="time" required /></div>
      <button type="submit" class="hf-btn pri" :disabled="busy || !valid">{{ busy ? 'Đang ghi…' : 'Ghi giấc ngủ' }}</button>
    </div>
    <small v-if="message" :class="{ warn: failed }" role="status">{{ message }}</small>
  </form>
</template>

<style scoped>
.sleep-log { display: flex; flex-direction: column; gap: 10px; }
.intro { display: flex; align-items: flex-start; gap: 8px; margin: 0; font-size: 13px; line-height: 1.5; color: var(--hf-sub); }
.intro svg { flex: none; margin-top: 2px; }
.fields { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 10px; }
.fields .hf-field { width: 130px; }
small { font-size: 12px; color: var(--hf-ok-text); }
small.warn { color: var(--hf-bad); }
</style>
