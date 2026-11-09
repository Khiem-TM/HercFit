<script setup lang="ts">
import { ref } from 'vue'
import { GlassWater } from 'lucide-vue-next'
import type { HealthApi } from './api'

const props = defineProps<{ api: HealthApi; canWrite: boolean }>()
const emit = defineEmits<{ saved: [] }>()

const amount = ref(250)
const busy = ref(false)
const message = ref<{ tone: 'ok' | 'error'; text: string } | null>(null)
// Bấm lại sau lỗi mạng gửi cùng khoá: backend trả lại kết quả cũ thay vì ghi hai lần.
let pendingWrite: { amount: number; key: string } | null = null

async function save(): Promise<void> {
  if (busy.value || !(amount.value > 0)) return
  busy.value = true
  message.value = null
  try {
    if (pendingWrite?.amount !== amount.value) pendingWrite = { amount: amount.value, key: crypto.randomUUID() }
    const saved = await props.api.createRecord('hydration', {
      amount_ml: amount.value, consumed_at: new Date().toISOString(), timezone: 'Asia/Ho_Chi_Minh',
    }, pendingWrite.key)
    pendingWrite = null
    message.value = { tone: 'ok', text: saved.pending
      ? `Google đã nhận ${amount.value} ml; số liệu hiện ở lần đồng bộ tới.`
      : `Đã ghi ${amount.value} ml lên Google Health.` }
    emit('saved')
  } catch (err) {
    message.value = { tone: 'error', text: err instanceof Error ? err.message : 'Không ghi được.' }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="water">
    <p class="hf-mut intro">Ghi thẳng lên Google Health (Google giữ bản gốc). Bạn cũng có thể nói với trợ lý, ví dụ “mình vừa uống 500 ml nước”.</p>
    <template v-if="canWrite">
      <div class="row">
        <label class="hf-sr" for="water-ml">Lượng nước (ml)</label>
        <input id="water-ml" v-model.number="amount" class="hf-inp amount" type="number" min="10" max="5000" step="50" />
        <span class="hf-mut">ml</span>
        <button v-for="preset in [250, 500]" :key="preset" type="button" class="hf-tog" @click="amount = preset">{{ preset }} ml</button>
        <button type="button" class="hf-btn pri" :disabled="busy || !(amount > 0)" @click="save">Ghi</button>
      </div>
      <p v-if="message" class="msg" :class="message.tone" role="status">{{ message.text }}</p>
    </template>
    <p v-else class="hf-warn">Chưa cấp quyền ghi dinh dưỡng lên Google Health. Bấm “Cấp thêm quyền” ở trên.</p>
  </div>
</template>

<style scoped>
.water { display: flex; flex-direction: column; gap: 10px; }
.intro { margin: 0; font-size: 13px; line-height: 1.5; }
.row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.amount { width: 110px; }
.msg { margin: 0; font-size: 13px; }
.msg.ok { color: var(--hf-ok-text); }
.msg.error { color: var(--hf-bad); }
</style>
