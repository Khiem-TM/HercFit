<script setup lang="ts">
import { computed } from 'vue'
import { Check, ExternalLink, ImageOff } from 'lucide-vue-next'
import CatalogImage from './CatalogImage.vue'
import { AUTHORITY, fmt, unverifiedText } from '@/features/chat/confirmation'

const props = defineProps<{ candidate: Record<string, any>; disabled?: boolean }>()
/** Research picture to import to Cloudinary after confirmation; null keeps the record without a picture. */
const selected = defineModel<string | null>({ default: null })

const record = computed(() => props.candidate.record || {})
const config = computed(() => record.value.configuration || {})
const isFood = computed(() => props.candidate.domain === 'foods')
const existing = computed(() => props.candidate.resolution === 'reuse' ? props.candidate.existing : null)
const unverified = computed(() => unverifiedText(props.candidate.unverified_fields))
const images = computed(() => (props.candidate.image_candidates || []) as { url: string; description?: string }[])
const hosts = (url: string) => { try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url } }
</script>

<template>
  <div class="px-5 pt-4">
    <div class="flex gap-4">
      <CatalogImage :src="selected" :alt="record.name_vi || 'Ảnh minh hoạ'" :icon="isFood ? 'food' : 'exercise'" class="h-24 w-24 shrink-0" />
      <div class="min-w-0 flex-1">
        <p class="font-headline-md text-xl leading-tight text-primary">{{ record.name_vi }}</p>
        <p v-if="record.name_en" class="text-xs text-on-surface-variant">{{ record.name_en }}</p>
        <dl v-if="isFood" class="mt-2 grid grid-cols-3 gap-x-3 gap-y-1 text-xs">
          <div><dt class="text-on-surface-variant">Khẩu phần</dt><dd class="font-label-code text-primary">{{ fmt(record.serving_size, 1) }} {{ record.serving_unit === 'ML' ? 'ml' : 'g' }}</dd></div>
          <div><dt class="text-on-surface-variant">Năng lượng</dt><dd class="font-label-code text-primary">{{ fmt(record.energy_kcal, 0, 'kcal') }}</dd></div>
          <div><dt class="text-on-surface-variant">Protein</dt><dd class="font-label-code text-primary">{{ fmt(record.protein_g, 1, 'g') }}</dd></div>
          <div><dt class="text-on-surface-variant">Carb</dt><dd class="font-label-code text-primary">{{ fmt(record.carbohydrate_g, 1, 'g') }}</dd></div>
          <div><dt class="text-on-surface-variant">Fat</dt><dd class="font-label-code text-primary">{{ fmt(record.fat_g, 1, 'g') }}</dd></div>
          <div><dt class="text-on-surface-variant">Chất xơ</dt><dd class="font-label-code text-primary">{{ fmt(record.fiber_g, 1, 'g') }}</dd></div>
        </dl>
        <div v-else class="mt-2 space-y-2">
          <div class="flex flex-wrap gap-1.5">
            <span class="rounded bg-[#d4b77d] px-1.5 font-label-code text-[10px] text-[#131313]">{{ record.kind }}</span>
            <span v-for="tag in record.muscle_groups || []" :key="tag" class="rounded border border-white/15 px-1.5 font-label-code text-[10px] text-on-surface-variant">{{ tag }}</span>
          </div>
          <dl class="grid grid-cols-3 gap-x-3 gap-y-1 text-xs">
            <div v-if="config.category"><dt class="text-on-surface-variant">Loại</dt><dd class="text-primary">{{ config.category === 'ISOLATION' ? 'Đơn khớp' : 'Đa khớp' }}</dd></div>
            <div v-if="config.activity"><dt class="text-on-surface-variant">Hoạt động</dt><dd class="font-label-code text-primary">{{ config.activity }}</dd></div>
            <div v-if="config.sport"><dt class="text-on-surface-variant">Môn</dt><dd class="text-primary">{{ config.sport }}</dd></div>
            <div><dt class="text-on-surface-variant">MET</dt><dd class="font-label-code text-primary">{{ fmt(config.default_met, 1) }}</dd></div>
          </dl>
        </div>
      </div>
    </div>

    <p v-if="existing" class="mt-3 rounded-lg border border-[#d4b77d]/30 bg-[#d4b77d]/10 px-3 py-2 text-xs text-primary">
      Catalog đã có “{{ existing.name_vi }}” ({{ existing.source_type === 'SYSTEM' ? 'bản ghi hệ thống' : 'bản ghi của bạn' }}). Xác nhận sẽ dùng bản này, không tạo bản trùng.
    </p>
    <p v-else-if="candidate.resolution === 'create_distinct'" class="mt-3 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-on-surface-variant">
      Biến thể mới, khác các bản gần giống đã có trong catalog.
    </p>
    <p v-if="candidate.estimate" class="mt-3 rounded-lg border border-amber-400/25 bg-amber-400/[0.06] px-3 py-2 text-xs text-on-surface">
      {{ fmt(candidate.estimate.energy_kcal, 0, 'kcal') }} cho 1 suất là ước tính bạn chọn từ {{ hosts(candidate.estimate.url) }}<template v-if="!candidate.estimate.applicable"> (nguồn nói về size hoặc công thức khác)</template>, không phải số liệu chính thức. Bạn có thể sửa sau trong catalog.
    </p>
    <p v-if="unverified" class="mt-2 text-[11px] text-outline">Chưa có nguồn xác nhận nên để trống: {{ unverified }}.</p>

    <fieldset v-if="images.length" class="mt-4" :disabled="disabled">
      <legend class="text-xs text-on-surface-variant">Ảnh minh hoạ tìm được · chọn một ảnh để lưu lên Cloudinary</legend>
      <div class="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-5">
        <button
          v-for="image in images"
          :key="image.url"
          type="button"
          :aria-pressed="selected === image.url"
          :aria-label="`Chọn ảnh từ ${hosts(image.url)}${image.description ? `: ${image.description}` : ''}`"
          class="group relative aspect-square overflow-hidden rounded-lg border-2 transition-colors disabled:opacity-50"
          :class="selected === image.url ? 'border-[#d4b77d]' : 'border-transparent hover:border-white/30'"
          @click="selected = image.url"
        >
          <CatalogImage :src="image.url" :alt="image.description || record.name_vi" rounded="rounded-none" class="h-full w-full" />
          <span v-if="selected === image.url" class="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full bg-[#d4b77d] text-[#131313]" aria-hidden="true">
            <Check class="h-3 w-3" :stroke-width="3" />
          </span>
        </button>
        <button
          type="button"
          :aria-pressed="selected === null"
          class="flex aspect-square flex-col items-center justify-center gap-1 rounded-lg border-2 bg-white/[0.03] text-[11px] text-on-surface-variant disabled:opacity-50"
          :class="selected === null ? 'border-[#d4b77d]' : 'border-transparent hover:border-white/30'"
          @click="selected = null"
        >
          <ImageOff class="h-4 w-4" aria-hidden="true" />Không dùng ảnh
        </button>
      </div>
      <p v-if="selected" class="mt-1.5 text-[11px] text-outline">Nguồn ảnh: {{ hosts(selected) }} · chỉ dùng minh hoạ, không phải căn cứ dinh dưỡng.</p>
    </fieldset>

    <p v-if="candidate.sources?.length" class="mt-3 text-[11px] text-on-surface-variant">
      {{ candidate.research_verified ? 'Nguồn đã đối chiếu trích dẫn' : 'Nguồn số liệu' }}
    </p>
    <ul v-if="candidate.sources?.length" class="mt-1.5 flex flex-wrap gap-1.5" aria-label="Nguồn số liệu">
      <li v-for="source in candidate.sources" :key="source.url">
        <a :href="source.url" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 rounded-md border border-white/10 px-2 py-1 text-[11px] text-on-surface-variant hover:text-primary">
          <ExternalLink class="h-3 w-3" aria-hidden="true" /><span class="max-w-[180px] truncate">{{ source.title || hosts(source.url) }}</span>
          <span v-if="source.authority" class="rounded bg-white/[0.06] px-1 font-label-code text-[9px] uppercase tracking-wide">{{ AUTHORITY[source.authority] || source.authority }}</span>
        </a>
      </li>
    </ul>
  </div>
</template>
