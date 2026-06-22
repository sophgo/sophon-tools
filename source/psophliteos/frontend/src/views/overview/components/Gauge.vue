<template>
  <div ref="chartRef" :style="{ width, height }"></div>
</template>
<script lang="ts" setup>
  // @ts-nocheck
  import { Ref, ref, watch } from 'vue';

  import { useECharts } from '/@/hooks/web/useECharts';

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
    value: {
      type: Number,
      default: 0,
    },
    colors: {
      type: Array,
      default: () => ['#C878D5', '#8127D2'],
    },
    max: {
      type: Number,
      default: 100,
    },
    unit: {
      type: String,
      default: '',
    },
  });

  const chartRef = ref<HTMLDivElement | null>(null);
  const { setOptions, echarts } = useECharts(chartRef as Ref<HTMLDivElement>);

  watch(
    [() => props.loading, () => props.value],
    () => {
      if (props.loading) {
        return;
      }
      setOptions({
        title: {
          text: props.unit,
          bottom: 0,
          left: 'center',
          textStyle: {
            fontSize: 14,
            fontWeight: 'normal',
          },
        },
        series: [
          {
            name: props.unit,
            type: 'gauge',
            min: 0,
            max: props.max,
            radius: '80%',
            splitNumber: 10,
            axisLine: {
              // 坐标轴线
              lineStyle: {
                shadowColor: 'rgba(56, 23, 67, 0.25)',
                shadowBlur: 8,
                opacity: 0.8,
                color: [
                  [
                    1,
                    new echarts.graphic.LinearGradient(0, 0, 1, 0, [
                      {
                        offset: 0,
                        color: props.colors[0],
                      },
                      {
                        offset: 1,
                        color: props.colors[1],
                      },
                    ]),
                  ],
                  // [1, '#56606E'],
                ],
                width: 30,
              },
            },
            axisTick: {
              // 坐标轴小标记
              distance: -30,
              length: 10, // 属性length控制线长
              lineStyle: {
                // 属性lineStyle控制线条样式
                color: 'white',
              },
            },
            axisLabel: {
              distance: 40,
            },
            splitLine: {
              // 分隔线
              distance: -30,
              length: 30, // 属性length控制线长
              lineStyle: {
                // 属性lineStyle（详见lineStyle）控制线条样式
                color: 'white',
              },
            },
            pointer: {
              width: 8,
              length: '70%',
              itemStyle: {
                color: {
                  type: 'linear',
                  x: 0,
                  y: 0,
                  x2: 0,
                  y2: 1,
                  colorStops: [
                    {
                      offset: 0,
                      color: props.colors[0],
                    },
                    {
                      offset: 1,
                      color: props.colors[1],
                    },
                  ],
                  global: false, // 缺省为 false
                },
              },
            },
            title: {
              offsetCenter: [0, '20%'], // x, y，单位px
            },
            detail: {
              fontSize: 20,
              // 其余属性默认使用全局文本样式，详见TEXTSTYLE
              // formatter: '{value}℃',
              fontWeight: 'bolder',
            },
            data: [{ value: props.value }],
          },
        ],
      });
    },
    { immediate: true },
  );
</script>
