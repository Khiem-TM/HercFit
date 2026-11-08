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
    <p><MoonStar :size="12" /> Thiết bị chưa ghi giấc ngủ đêm qua? Ghi tay giờ ngủ để đánh giá chính xác hơn.</p>
    <div class="fields">
      <label>Đi ngủ <input v-model="bedtime" type="time" required /></label>
      <label>Thức dậy <input v-model="wake" type="time" required /></label>
      <button type="submit" :disabled="busy || !valid">{{ busy ? 'Đang ghi…' : 'Ghi giấc ngủ' }}</button>
    </div>
    <small v-if="message" :class="{ warn: failed }">{{ message }}</small>
  </form>
</template>

<style scoped>
.sleep-log { display: flex; flex-direction: column; gap: 8px; margin-top: 14px; padding: 12px; border: 1px dashed light-dark(#36768940, #8fc3d440); border-radius: 12px; }
.sleep-log p { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 10.5px; color: light-dark(#53575d, #a3a8ae); }
.fields { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 10px; }
label { display: flex; flex-direction: column; gap: 3px; font-size: 10px; color: light-dark(#60676e, #8d949c); }
input { padding: 5px 8px; border: 1px solid light-dark(#18181822, #ffffff22); border-radius: 8px; background: transparent; color: inherit; font: 12px Geist, sans-serif; }
button { padding: 6px 12px; border-radius: 8px; background: light-dark(#367689, #8fc3d4); color: light-dark(#fdfcf9, #14171d); font-size: 11px; }
button:disabled { opacity: .5; }
small { font-size: 10px; color: light-dark(#417e58, #9fd3b0); }
small.warn { color: light-dark(#8f6817, #e8c07d); }
</style>
