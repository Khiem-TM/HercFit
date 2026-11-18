<script setup lang="ts">
import { onMounted, onUnmounted, useId, useTemplateRef } from 'vue'
defineProps<{ title: string; description: string; busy: boolean; error?: string; confirmLabel: string }>()
const emit = defineEmits<{ cancel: []; confirm: [] }>()
const dialog = useTemplateRef<HTMLDialogElement>('dialog')
const titleId = useId(), descriptionId = useId()
let previous: HTMLElement | null = null
onMounted(() => { previous = document.activeElement as HTMLElement; dialog.value?.showModal() })
onUnmounted(() => { dialog.value?.close(); if (previous?.isConnected) previous.focus({ preventScroll: true }) })
</script>
<template>
  <dialog ref="dialog" class="plan-dialog" :aria-labelledby="titleId" :aria-describedby="descriptionId"
    @cancel.prevent="!busy && emit('cancel')" @keydown.esc.stop.prevent="!busy && emit('cancel')" @click.self="!busy && emit('cancel')">
    <div class="content">
      <h2 :id="titleId">{{ title }}</h2>
      <p :id="descriptionId">{{ description }}</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="actions">
        <button type="button" class="hf-btn" :disabled="busy" autofocus @click="emit('cancel')">Hủy</button>
        <button type="button" class="hf-btn pri" :disabled="busy" @click="emit('confirm')">{{ busy ? 'Đang lưu…' : error ? 'Thử lại' : confirmLabel }}</button>
      </div>
    </div>
  </dialog>
</template>
<style scoped>
.plan-dialog { margin: auto; padding: 0; border: 1px solid var(--hf-line); border-radius: 24px; width: min(480px, calc(100vw - 32px)); max-height: calc(100dvh - 32px); color: var(--hf-ink); background: var(--hf-card); box-shadow: 0 24px 80px var(--hf-shadow-2); }
.plan-dialog::backdrop { background: var(--hf-scrim); }
.content { padding: 26px; }
h2 { font-size: 22px; line-height: 1.4; margin: 0 0 12px; }
p { font-size: 14px; color: var(--hf-muted); line-height: 1.7; margin: 0 0 20px; }
.error { color: var(--hf-bad); }
.actions { display: flex; gap: 10px; justify-content: flex-end; flex-wrap: wrap; }
.hf-btn { min-height: 44px; }
</style>
