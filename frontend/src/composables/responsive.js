import { computed, onScopeDispose, ref } from 'vue';

// One media query subscription per consumer; resizing never changes business state.
export function useResponsive() {
  const phoneQuery = window.matchMedia('(max-width: 767px)');
  const compactQuery = window.matchMedia('(max-width: 1023px)');
  const isPhone = ref(phoneQuery.matches);
  const isCompact = ref(compactQuery.matches);
  const phoneChanged = event => { isPhone.value = event.matches; };
  const compactChanged = event => { isCompact.value = event.matches; };
  phoneQuery.addEventListener('change', phoneChanged);
  compactQuery.addEventListener('change', compactChanged);
  onScopeDispose(() => {
    phoneQuery.removeEventListener('change', phoneChanged);
    compactQuery.removeEventListener('change', compactChanged);
  });
  return { isPhone, isCompact, isTablet: computed(() => isCompact.value && !isPhone.value) };
}
