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
  const { setOptions, echarts } = useECharts(chartRef as Ref<HTMLDivElement>);

  // 设备基础信息
  const deviceInfoStore = useDeviceInfo();
  const { fanSpeed: fanSpeedData, deviceStatus } = storeToRefs(deviceInfoStore);

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
          top: '32px',
          bottom: '0',
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
        // legend: {
        //   bottom: '0',
        //   data: ['CPU使用率', '内存使用率', '温度'],
        // },
        xAxis: [
          {
            type: 'category',
            data: deviceStatus.value.map((board) => `${t('overview.coreBoard')}-${board.number}`),
            axisPointer: {
              type: 'shadow',
            },
          },
        ],
        yAxis: [
          {
            type: 'value',
            name: '',
            min: 0,
            axisLabel: {
              formatter: '{value} r/min',
            },
          },
        ],
        series: [
          {
            name: t('overview.fanSpeed'),
            type: 'bar',
            barMaxWidth: 20,
            tooltip: {
              valueFormatter: function (value) {
                return value + ' r/min';
              },
            },
            markPoint: {
              data: [
                { type: 'max', name: 'Max' },
                { type: 'min', name: 'Min' },
              ],
            },
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: '#83bff6' },
                { offset: 0.5, color: '#188df0' },
                { offset: 1, color: '#188df0' },
              ]),
            },
            emphasis: {
              itemStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                  { offset: 0, color: '#2378f7' },
                  { offset: 0.7, color: '#2378f7' },
                  { offset: 1, color: '#83bff6' },
                ]),
              },
            },
            data: fanSpeedData,
          },
        ],
      });
    },
    { immediate: true },
  );
</script>
