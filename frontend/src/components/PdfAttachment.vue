<template>
  <div>
    <div v-if="modelValue">
      <a :href="modelValue" target="_blank" rel="noopener">打开 PDF 附件 ↗</a>
      <ElButton link type="danger" :disabled="busy" @click="$emit('update:modelValue', '')">移除</ElButton>
    </div>
    <ElButton :loading="busy" @click="input.click()">{{ modelValue ? '替换 PDF' : '＋ 上传 PDF' }}</ElButton>
    <span class="small-note"> 最多 1 个 PDF，不超过 32 MB</span>
    <input ref="input" type="file" accept="application/pdf,.pdf" hidden @change="choose" />
  </div>
</template>
<script setup>
import { ref } from 'vue';
import { ElMessage } from 'element-plus';
import { uploadImage } from '../composables/workbench';
defineProps({ modelValue: { type: String, default: '' } });
const emit = defineEmits(['update:modelValue', 'busy']);
const input = ref(), busy = ref(false);
async function choose(event) {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file || busy.value) return;
  if (!/\.pdf$/i.test(file.name) || file.size > 32 * 1024 * 1024) {
    ElMessage.error('请选择不超过 32 MB 的 PDF 文件');
    return;
  }
  busy.value = true;
  emit('busy', true);
  try {
    emit('update:modelValue', await uploadImage(file, undefined, 'orders/templates/attachments'));
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    busy.value = false;
    emit('busy', false);
  }
}
</script>
