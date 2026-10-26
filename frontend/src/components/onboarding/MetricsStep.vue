<script setup lang="ts">
import { Ruler } from 'lucide-vue-next'
import OnboardingField from './OnboardingField.vue'
import type { OnboardingForm, FieldErrors } from '@/features/onboarding/model'
const form = defineModel<OnboardingForm>({required:true})
defineProps<{errors:FieldErrors}>()
</script>
<template>
  <div class="step-fields">
    <label class="choice-toggle"><input v-model="form.metricsEnabled" type="checkbox" /><span>Ghi nhận số đo ban đầu</span><Ruler :size="17" /></label>
    <template v-if="form.metricsEnabled">
      <div class="two-columns"><OnboardingField id="weight" v-model="form.weight" label="Cân nặng *" unit="KG" type="number" inputmode="decimal" min="20" max="400" step="0.001" :error="errors.weight" placeholder="68.5" /><OnboardingField id="height" v-model="form.height" label="Chiều cao" unit="CM" type="number" inputmode="decimal" min="50" max="260" step="0.001" :error="errors.height" placeholder="172" /></div>
      <div class="two-columns"><OnboardingField id="bodyFat" v-model="form.bodyFat" label="Tỷ lệ mỡ cơ thể" unit="%" type="number" inputmode="decimal" min="2" max="75" step="0.01" :error="errors.bodyFat" placeholder="Chưa biết" /><OnboardingField id="muscleMass" v-model="form.muscleMass" label="Khối lượng cơ" unit="KG" type="number" inputmode="decimal" min="1" max="200" step="0.001" :error="errors.muscleMass" placeholder="Chưa biết" /></div>
      <p class="note">Chỉ cân nặng là bắt buộc khi ghi số đo. Các chỉ số chưa biết có thể để trống và bổ sung sau.</p>
    </template>
    <div v-else class="deferred"><Ruler :size="26" :stroke-width="1" /><h3>Bắt đầu theo nhịp của bạn.</h3><p>Bạn có thể ghi số đo đầu tiên trong phần hồ sơ hoặc qua hội thoại bất cứ lúc nào.</p></div>
  </div>
</template>
