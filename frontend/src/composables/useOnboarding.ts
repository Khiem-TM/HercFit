import { computed, reactive, shallowRef } from 'vue'
import { useAuth } from './useAuth'
import { buildOnboardingPayload, initialForm, validateStep, type FieldErrors } from '@/features/onboarding/model'
import type { OnboardingPayload } from '@/types/api'

export function useOnboarding() {
  const { user, currentGoal, completeOnboarding } = useAuth()
  const form = reactive(initialForm(user.value!, Boolean(currentGoal.value)))
  const step = shallowRef(0)
  const errors = shallowRef<FieldErrors>({})
  const submitting = shallowRef(false)
  const error = shallowRef('')
  const uncertain = shallowRef(false)
  let request: { payload: OnboardingPayload; key: string } | undefined
  const locked = computed(() => submitting.value || uncertain.value)
  const steps = ['Hồ sơ', 'Số đo', 'Mục tiêu', 'Xác nhận']

  function next() {
    errors.value = validateStep(form, step.value)
    if (!Object.keys(errors.value).length) { step.value++; error.value = '' }
  }
  function back() { if (!locked.value) { step.value = Math.max(0,step.value-1); form.confirmed = false; errors.value = {}; error.value = '' } }
  async function submit() {
    if (submitting.value || !user.value) return
    if (!request) {
      for (let index = 0; index < 4; index++) {
        const invalid = validateStep(form,index)
        if (Object.keys(invalid).length) { step.value = index; errors.value = invalid; return }
      }
      request = { payload:buildOnboardingPayload(form,user.value),key:crypto.randomUUID() }
    }
    submitting.value = true
    error.value = ''
    try {
      await completeOnboarding(request.payload,request.key)
      request = undefined
      uncertain.value = false
    } catch (failure) {
      const status = (failure as Error & {status?:number}).status
      uncertain.value = status === undefined || status >= 500
      if (!uncertain.value) request = undefined
      error.value = uncertain.value
        ? 'Chưa xác định được kết quả lưu. Hãy thử lại để hoàn tất với cùng thông tin đã xác nhận.'
        : failure instanceof Error ? failure.message : 'Không thể lưu hồ sơ. Vui lòng thử lại.'
    } finally { submitting.value = false }
  }
  return { form, step, steps, errors, submitting, locked, uncertain, error, currentGoal, next, back, submit }
}
