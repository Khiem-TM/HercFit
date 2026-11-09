<script setup lang="ts">
import { AnimatePresence, motion } from 'motion-v'
import { presence, toast } from '@/motion'

/** Toast dùng chung: trượt lên khi hiện, trượt xuống khi ẩn; có thể kèm một nút hành động. */
defineProps<{ message: string; action?: string }>()
const emit = defineEmits<{ action: [] }>()
</script>

<template>
  <Teleport to="body">
    <div class="hf hf-toast-wrap">
      <AnimatePresence>
        <motion.div v-if="message" :key="message" class="hf-toast" role="status" aria-live="polite" v-bind="presence(toast)">
          <span class="text">{{ message }}</span>
          <button v-if="action" type="button" class="act" @click.stop="emit('action')">{{ action }}</button>
        </motion.div>
      </AnimatePresence>
    </div>
  </Teleport>
</template>

<style scoped>
.text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.act {
  flex: none; border: 0; border-radius: 999px; padding: 6px 12px; font: inherit; font-size: 13px; font-weight: 600;
  background: #fff; color: #141416; cursor: pointer;
  transition: background-color var(--hf-dur-fast) var(--hf-ease-out), transform var(--hf-dur-instant) var(--hf-ease-out);
}
.act:hover { background: #E4E4E7; }
.act:active { transform: scale(.97); }
</style>
