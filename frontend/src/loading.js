import { computed, reactive } from 'vue'

const state = reactive({
  routeLoading: false,
  requestCount: 0,
})

export function startRouteLoading() {
  state.routeLoading = true
}

export function stopRouteLoading() {
  state.routeLoading = false
}

export function beginRequestLoading() {
  state.requestCount += 1
}

export function endRequestLoading() {
  state.requestCount = Math.max(0, state.requestCount - 1)
}

export const isAdminPageLoading = computed(() => state.routeLoading || state.requestCount > 0)
