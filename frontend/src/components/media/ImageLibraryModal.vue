<script setup lang="ts">
import { computed, onMounted, onUnmounted, shallowRef, useId, useTemplateRef, watch } from 'vue'
import { ImagePlus, LoaderCircle, Trash2, X } from 'lucide-vue-next'
import { useAuth } from '@/composables/useAuth'

type Kind = 'foods' | 'meals' | 'exercises' | 'trainings'
interface RecordItem { id: string; name?: string; name_vi?: string }
interface Cover { entity_id: string; image_url: string | null; version_id: number }
const emit = defineEmits<{ close: [] }>()
const { authFetch } = useAuth()
const kind = shallowRef<Kind>('foods')
const records = shallowRef<RecordItem[]>([])
const selectedId = shallowRef('')
const cover = shallowRef<Cover | null>(null)
const loading = shallowRef(false)
const busy = shallowRef(false)
const error = shallowRef('')
const notice = shallowRef('')
const dialog = useTemplateRef<HTMLDialogElement>('dialog')
const fileInput = useTemplateRef<HTMLInputElement>('fileInput')
const labelId = useId()
const selectedName = computed(() => records.value.find(record => record.id === selectedId.value)?.name_vi
  || records.value.find(record => record.id === selectedId.value)?.name || '')
const kinds: { value: Kind; label: string }[] = [
  { value: 'foods', label: 'Thực phẩm của tôi' }, { value: 'meals', label: 'Bữa ăn' },
  { value: 'exercises', label: 'Bài tập của tôi' }, { value: 'trainings', label: 'Buổi tập' },
]

async function data(response: Response) {
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Không thể xử lý yêu cầu ảnh.')
  return body
}

watch(kind, async (value, _, onCleanup) => {
  let cancelled = false
  onCleanup(() => { cancelled = true })
  loading.value = true
  error.value = ''
  records.value = []
  selectedId.value = ''
  cover.value = null
  try {
    // Fetch all pages so older records remain selectable.
    const all: RecordItem[] = []
    for (let offset = 0; ; offset += 200) {
      const scope = value === 'foods' || value === 'exercises' ? '&source_type=CUSTOM' : ''
      const page = await data(await authFetch(`/api/${value}?limit=200&offset=${offset}${scope}`))
      if (cancelled) return
      if (!Array.isArray(page)) throw new Error('Không thể đọc danh sách dữ liệu.')
      all.push(...page)
      if (page.length < 200) break
    }
    records.value = all
    selectedId.value = all[0]?.id || ''
  } catch (err) {
    if (!cancelled) error.value = err instanceof Error ? err.message : 'Không thể tải danh sách.'
  } finally {
    if (!cancelled) loading.value = false
  }
}, { immediate: true })

watch(selectedId, async (id, _, onCleanup) => {
  let cancelled = false
  onCleanup(() => { cancelled = true })
  cover.value = null
  notice.value = ''
  if (!id) return
  error.value = ''
  try {
    const result = await data(await authFetch(`/api/media/${kind.value}/${id}/image`))
    if (!cancelled) cover.value = result
  } catch (err) {
    if (!cancelled) error.value = err instanceof Error ? err.message : 'Không thể tải ảnh.'
  }
})

async function changeImage(file?: File) {
  if (!cover.value || busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  const endpoint = `/api/media/${kind.value}/${selectedId.value}/image`
  try {
    let response: Response
    if (file) {
      const form = new FormData()
      form.append('file', file)
      form.append('expected_version_id', String(cover.value.version_id))
      response = await authFetch(endpoint, { method: 'PUT', body: form })
    } else {
      response = await authFetch(`${endpoint}?expected_version_id=${cover.value.version_id}`, { method: 'DELETE' })
    }
    if (response.status === 409) {
      cover.value = await data(await authFetch(endpoint))
      throw new Error('Bản ghi vừa thay đổi. Ảnh đã được tải lại; vui lòng thử lại.')
    }
    cover.value = await data(response)
    notice.value = file ? 'Đã lưu ảnh.' : 'Đã gỡ ảnh.'
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Không thể lưu ảnh.'
  } finally {
    busy.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

function chooseFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (file) void changeImage(file)
}
function close() { if (!busy.value) emit('close') }
const previousFocus = document.activeElement as HTMLElement | null
onMounted(() => dialog.value?.showModal())
onUnmounted(() => previousFocus?.focus())
</script>

<template>
  <dialog ref="dialog" :aria-labelledby="labelId" class="image-library" @cancel.prevent="close" @click="event => { if (event.target === dialog) close() }">
    <div class="flex items-center justify-between gap-4">
      <h2 :id="labelId" class="text-lg font-medium">Ảnh của bạn</h2>
      <button type="button" aria-label="Đóng quản lý ảnh" :disabled="busy" class="rounded-lg p-2 hover:bg-white/10" @click="close"><X class="h-5 w-5" /></button>
    </div>
    <p class="mb-5 mt-1 text-xs leading-5 text-outline">Thêm ảnh cho thực phẩm, bữa ăn, bài tập và buổi tập đã lưu.</p>
    <label class="mb-4 block text-xs">Loại dữ liệu
      <select v-model="kind" :disabled="busy" class="mt-2 w-full rounded-lg border border-white/15 bg-[#202020] p-3">
        <option v-for="option in kinds" :key="option.value" :value="option.value">{{ option.label }}</option>
      </select>
    </label>
    <p v-if="loading" role="status" class="py-6 text-sm text-outline">Đang tải danh sách…</p>
    <label v-else-if="records.length" class="block text-xs">Chọn bản ghi
      <select v-model="selectedId" :disabled="busy" class="mt-2 w-full rounded-lg border border-white/15 bg-[#202020] p-3">
        <option v-for="record in records" :key="record.id" :value="record.id">{{ record.name_vi || record.name }}</option>
      </select>
    </label>
    <p v-else class="py-6 text-sm text-outline">Chưa có dữ liệu trong nhóm này. Hãy tạo bản ghi trước khi thêm ảnh.</p>
    <template v-if="cover">
      <div class="my-4 flex h-52 items-center justify-center overflow-hidden rounded-xl border border-white/10 bg-black/20">
        <img v-if="cover.image_url" :src="cover.image_url" :alt="selectedName" class="h-full w-full object-contain" />
        <ImagePlus v-else class="h-10 w-10 text-outline" :stroke-width="1" aria-hidden="true" />
      </div>
      <input ref="fileInput" type="file" accept="image/jpeg,image/png,image/webp" class="hidden" @change="chooseFile" />
      <div class="flex flex-wrap gap-3">
        <button type="button" :disabled="busy" class="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-xs font-medium text-black disabled:opacity-50" @click="fileInput?.click()">
          <LoaderCircle v-if="busy" class="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
          <ImagePlus v-else class="h-4 w-4" aria-hidden="true" />
          {{ busy ? 'Đang xử lý…' : cover.image_url ? 'Thay ảnh' : 'Tải ảnh lên' }}
        </button>
        <button v-if="cover.image_url" type="button" :disabled="busy" class="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs text-error hover:bg-error/10 disabled:opacity-50" @click="changeImage()"><Trash2 class="h-4 w-4" />Gỡ ảnh</button>
      </div>
      <p class="mt-3 text-[11px] text-outline">Ảnh tĩnh JPEG, PNG hoặc WebP.</p>
    </template>
    <p v-if="error" role="alert" class="mt-4 text-xs leading-5 text-error">{{ error }}</p>
    <p v-if="notice" role="status" class="mt-4 text-xs text-emerald-300">{{ notice }}</p>
  </dialog>
</template>

<style scoped>
.image-library { width: min(480px, calc(100vw - 32px)); max-height: calc(100dvh - 40px); overflow-y: auto; margin: auto; padding: 24px; border: 1px solid #ffffff1a; border-radius: 16px; background: #171717; color: #e5e2e1; }
.image-library::backdrop { background: #0009; backdrop-filter: blur(4px); }
</style>
