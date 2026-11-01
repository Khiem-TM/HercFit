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
.onboarding-field label{display:block;font-size:12px;color:light-dark(#44423d, #c9c6c0);margin-bottom:10px}.field-control{display:flex;align-items:center;border:1px solid light-dark(#18181815, #ffffff15);border-radius:10px;background:light-dark(#18181803, #ffffff03);transition:border-color .2s,background .2s}.field-control:focus-within{border-color:light-dark(#87671a99, #d4b77d99);background:light-dark(#87671a05, #d4b77d05)}.field-control.invalid{border-color:light-dark(#a6564e77, #ffb4ab77)}.field-control input{width:100%;min-width:0;background:transparent;color:light-dark(#2b2720, #eee9df);border:0;padding:15px 16px;font-size:14px;outline:none;border-radius:10px}.field-control span{font:10px 'JetBrains Mono',monospace;color:light-dark(#726f66, #8b887f);padding-right:16px;white-space:nowrap}.field-hint,.field-error{font-size:11px;line-height:1.6;margin-top:7px}.field-hint{color:light-dark(#767570, #82817c)}.field-error{color:light-dark(#a6564e, #ffb4ab)}
</style>
