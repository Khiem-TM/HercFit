<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { AlertTriangle, CloudUpload, Loader2 } from 'lucide-vue-next'
import type { ExportConflict, ExportSwitch, ScopeBundle } from '@/types/api'
import { type HealthApi, waitForOperation, OPERATION_TEXT } from './api'

const props = defineProps<{ api: HealthApi }>()

const sync = ref<ExportSwitch | null>(null)
const bundles = ref<ScopeBundle[]>([])
const conflicts = ref<ExportConflict[]>([])
const busy = ref(false)
const error = ref<string | null>(null)
const note = ref<string | null>(null)
const controller = new AbortController()
onUnmounted(() => controller.abort())

const on = computed(() => !!sync.value?.enabled)
const missing = computed(() => {
  const keys = new Set(sync.value?.missing_bundles ?? [])
  return bundles.value.filter(bundle => keys.has(bundle.key))
})
const summary = computed(() => {
  const state = sync.value
  if (!state) return ''
  const parts = [`Đã gửi ${state.sent} bản ghi`]
  if (state.pending) parts.push(`đang chờ ${state.pending}`)
  if (state.last_sent_at) parts.push(`gần nhất ${new Date(state.last_sent_at).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' })}`)
  return parts.join(' · ')
})

async function load(): Promise<void> {
  error.value = null
  try {
    const [state, scopes, open] = await Promise.all([props.api.exportSwitch(), props.api.scopes(), props.api.conflicts()])
    sync.value = state
    bundles.value = scopes.bundles
    conflicts.value = open
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Không tải được cài đặt đồng bộ.'
  }
}

async function guarded(action: () => Promise<void>): Promise<void> {
  busy.value = true
  error.value = null
  try {
    await action()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Thao tác không thành công.'
  } finally {
    busy.value = false
  }
}

/** Công tắc duy nhất: bật thì xin Google một lần mọi thứ còn thiếu (nếu có), rồi gửi lịch sử và các thay đổi. */
function setSync(enabled: boolean): Promise<void> {
  return guarded(async () => {
    const state = await props.api.setExportSwitch(enabled)
    if (state.authorization_url) {
      window.location.assign(state.authorization_url)
      return
    }
    sync.value = state
    note.value = enabled ? 'Đang gửi dữ liệu hiện có lên Google Health…' : 'Đã dừng đồng bộ lên Google. Dữ liệu đã gửi vẫn ở trên Google.'
    if (enabled && state.operation_id) {
      void waitForOperation(props.api, state.operation_id, async op => {
        note.value = `Gửi dữ liệu hiện có: ${OPERATION_TEXT[op.state]}`
        sync.value = await props.api.exportSwitch().catch(() => sync.value)
      }, { signal: controller.signal }).catch(() => {
        if (!controller.signal.aborted) note.value = 'Chưa đọc được tiến độ. Dữ liệu vẫn được xử lý trong nền.'
      })
    }
  })
}

function resolve(conflict: ExportConflict, resolution: 'KEEP_LOCAL' | 'ACCEPT_REMOTE'): Promise<void> {
  return guarded(async () => {
    await props.api.resolveConflict(conflict.id, resolution)
    conflicts.value = conflicts.value.filter(item => item.id !== conflict.id)
  })
}

function setGroup(group: string, enabled: boolean): Promise<void> {
  return guarded(async () => {
    await props.api.setExportGroup(group, enabled)
    await load()
    note.value = enabled ? 'Nhóm này sẽ tự gửi các thay đổi mới lên Google Health.' : 'Đã dừng gửi nhóm này.'
  })
}

function brief(payload: Record<string, unknown> | null): string {
  if (!payload) return '—'
  const value = Object.entries(payload).find(([key]) => key !== 'dataSource' && key !== 'name')?.[1]
  return JSON.stringify(value ?? payload).slice(0, 140)
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <div class="space-y-3 rounded-2xl border border-ink/[0.08] bg-panel p-4 text-xs">
    <div class="flex items-start gap-3">
      <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-ink/10 bg-ink/5">
        <CloudUpload class="h-4 w-4 text-primary" />
      </div>
      <div class="min-w-0 flex-1">
        <h4 class="text-sm font-medium text-primary">Đồng bộ lên Google Health</h4>
        <p class="mt-0.5 leading-relaxed text-outline">
          {{ on
            ? 'Cân nặng, bữa ăn, buổi tập, nước uống và nhật ký bạn ghi ở HercFit được tự động gửi lên Google Health.'
            : 'Bật một lần: HercFit xin mọi quyền Google còn thiếu trên một màn hình, gửi dữ liệu bạn đã ghi và tự gửi mọi thay đổi sau này.' }}
        </p>
      </div>
      <Loader2 v-if="busy" class="mt-1 h-3.5 w-3.5 animate-spin text-outline" />
      <button
        type="button" role="switch" :aria-checked="on" aria-label="Đồng bộ lên Google Health"
        :disabled="busy || !sync?.available"
        class="relative mt-0.5 h-6 w-11 shrink-0 rounded-full border transition-colors disabled:opacity-40"
        :class="on ? 'border-emerald-400/50 bg-emerald-400/30' : 'border-ink/20 bg-ink/10'"
        @click="setSync(!on)"
      >
        <span
          class="absolute top-0.5 h-[18px] w-[18px] rounded-full bg-ink shadow transition-[left] duration-200"
          :class="on ? 'left-[22px]' : 'left-0.5'"
        />
      </button>
    </div>

    <p v-if="error" class="rounded-xl border border-error/40 bg-error/10 px-3 py-2 text-error">{{ error }}</p>
    <p v-if="sync && !sync.available" class="text-outline">Máy chủ chưa mở chức năng đồng bộ lên Google.</p>

    <template v-if="sync?.available">
      <p v-if="sync.partial" class="text-amber-300">Đang bật một phần. Bật công tắc để đồng bộ toàn bộ.</p>
      <div v-if="on || sync.partial" class="space-y-2 rounded-xl border border-ink/[0.06] px-3 py-2.5">
        <p class="text-on-surface-variant">{{ summary }}</p>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="group in sync.groups" :key="group.group"
            type="button" role="switch" :aria-checked="group.enabled" :aria-label="`Đồng bộ ${group.label}`"
            :disabled="busy || !group.write_scope_granted"
            class="rounded-full px-2 py-0.5 text-[10.5px] disabled:opacity-40"
            :class="group.enabled ? 'bg-emerald-400/15 text-emerald-300' : 'bg-ink/10 text-outline'"
            :title="group.write_scope_granted ? '' : 'Chưa có quyền ghi'"
            @click="setGroup(group.group, !group.enabled)"
          >{{ group.enabled ? '✓' : '·' }} {{ group.label }}</button>
        </div>
        <p v-if="sync.attention" class="flex items-center gap-1 text-amber-300">
          <AlertTriangle class="h-3 w-3" />{{ sync.attention }} bản ghi chưa gửi được, xem xung đột bên dưới nếu có.
        </p>
      </div>
      <div v-if="on && missing.length" class="flex flex-wrap items-center gap-2 text-outline">
        <span>Còn thiếu quyền: {{ missing.map(bundle => bundle.label).join(', ') }}.</span>
        <button type="button" :disabled="busy" class="rounded-lg border border-ink/20 px-2 py-1 text-primary hover:bg-ink/10 disabled:opacity-40" @click="setSync(true)">Cấp nốt</button>
      </div>
      <p class="text-[11px] text-outline">Tắt chỉ dừng gửi. Dữ liệu đã có trên Google được giữ nguyên, việc đọc từ Google vẫn tiếp tục.</p>
      <p v-if="note" class="text-[11px] text-outline" role="status">{{ note }}</p>
    </template>

    <div v-if="conflicts.length" class="space-y-1.5">
      <p class="flex items-center gap-1 font-label-code text-[10px] text-amber-300"><AlertTriangle class="h-3 w-3" />
        XUNG ĐỘT CẦN BẠN CHỌN</p>
      <div v-for="conflict in conflicts" :key="conflict.id" class="space-y-1 rounded-xl border border-amber-400/25 bg-amber-400/[0.05] p-2">
        <p class="text-on-surface-variant">{{ conflict.data_type }} đã được sửa ở ứng dụng khác.</p>
        <p class="text-[11px] text-outline">HercFit: {{ brief(conflict.local_payload) }}</p>
        <p class="text-[11px] text-outline">Google: {{ brief(conflict.remote_payload) }}</p>
        <div class="flex gap-2">
          <button type="button" :disabled="busy" class="rounded-lg border border-ink/20 px-2 py-1 text-[11px] text-primary hover:bg-ink/10" @click="resolve(conflict, 'KEEP_LOCAL')">Giữ bản HercFit</button>
          <button type="button" :disabled="busy" class="rounded-lg border border-ink/20 px-2 py-1 text-[11px] text-primary hover:bg-ink/10" @click="resolve(conflict, 'ACCEPT_REMOTE')">Nhận bản Google</button>
        </div>
      </div>
    </div>
  </div>
</template>
