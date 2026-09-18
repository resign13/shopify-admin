<template>
  <div
    ref="root"
    class="chart"
    role="img"
    :aria-label="metric === 'orders' ? '每日订单数趋势' : '每日商品金额趋势'"
  />
</template>
<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from "vue";
import { init, use } from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);
const props = defineProps({ points: Array, metric: String }),
  root = ref();
let chart, observer;
function draw() {
  chart?.setOption({
    animation: false,
    grid: { left: 52, right: 22, top: 20, bottom: 30 },
    tooltip: { trigger: "axis" },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: props.points.map((p) => p.date.slice(5)),
      axisLine: { lineStyle: { color: "#e5e7eb" } },
      axisTick: { show: false },
      axisLabel: { color: "#98a2b3", fontSize: 10 },
    },
    yAxis: {
      type: "value",
      minInterval: props.metric === "orders" ? 1 : undefined,
      splitLine: { lineStyle: { color: "#f0f2f5", type: "dashed" } },
      axisLabel: { color: "#98a2b3", fontSize: 10 },
    },
    series: [
      {
        type: "line",
        data: props.points.map((p) => p[props.metric]),
        smooth: 0.25,
        showSymbol: false,
        lineStyle: { width: 2.5, color: "#2563eb" },
        areaStyle: { color: "#2563eb", opacity: 0.06 },
        itemStyle: { color: "#2563eb" },
      },
    ],
  });
}
onMounted(() => {
  chart = init(root.value);
  draw();
  observer = new ResizeObserver(() => chart.resize());
  observer.observe(root.value);
});
watch(() => [props.points, props.metric], draw, { deep: true });
onBeforeUnmount(() => {
  observer?.disconnect();
  chart?.dispose();
});
</script>
