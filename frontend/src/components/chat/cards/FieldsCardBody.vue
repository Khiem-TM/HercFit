<script setup lang="ts">
import { computed } from 'vue'
import { Info } from 'lucide-vue-next'
import { ACTION_NOTES, fieldRows } from '@/features/chat/confirmation'

/** Thẻ chuẩn cho lệnh ghi không có chạy thử (số đo cơ thể, mục tiêu, hồ sơ, sửa, xoá): các trường có nhãn, không bao giờ là JSON thô. */
const props = defineProps<{ tool: string; payload: Record<string, unknown> }>()

const rows = computed(() => fieldRows(props.payload, props.tool))
const note = computed(() => ACTION_NOTES[props.tool] ?? '')
// Xoá và đổi trạng thái chỉ mang id của bản ghi: một mã tham chiếu ngắn để phân biệt hai bản ghi.
const reference = computed(() => {
  const id = props.payload?.resource_id
  return typeof id === 'string' && id ? `#${id.slice(-6)}` : ''
})
</script>

<template>
  <div class="px-5 pt-4">
    <dl v-if="rows.length" class="divide-y divide-ink/[0.06] rounded-xl border border-ink/[0.06] bg-sunken" aria-label="Thông tin sẽ lưu">
      <div v-for="row in rows" :key="row.label" class="flex flex-col gap-0.5 px-3.5 py-2.5 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
        <dt class="shrink-0 text-xs text-on-surface-variant">{{ row.label }}</dt>
        <dd class="min-w-0 break-words text-sm text-primary sm:text-right">{{ row.value }}</dd>
      </div>
    </dl>
    <p v-if="note || reference || !rows.length" class="mt-3 flex gap-2 rounded-lg border border-mist/25 bg-mist/[0.06] px-3 py-2.5 text-xs leading-5 text-on-surface-variant">
      <Info class="mt-0.5 h-4 w-4 shrink-0 text-mist" aria-hidden="true" />
      <span>
        {{ note || 'Kiểm tra thông tin trước khi lưu.' }}
        <span v-if="reference" class="font-label-code text-primary">Bản ghi {{ reference }}</span>
      </span>
    </p>
  </div>
</template>
