<template>
  <div>
    <div class="image-grid">
      <div
        v-for="(url, index) in modelValue"
        :key="`${url}-${index}`"
        class="image-tile"
      >
        <ElImage
          :src="imageUrl(url, 160)"
          :preview-src-list="modelValue"
          :initial-index="index"
          fit="contain"
          preview-teleported
        />
        <div class="image-tools">
          <ElButton
            link
            :disabled="index === 0"
            title="设为首图"
            @click="move(index, 0)"
            >{{ index === 0 ? "首图" : "置顶" }}</ElButton
          ><ElButton
            link
            :disabled="index === 0"
            title="向前移动"
            @click="move(index, index - 1)"
            >←</ElButton
          ><ElButton link type="danger" title="移除图片" @click="remove(index)"
            >×</ElButton
          >
        </div>
      </div>
    </div>
    <div v-for="entry in queue" :key="entry.id" class="upload-progress">
      <span>{{ entry.file.name }}</span
      ><ElProgress
        v-if="entry.state === 'loading'"
        :percentage="entry.progress"
      /><span v-if="entry.state === 'failed'" class="negative"
        >{{ entry.error }}
        <ElButton link type="primary" @click="run(entry)">重试</ElButton
        ><ElButton link @click="queue = queue.filter((q) => q.id !== entry.id)"
          >移除</ElButton
        ></span
      >
    </div>
    <ElButton
      class="section-gap"
      :disabled="modelValue.length >= max || busy"
      @click="input.click()"
      >＋ {{ max === 1 ? "上传图片" : "添加图片" }}</ElButton
    ><span class="small-note" style="margin-left: 10px"
      >{{ modelValue.length }} / {{ max }} 张 · 点击图片预览</span
    ><input
      ref="input"
      type="file"
      accept="image/*"
      :multiple="max > 1"
      hidden
      @change="choose"
    />
  </div>
</template>
<script setup>
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { uploadImage } from "../composables/workbench";
import { imageUrl } from "../utils/imageUrl";
const props = defineProps({
    modelValue: { type: Array, default: () => [] },
    max: { type: Number, default: 10 },
  }),
  emit = defineEmits(["update:modelValue", "busy"]);
const input = ref(),
  queue = ref([]),
  busy = computed(() => queue.value.some((q) => q.state === "loading"));
watch(busy, (v) => emit("busy", v));
function move(from, to) {
  const next = [...props.modelValue];
  next.splice(to, 0, next.splice(from, 1)[0]);
  emit("update:modelValue", next);
}
function remove(index) {
  emit(
    "update:modelValue",
    props.modelValue.filter((_, i) => i !== index),
  );
}
async function run(entry) {
  if (entry.state === "loading") return;
  if (props.modelValue.length >= props.max) {
    ElMessage.warning("图片数量已达上限");
    return;
  }
  entry.state = "loading";
  entry.progress = 0;
  try {
    const url = await uploadImage(entry.file, (p) => (entry.progress = p));
    emit("update:modelValue", [...props.modelValue, url].slice(0, props.max));
    queue.value = queue.value.filter((q) => q.id !== entry.id);
  } catch (e) {
    entry.state = "failed";
    entry.error = e.message;
  }
}
async function choose(event) {
  const files = [...event.target.files];
  event.target.value = "";
  for (const file of files.slice(0, props.max - props.modelValue.length)) {
    if (!file.type.startsWith("image/") || file.size > 32 * 1024 * 1024) {
      ElMessage.error("请选择不超过 32 MB 的图片");
      continue;
    }
    const entry = {
      id: crypto.randomUUID(),
      file,
      state: "queued",
      progress: 0,
    };
    queue.value.push(entry);
    await run(queue.value.find((q) => q.id === entry.id));
  }
}
</script>
<style scoped>
.upload-progress {
  font-size: 12px;
  margin-top: 12px;
  max-width: 400px;
  overflow-wrap: anywhere;
}
.upload-progress > span {
  display: block;
  margin-bottom: 5px;
}
</style>
