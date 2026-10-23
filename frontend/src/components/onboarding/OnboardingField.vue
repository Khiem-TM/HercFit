<script setup lang="ts">
defineOptions({ inheritAttrs: false })
defineProps<{ id: string; label: string; unit?: string; hint?: string; error?: string }>()
const model = defineModel<string>({ required: true })
</script>
<template>
  <div class="onboarding-field">
    <label :for="id">{{ label }}</label>
    <div class="field-control" :class="{ invalid: error }"><input :id="id" :value="model" v-bind="$attrs" @input="model = ($event.target as HTMLInputElement).value" :aria-invalid="Boolean(error)" :aria-describedby="error ? `${id}-error` : hint ? `${id}-hint` : undefined" /><span v-if="unit">{{ unit }}</span></div>
    <p v-if="error" :id="`${id}-error`" class="field-error" role="alert">{{ error }}</p>
    <p v-else-if="hint" :id="`${id}-hint`" class="field-hint">{{ hint }}</p>
  </div>
</template>
<style scoped>
.onboarding-field label{display:block;font-size:12px;color:#c9c6c0;margin-bottom:10px}.field-control{display:flex;align-items:center;border:1px solid #ffffff15;border-radius:10px;background:#ffffff03;transition:border-color .2s,background .2s}.field-control:focus-within{border-color:#d4b77d99;background:#d4b77d05}.field-control.invalid{border-color:#ffb4ab77}.field-control input{width:100%;min-width:0;background:transparent;color:#eee9df;border:0;padding:15px 16px;font-size:14px;outline:none;border-radius:10px;color-scheme:dark}.field-control span{font:10px 'JetBrains Mono',monospace;color:#8b887f;padding-right:16px;white-space:nowrap}.field-hint,.field-error{font-size:11px;line-height:1.6;margin-top:7px}.field-hint{color:#82817c}.field-error{color:#ffb4ab}
</style>
