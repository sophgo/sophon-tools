<template>
  <div ref="chartRef" :style="{ width, height }"></div>
</template>
<script lang="ts" setup>
  // @ts-nocheck
  import { Ref, ref, watch } from 'vue';
  import { storeToRefs } from 'pinia';

  import { useECharts } from '/@/hooks/web/useECharts';
  import { useDeviceInfo } from '/@/store/modules/overview';

  import { useI18n } from '/@/hooks/web/useI18n';
  const { t } = useI18n();

  const props = defineProps({
    loading: Boolean,
    width: {
      type: String as PropType<string>,
      default: '100%',
    },
    height: {
      type: String as PropType<string>,
      default: '300px',
    },
  });

  const chartRef = ref<HTMLDivElement | null>(null);
  const { setOptions } = useECharts(chartRef as Ref<HTMLDivElement>);
  const colors = ['#57a8e0', '#28b463', '#9b59b6', '#ffa833'];

  // 设备基础信息
  const deviceInfoStore = useDeviceInfo();
  const {
    deviceStatus,
    cpu: cpuData,
    tpu: tpuData,
    memory: memoryData,
  } = storeToRefs(deviceInfoStore);

  watch(
    () => props.loading,
    () => {
      if (props.loading) {
        return;
      }
      setOptions({
        grid: {
          containLabel: true,
          left: '16px',
          right: '16px',
          top: '8px',
          bottom: '48px',
        },
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross',
            crossStyle: {
              color: '#999',
            },
          },
        },
        legend: {
          bottom: '0',
          data: [t('overview.cpuUsage'), t('overview.tpuUsage'), t('overview.memoryUsage')],
        },
        xAxis: [
          {
            type: 'category',
            data: [
              ...deviceStatus.value.map((board) => `${t('overview.coreBoard')}-${board.number}`),
              t('overview.controlBoard'),
            ],
            axisPointer: {
              type: 'shadow',
            },
          },
        ],
        yAxis: [
          {
            type: 'value',
            name: t('overview.usage'),
            min: 0,
            max: 100,
            interval: 20,
            axisLabel: {
              formatter: '{value} %',
            },
          },
        ],
        series: [
          {
            name: t('overview.cpuUsage'),
            type: 'bar',
            barMaxWidth: 20,
            tooltip: {
              valueFormatter: function (value) {
                return value + ' %';
              },
            },
            markPoint: {
              data: [
                { type: 'max', name: 'Max' },
                { type: 'min', name: 'Min' },
              ],
            },
            data: cpuData,
            itemStyle: {
              color: colors[0],
            },
          },
          {
            name: t('overview.tpuUsage'),
            type: 'bar',
            barMaxWidth: 20,
            tooltip: {
              valueFormatter: function (value) {
                return value + ' %';
              },
            },
            markPoint: {
              data: [
                { type: 'max', name: 'Max' },
                { type: 'min', name: 'Min' },
              ],
            },
            data: tpuData,
            itemStyle: {
              color: colors[1],
            },
          },
          {
            name: t('overview.memoryUsage'),
            type: 'bar',
            barMaxWidth: 20,
            tooltip: {
              valueFormatter: function (value) {
                return value + ' %';
              },
            },
            markPoint: {
              data: [
                { type: 'max', name: 'Max' },
                { type: 'min', name: 'Min' },
              ],
            },
            itemStyle: {
              color: colors[2],
            },
            data: memoryData,
          },
        ],
      });
    },
    { immediate: true },
  );
</script>
