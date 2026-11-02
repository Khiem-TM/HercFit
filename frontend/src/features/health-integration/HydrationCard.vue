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
  <div class="space-y-3 rounded-2xl border border-ink/[0.08] bg-panel p-4 text-xs">
    <div class="flex items-center gap-2">
      <GlassWater class="h-4 w-4 text-primary" />
      <h4 class="text-sm font-medium text-primary">Nước uống</h4>
    </div>
    <p class="text-[11px] text-outline">Ghi thẳng lên Google Health (Google giữ bản gốc). Bạn cũng có thể nói với trợ lý, ví dụ
      “mình vừa uống 500 ml nước”.</p>
    <template v-if="canWrite">
      <div class="flex flex-wrap items-center gap-2 text-on-surface-variant">
        <input v-model.number="amount" type="number" min="10" max="5000" step="50" aria-label="Lượng nước (ml)"
          class="w-24 rounded-lg border border-ink/15 bg-transparent px-2 py-1 text-primary" /> ml
        <button v-for="preset in [250, 500]" :key="preset" type="button"
          class="rounded-lg border border-ink/20 px-2 py-1 text-[11px] text-primary hover:bg-ink/10" @click="amount = preset">
          {{ preset }} ml
        </button>
        <button type="button" :disabled="busy || !(amount > 0)"
          class="rounded-xl bg-ink px-3 py-1.5 font-semibold text-paper hover:bg-ink/90 disabled:opacity-40" @click="save">Ghi</button>
      </div>
      <p v-if="message" :class="message.tone === 'ok' ? 'text-emerald-300' : 'text-error'">{{ message.text }}</p>
    </template>
    <p v-else class="text-[11px] text-amber-300">Chưa cấp quyền ghi dinh dưỡng lên Google Health. Bấm “Cấp thêm quyền” ở trên.</p>
  </div>
</template>
