<script setup lang="ts">
import { onUnmounted, shallowRef, useId, useTemplateRef, watch } from 'vue'
import { Camera, X } from 'lucide-vue-next'

const props = defineProps<{ label: string; disabled?: boolean }>()
const model = defineModel<File | null>({ default: null })

// Mirrors the server limits (core/settings IMAGE_MAX_BYTES, prepare_image formats).
const MAX_BYTES = 5 * 1024 * 1024
const TYPES = ['image/jpeg', 'image/png', 'image/webp']
const input = useTemplateRef<HTMLInputElement>('input')
const preview = shallowRef<string | null>(null)
const error = shallowRef('')
const hintId = useId()

watch(model, (file) => {
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = file ? URL.createObjectURL(file) : null
})
onUnmounted(() => { if (preview.value) URL.revokeObjectURL(preview.value) })

function choose(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  error.value = ''
  if (!file) return
  if (!TYPES.includes(file.type)) error.value = 'Chỉ nhận ảnh JPEG, PNG hoặc WebP.'
  else if (file.size > MAX_BYTES) error.value = 'Ảnh lớn hơn 5 MB.'
  else model.value = file
  if (input.value) input.value.value = ''
}
</script>

<template>
  <div class="rounded-xl border border-dashed border-white/15 bg-white/[0.02] p-3">
    <div class="flex items-center gap-3">
      <div v-if="preview" class="relative h-16 w-16 shrink-0 overflow-hidden rounded-lg">
        <img :src="preview" :alt="`Ảnh đính kèm: ${model?.name}`" class="h-full w-full object-cover" />
      </div>
      <div class="min-w-0 flex-1">
        <p class="text-xs font-medium text-primary">{{ props.label }}</p>
        <p :id="hintId" class="mt-0.5 text-[11px] leading-4 text-on-surface-variant">
          {{ model ? model.name : 'Tuỳ chọn · JPEG/PNG/WebP ≤ 5 MB · lưu lên Cloudinary sau khi xác nhận' }}
        </p>
      </div>
      <input ref="input" type="file" accept="image/jpeg,image/png,image/webp" class="sr-only" tabindex="-1" @change="choose" />
      <button
        v-if="!model"
        type="button"
        :disabled="disabled"
        :aria-describedby="hintId"
        class="inline-flex min-h-[40px] items-center gap-1.5 rounded-lg border border-white/15 px-3 text-xs text-primary hover:bg-white/[0.06] disabled:opacity-50"
        @click="input?.click()"
      >
        <Camera class="h-4 w-4" aria-hidden="true" />Thêm ảnh
      </button>
      <button
        v-else
        type="button"
        :disabled="disabled"
        aria-label="Bỏ ảnh đính kèm"
        class="inline-flex h-10 w-10 items-center justify-center rounded-lg text-on-surface-variant hover:bg-white/[0.06] disabled:opacity-50"
        @click="model = null"
      >
        <X class="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
    <p v-if="error" role="alert" class="mt-2 text-[11px] text-error">{{ error }}</p>
  </div>
</template>
