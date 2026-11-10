<script setup lang="ts">
import { computed, onMounted, reactive, shallowRef } from 'vue'
import { useDebounceFn } from '@vueuse/core'
import { Check, Lightbulb, Loader2, Search, SearchX } from 'lucide-vue-next'
import type { FoodChoice, FoodGap, FoodGapItem, FoodRecord } from '@/types/api'
import { useAuth } from '@/composables/useAuth'
import CatalogImage from '@/components/chat/cards/CatalogImage.vue'
import PhotoAttachment from '@/components/chat/cards/PhotoAttachment.vue'
import {
  type CustomFoodForm, type FoodGapApi, type FoodPick, LIMITS, choices, createFoodGapApi, customFoodError,
  customFoodPayload, draftQuantity, emptyCustomForm, energyLabel, householdPortion, pickText, summary, unitFor,
  validQuantity,
} from '@/features/chat/foodGap'

const props = defineProps<{ gap: FoodGap; disabled?: boolean; api?: FoodGapApi }>()
const emit = defineEmits<{ (e: 'resolve', choices: FoodChoice[], text: string): void }>()

const api = props.api ?? createFoodGapApi(useAuth().authFetch)

interface ItemState {
  tab: 'search' | 'custom'
  query: string
  results: FoodRecord[]
  searching: boolean
  searchError: string
  /** Bản ghi đang chọn trong kết quả tìm và lượng đã ăn của nó. */
  selected: FoodRecord | null
  quantity: number | null
  form: CustomFoodForm
  photo: File | null
  suggesting: boolean
  suggested: boolean
  saving: boolean
  error: string
  note: string
  seq: number
}

const state = reactive<Record<string, ItemState>>(Object.fromEntries(props.gap.items.map((item) => [item.key, {
  tab: 'search', query: item.query, results: [], searching: Boolean(item.query.trim()), searchError: '', selected: null, quantity: null,
  form: emptyCustomForm(item.query, item), photo: null, suggesting: false, suggested: false, saving: false, error: '',
  note: '', seq: 0,
} satisfies ItemState])))
const picks = reactive<Record<string, FoodPick>>({})
const attempted = shallowRef<Record<string, boolean>>({})

const done = computed(() => props.gap.items.filter((item) => picks[item.key]).length)
const complete = computed(() => done.value === props.gap.items.length)
const meal = computed(() => {
  const at = props.gap.meal?.consumed_at ? new Date(props.gap.meal.consumed_at) : null
  const time = at && !Number.isNaN(at.getTime())
    ? at.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Ho_Chi_Minh' }) : ''
  return [props.gap.meal?.name, time].filter(Boolean).join(' · ')
})

async function search(item: FoodGapItem): Promise<void> {
  const current = state[item.key]
  const query = current.query.trim()
  const seq = ++current.seq
  current.searchError = ''
  if (!query) {
    current.results = []
    return
  }
  current.searching = true
  try {
    const rows = await api.search(query)
    if (seq === current.seq) current.results = rows
  } catch (err) {
    if (seq === current.seq) {
      current.results = []
      current.searchError = err instanceof Error ? err.message : 'Không tìm được món trong danh mục.'
    }
  } finally {
    if (seq === current.seq) current.searching = false
  }
}
const searchSoon = useDebounceFn((item: FoodGapItem) => search(item), 300)

onMounted(() => props.gap.items.forEach((item) => search(item)))

function select(item: FoodGapItem, food: FoodRecord): void {
  const current = state[item.key]
  current.selected = food
  // Người dùng chưa nói lượng: điền sẵn một khẩu phần hộ gia đình của món (vẫn sửa được), nếu món có.
  current.quantity = draftQuantity(item, food) ?? householdPortion(food)?.quantity ?? null
}

function usePick(item: FoodGapItem): void {
  const current = state[item.key]
  if (!current.selected || !validQuantity(current.quantity)) return
  const { unit, label } = unitFor(current.selected)
  picks[item.key] = { key: item.key, food_id: current.selected.id, quantity: current.quantity, unit, label,
                      name: current.selected.name_vi, custom: current.selected.source_type === 'CUSTOM' }
}

async function suggest(item: FoodGapItem): Promise<void> {
  const current = state[item.key]
  if (!current.form.name.trim()) {
    current.error = 'Nhập tên món trước khi xin gợi ý.'
    return
  }
  current.suggesting = true
  current.error = ''
  current.note = ''
  try {
    const facts = await api.suggest(current.form.name)
    Object.assign(current.form, facts)
    current.suggested = true
    current.note = 'Số liệu gợi ý từ nguồn web, tính trên 100 g. Bạn kiểm tra lại trước khi lưu.'
  } catch (err) {
    current.error = err instanceof Error ? err.message : 'Chưa gợi ý được số liệu; bạn nhập giúp nhé.'
  } finally {
    current.suggesting = false
  }
}

async function saveCustom(item: FoodGapItem): Promise<void> {
  const current = state[item.key]
  attempted.value = { ...attempted.value, [item.key]: true }
  const problem = customFoodError(current.form)
  current.error = problem ?? ''
  if (problem) return
  current.saving = true
  try {
    const food = await api.create(customFoodPayload(current.form, current.suggested))
    current.note = ''
    if (current.photo) {
      try {
        await api.uploadImage(food, current.photo)
      } catch (err) {
        // Món đã được lưu; chỉ ảnh bị lỗi.
        current.note = `Đã lưu món, nhưng chưa lưu được ảnh: ${err instanceof Error ? err.message : 'lỗi không xác định'}.`
      }
    }
    picks[item.key] = { key: item.key, food_id: food.id, quantity: current.form.grams as number, unit: 'G', label: 'g',
                        name: food.name_vi, custom: true }
  } catch (err) {
    current.error = err instanceof Error ? err.message : 'Không lưu được món riêng.'
  } finally {
    current.saving = false
  }
}

function change(item: FoodGapItem): void {
  delete picks[item.key]
}

function send(): void {
  if (!complete.value || props.disabled) return
  emit('resolve', choices(picks), summary(props.gap.items, picks))
}

const fields = [
  { key: 'energy_kcal', label: 'Năng lượng', unit: 'kcal', max: LIMITS.kcal, step: 1 },
  { key: 'carbohydrate_g', label: 'Carb', unit: 'g', max: LIMITS.macro, step: 0.1 },
  { key: 'fat_g', label: 'Chất béo', unit: 'g', max: LIMITS.macro, step: 0.1 },
  { key: 'protein_g', label: 'Protein', unit: 'g', max: LIMITS.macro, step: 0.1 },
] as const
</script>

<template>
  <section class="hf fgap" aria-label="Chọn món cho bữa ăn">
    <div class="eyebrow">
      <span class="ic"><SearchX :size="14" :stroke-width="2.2" aria-hidden="true" /></span>
      Món chưa có trong danh mục<span v-if="meal" class="meal">· {{ meal }}</span>
    </div>

    <article v-for="item in gap.items" :key="item.key" class="item">
      <header class="ihead">
        <b>“{{ item.query }}”</b>
        <span v-if="picks[item.key]" class="hf-chip"><Check :size="12" :stroke-width="3" aria-hidden="true" />Đã chọn</span>
      </header>

      <div v-if="picks[item.key]" class="picked">
        <span>{{ pickText(picks[item.key]) }}</span>
        <button type="button" class="hf-lnk" :disabled="disabled" @click="change(item)">Đổi</button>
      </div>

      <template v-else>
        <div class="hf-seg soft tabs" role="group" :aria-label="`Cách chọn món cho ${item.query}`">
          <button type="button" :aria-pressed="state[item.key].tab === 'search'" :disabled="disabled"
                  @click="state[item.key].tab = 'search'">Tìm trong danh mục</button>
          <button type="button" :aria-pressed="state[item.key].tab === 'custom'" :disabled="disabled"
                  @click="state[item.key].tab = 'custom'">Tạo món riêng</button>
        </div>

        <!-- Tìm trong danh mục: backend tìm không dấu và xếp hạng có dấu, gồm cả món riêng của bạn -->
        <div v-if="state[item.key].tab === 'search'" class="pane">
          <label class="search">
            <Search :size="16" aria-hidden="true" />
            <input v-model="state[item.key].query" class="hf-inp" type="search" maxlength="80" :disabled="disabled"
                   :aria-label="`Tìm món thay cho ${item.query}`" placeholder="Nhập tên món…" @input="searchSoon(item)" />
          </label>
          <p v-if="state[item.key].searching" class="hint" aria-live="polite">
            <Loader2 :size="14" class="hf-spin" aria-hidden="true" />Đang tìm…
          </p>
          <p v-else-if="state[item.key].searchError" class="hf-warn" role="alert">{{ state[item.key].searchError }}</p>
          <p v-else-if="!state[item.key].results.length" class="hint">
            Không thấy món phù hợp. Thử tên khác hoặc tạo món riêng.
          </p>
          <ul v-else class="results">
            <li v-for="food in state[item.key].results" :key="food.id">
              <button type="button" class="res" :aria-pressed="state[item.key].selected?.id === food.id" :disabled="disabled"
                      @click="select(item, food)">
                <CatalogImage :src="food.image_url" :alt="food.name_vi" icon="food" rounded="rounded-lg" class="thumb" />
                <span class="rtext">
                  <span class="rname">{{ food.name_vi }}</span>
                  <small>{{ energyLabel(food) }}<template v-if="food.source_type === 'CUSTOM'"> · Món của bạn</template></small>
                </span>
                <Check v-if="state[item.key].selected?.id === food.id" :size="16" :stroke-width="3" aria-hidden="true" />
              </button>
            </li>
          </ul>
          <div v-if="state[item.key].selected" class="qty">
            <div class="hf-field">
              <label :for="`q-${item.key}`">Lượng đã ăn ({{ unitFor(state[item.key].selected!).label }})<template
                v-if="householdPortion(state[item.key].selected!)"> · {{ householdPortion(state[item.key].selected!)!.label }} ≈
                {{ householdPortion(state[item.key].selected!)!.quantity }} {{ unitFor(state[item.key].selected!).label }}</template></label>
              <input :id="`q-${item.key}`" v-model.number="state[item.key].quantity" class="hf-inp" type="number"
                     inputmode="decimal" min="0" :max="LIMITS.quantity" :step="unitFor(state[item.key].selected!).step"
                     :aria-invalid="state[item.key].quantity !== null && !validQuantity(state[item.key].quantity)"
                     :disabled="disabled" />
            </div>
            <button type="button" class="hf-btn pri sm" :disabled="disabled || !validQuantity(state[item.key].quantity)"
                    @click="usePick(item)">Dùng món này</button>
          </div>
        </div>

        <!-- Tạo món riêng: lưu vào danh mục của bạn, dinh dưỡng tính trên 100 g -->
        <div v-else class="pane">
          <div class="hf-field">
            <label :for="`n-${item.key}`">Tên món</label>
            <div class="name">
              <input :id="`n-${item.key}`" v-model="state[item.key].form.name" class="hf-inp" :maxlength="LIMITS.name"
                     :disabled="disabled || state[item.key].saving" />
              <button type="button" class="hf-btn sm bulb" :disabled="disabled || state[item.key].suggesting || state[item.key].saving"
                      aria-label="Gợi ý dinh dưỡng bằng AI" title="Gợi ý dinh dưỡng bằng AI" @click="suggest(item)">
                <Loader2 v-if="state[item.key].suggesting" :size="16" class="hf-spin" aria-hidden="true" />
                <Lightbulb v-else :size="16" aria-hidden="true" />
                <span>Gợi ý</span>
              </button>
            </div>
          </div>
          <p class="hint">Dinh dưỡng trên 100 g</p>
          <div class="macros">
            <div v-for="field in fields" :key="field.key" class="hf-field">
              <label :for="`${field.key}-${item.key}`">{{ field.label }} ({{ field.unit }})</label>
              <input :id="`${field.key}-${item.key}`" v-model.number="state[item.key].form[field.key]" class="hf-inp"
                     type="number" inputmode="decimal" min="0" :max="field.max" :step="field.step"
                     :disabled="disabled || state[item.key].saving" />
            </div>
          </div>
          <div class="hf-field">
            <label :for="`g-${item.key}`">Đã ăn (g)</label>
            <input :id="`g-${item.key}`" v-model.number="state[item.key].form.grams" class="hf-inp" type="number"
                   inputmode="decimal" min="0" :max="LIMITS.quantity" step="10"
                   :aria-invalid="attempted[item.key] && !validQuantity(state[item.key].form.grams)"
                   :disabled="disabled || state[item.key].saving" />
          </div>
          <PhotoAttachment v-model="state[item.key].photo" label="Ảnh món ăn" hint="Tuỳ chọn · JPEG/PNG/WebP ≤ 5 MB · lưu lên Cloudinary cùng món"
                           :disabled="disabled || state[item.key].saving" />
          <p v-if="state[item.key].note" class="hf-info">{{ state[item.key].note }}</p>
          <p v-if="state[item.key].error" class="hf-warn" role="alert">{{ state[item.key].error }}</p>
          <div class="hf-acts end">
            <button type="button" class="hf-btn pri sm" :disabled="disabled || state[item.key].saving" @click="saveCustom(item)">
              <Loader2 v-if="state[item.key].saving" :size="14" class="hf-spin" aria-hidden="true" />Lưu món
            </button>
          </div>
        </div>
      </template>
      <p v-if="picks[item.key] && state[item.key].note" class="hf-info">{{ state[item.key].note }}</p>
    </article>

    <div class="foot">
      <span class="hint" aria-live="polite">{{ done }}/{{ gap.items.length }} món đã chọn</span>
      <button type="button" class="hf-btn pri" :disabled="disabled || !complete" @click="send">Tiếp tục ghi bữa</button>
    </div>
  </section>
</template>

<style scoped>
.fgap {
  background: var(--hf-card); border: 1px solid var(--hf-line); border-radius: 22px; padding: 18px;
  display: flex; flex-direction: column; gap: 14px; box-shadow: 0 6px 20px rgba(0, 0, 0, .05);
}
.eyebrow { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; font-weight: 600; color: var(--hf-muted); }
.meal { font-weight: 500; }
.ic { width: 26px; height: 26px; border-radius: 8px; background: var(--hf-fill); display: inline-flex; align-items: center; justify-content: center; color: var(--hf-ink); }
.item { display: flex; flex-direction: column; gap: 10px; padding-top: 12px; border-top: 1px solid var(--hf-line-2); }
.item:first-of-type { border-top: 0; padding-top: 0; }
.ihead { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 15px; }
.ihead .hf-chip { display: inline-flex; align-items: center; gap: 4px; }
.picked { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: 14px; color: var(--hf-sub); }
.tabs { align-self: flex-start; }
.pane { display: flex; flex-direction: column; gap: 10px; }
.search { position: relative; display: block; }
.search svg { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: var(--hf-muted); pointer-events: none; }
.search .hf-inp { padding-left: 36px; }
.hint { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--hf-muted); margin: 0; }
.results { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; max-height: 260px; overflow-y: auto; }
.res {
  width: 100%; display: flex; align-items: center; gap: 10px; text-align: left; padding: 8px; border-radius: 12px;
  border: 1px solid var(--hf-line-3); background: var(--hf-card); color: var(--hf-ink); font: inherit;
}
.res:hover:not(:disabled) { background: var(--hf-fill-3); }
.res[aria-pressed="true"] { border-color: var(--hf-ink); }
.thumb { width: 40px; height: 40px; flex: none; }
.rtext { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.rname { font-size: 14px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rtext small { font-size: 12px; color: var(--hf-muted); }
.qty { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; align-items: end; }
.name { display: flex; gap: 8px; }
.bulb { flex: none; gap: 6px; }
.macros { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.end { justify-content: flex-end; }
.foot { display: flex; align-items: center; gap: 8px; justify-content: space-between; flex-wrap: wrap; }
@media (max-width: 520px) {
  .macros { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .bulb span { display: none; }
}
</style>
