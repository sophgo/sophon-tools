<template>
  <Card :bordered="true" size="small" class="!mb-4">
    <template #title>
      <span class="text-sm">{{ label || fields[1] }}</span>
    </template>
    <div ref="chartRef" :style="{ width: '100%', height: '220px' }"></div>
  </Card>
</template>
<script lang="ts" setup>
  // @ts-nocheck
  import { Ref, ref, watch } from 'vue';
  import { Card } from 'ant-design-vue';
  import { useECharts } from '/@/hooks/web/useECharts';

  const props = defineProps<{
    field?: string;
    label?: string; // 中文标题
    fields: string[]; // 该图要绘的字段名（含 timestamp 在 [0]）
    points: number[][]; // 每行对应 fields 顺序
  }>();

  const chartRef = ref<HTMLDivElement | null>(null);
  const { setOptions, echarts } = useECharts(chartRef as Ref<HTMLDivElement>);

  // 由字段名后缀推断 Y 轴单位（单指标图更准确）
  function yAxisFromField(field: string) {
    if (field.endsWith('_pct'))
      return { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } };
    if (field.endsWith('_c'))
      return { type: 'value', axisLabel: { formatter: '{value}°C' } };
    if (field.endsWith('_w'))
      return { type: 'value', axisLabel: { formatter: '{value}W' } };
    if (field.endsWith('_mv'))
      return { type: 'value', axisLabel: { formatter: '{value}mV' } };
    if (field.endsWith('_mw'))
      return { type: 'value', axisLabel: { formatter: '{value}mW' } };
    if (field.endsWith('_mhz'))
      return { type: 'value', axisLabel: { formatter: '{value}MHz' } };
    if (field.endsWith('_mib'))
      return { type: 'value', axisLabel: { formatter: '{value}MiB' } };
    if (field.endsWith('_kibps'))
      return { type: 'value', axisLabel: { formatter: '{value} KiB/s' } };
    if (field.endsWith('_hz'))
      return { type: 'value', axisLabel: { formatter: '{value}Hz' } };
    if (field.endsWith('_s'))
      return { type: 'value', axisLabel: { formatter: '{value}s' } };
    return { type: 'value' };
  }

  watch(
    () => [props.fields, props.points] as const,
    () => {
      if (!props.fields.length || !props.points.length) return;

      // timestamps = 每行 [0]；series 字段从 [1] 开始
      const xData = props.points.map((row) => fmtTime(row[0]));
      const series = props.fields.slice(1).map((name, i) => ({
        name: name,
        type: 'line' as const,
        smooth: true,
        showSymbol: false,
        data: props.points.map((row) => row[i + 1]),
      }));

      // 单指标图：按字段名推断 Y 轴；多指标图：用分组 yAxis
      const metricField = props.fields[1] || '';
      const yAx =
        props.fields.length === 2
          ? yAxisFromField(metricField)
          : yAxisFromField(metricField); // 统一按首字段推断
      setOptions({
        tooltip: { trigger: 'axis' },
        legend: { bottom: 0, type: 'scroll' },
        grid: { left: '8px', right: '16px', top: '24px', bottom: '40px', containLabel: true },
        xAxis: { type: 'category', data: xData, boundaryGap: false },
        yAxis: yAx,
        series,
      });
    },
    { immediate: true, deep: true },
  );

  function fmtTime(ts: number): string {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }
</script>
