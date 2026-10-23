<script setup lang="ts">
import { Activity, Dumbbell, Flame, Scale } from 'lucide-vue-next'
import OnboardingField from './OnboardingField.vue'
import { goalChoices, type OnboardingForm, type FieldErrors } from '@/features/onboarding/model'
const form = defineModel<OnboardingForm>({required:true})
defineProps<{errors:FieldErrors; existingGoal?:string}>()
const icons = [Flame,Dumbbell,Scale,Activity]
function choose(id:string,title:string) { form.value.goalType=id; form.value.goalTitle=title }
</script>
<template>
  <div class="step-fields">
    <p v-if="existingGoal" class="note">Bạn đã có mục tiêu “{{ existingGoal }}”. Mục tiêu này được giữ lại; bạn có thể điều chỉnh trong hội thoại.</p>
    <label v-else class="choice-toggle"><input v-model="form.goalEnabled" type="checkbox" /><span>Đặt mục tiêu đầu tiên</span><Activity :size="17" /></label>
    <template v-if="form.goalEnabled && !existingGoal">
      <div class="goal-grid" role="group" aria-label="Hướng đi của bạn"><button v-for="(choice,index) in goalChoices" :key="choice.id" type="button" class="goal-choice" :class="{chosen:form.goalType===choice.id}" :aria-pressed="form.goalType===choice.id" @click="choose(choice.id,choice.title)"><component :is="icons[index]" :size="20" :stroke-width="1.3" /><strong>{{ choice.title }}</strong><span>{{ choice.description }}</span></button></div>
      <p v-if="errors.goalType" class="field-error" role="alert">{{ errors.goalType }}</p>
      <OnboardingField id="goalTitle" v-model="form.goalTitle" label="Tên mục tiêu *" maxlength="255" :error="errors.goalTitle" placeholder="Một lời hẹn với chính mình" />
      <div class="two-columns"><OnboardingField id="startDate" v-model="form.startDate" label="Ngày bắt đầu *" type="date" :error="errors.startDate" /><OnboardingField id="targetDate" v-model="form.targetDate" label="Ngày mong muốn hoàn thành" type="date" :min="form.startDate" :error="errors.targetDate" /></div>
      <OnboardingField id="targetWeight" v-model="form.targetWeight" label="Cân nặng đích (tùy chọn)" unit="KG" type="number" inputmode="decimal" min="0.001" max="9999999.999" step="0.001" :error="errors.targetWeight" hint="Để trống nếu mục tiêu của bạn không dựa vào cân nặng." placeholder="Chưa đặt" />
    </template>
    <div v-else-if="!existingGoal" class="deferred"><Activity :size="26" :stroke-width="1" /><h3>Chưa cần chọn một đích đến.</h3><p>Bạn có thể khám phá và đặt mục tiêu cùng HercFit sau.</p></div>
  </div>
</template>
