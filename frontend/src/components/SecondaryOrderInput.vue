<template>
  <ElInput :model-value="suffix" :maxlength="253" clearable placeholder="选填副单号" aria-label="副单号（选填）" @update:model-value="change" @paste="paste">
    <template #prepend>PO</template>
  </ElInput>
</template>
<script setup>
import {computed} from 'vue';
const props=defineProps({modelValue:{type:String,default:''}});
const emit=defineEmits(['update:modelValue']);
const suffix=computed(()=>props.modelValue.replace(/^PO/i,''));
function change(value){emit('update:modelValue',value.trim()?'PO'+value:'');}
function paste(event){const text=event.clipboardData?.getData('text')||'';if(/^PO/i.test(text.trim())){event.preventDefault();change(text.trim().slice(2));}}
</script>
