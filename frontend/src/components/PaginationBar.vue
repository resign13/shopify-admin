<template>
  <div v-if="totalItems > 0" class="pager">
    <div class="pager-meta">
      <strong>{{ startItem }}-{{ endItem }}</strong>
      <span>共 {{ totalItems }} {{ itemLabel }}</span>
    </div>

    <div class="pager-controls">
      <label class="pager-size">
        <span>每页显示</span>
        <select :value="pageSize" @change="handlePageSizeChange">
          <option v-for="option in sizeOptions" :key="option" :value="option">
            {{ option }}
          </option>
        </select>
      </label>

      <div class="pager-buttons">
        <button class="pager-button" type="button" :disabled="page <= 1" @click="setPage(page - 1)">
          上一页
        </button>

        <button
          v-for="pageNumber in visiblePages"
          :key="pageNumber"
          :class="['pager-button', { active: pageNumber === page }]"
          type="button"
          @click="setPage(pageNumber)"
        >
          {{ pageNumber }}
        </button>

        <button class="pager-button" type="button" :disabled="page >= totalPages" @click="setPage(page + 1)">
          下一页
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  page: {
    type: Number,
    required: true,
  },
  pageSize: {
    type: Number,
    required: true,
  },
  totalItems: {
    type: Number,
    required: true,
  },
  itemLabel: {
    type: String,
    default: '项',
  },
  sizeOptions: {
    type: Array,
    default: () => [6, 10, 20, 40],
  },
})

const emit = defineEmits(['update:page', 'update:pageSize'])

const totalPages = computed(() => Math.max(1, Math.ceil(props.totalItems / props.pageSize)))
const safePage = computed(() => Math.min(Math.max(1, props.page), totalPages.value))
const startItem = computed(() => {
  if (!props.totalItems) return 0
  return (safePage.value - 1) * props.pageSize + 1
})
const endItem = computed(() => Math.min(props.totalItems, safePage.value * props.pageSize))
const visiblePages = computed(() => {
  const start = Math.max(1, safePage.value - 2)
  const end = Math.min(totalPages.value, start + 4)
  const pages = []
  for (let pageNumber = Math.max(1, end - 4); pageNumber <= end; pageNumber += 1) {
    pages.push(pageNumber)
  }
  return pages
})

function setPage(nextPage) {
  const normalized = Math.min(Math.max(1, nextPage), totalPages.value)
  emit('update:page', normalized)
}

function handlePageSizeChange(event) {
  const nextSize = Number(event.target.value || props.pageSize)
  emit('update:pageSize', nextSize)
  emit('update:page', 1)
}
</script>

<style scoped>
.pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid rgba(110, 85, 61, 0.14);
}

.pager-meta {
  display: flex;
  align-items: baseline;
  gap: 8px;
  color: var(--muted);
}

.pager-controls,
.pager-buttons,
.pager-size {
  display: flex;
  align-items: center;
  gap: 10px;
}

.pager-size span {
  color: var(--muted);
  font-size: 0.92rem;
}

.pager-size select {
  min-height: 40px;
  border: 1px solid rgba(110, 85, 61, 0.14);
  border-radius: 999px;
  padding: 0 12px;
  background: #fff;
}

.pager-button {
  min-width: 42px;
  min-height: 40px;
  padding: 0 14px;
  border: 1px solid rgba(110, 85, 61, 0.14);
  border-radius: 999px;
  background: #fff;
  color: var(--text);
  cursor: pointer;
}

.pager-button.active {
  border-color: transparent;
  background: linear-gradient(135deg, #cf9369, #b46b45);
  color: #fff;
}

.pager-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

@media (max-width: 900px) {
  .pager {
    flex-direction: column;
    align-items: flex-start;
  }

  .pager-controls {
    width: 100%;
    flex-direction: column;
    align-items: flex-start;
  }

  .pager-buttons {
    flex-wrap: wrap;
  }
}
</style>
