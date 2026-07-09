<template>
  <div class="flex flex-wrap items-center gap-8px mb-16px">
    <Select
      v-model:value="preset"
      style="width: 140px"
      :options="presetOptions"
      @change="onPresetChange"
    />
    <RangePicker
      v-model:value="customRange"
      :show-time="true"
      format="YYYY-MM-DD HH:mm"
      :disabled="preset !== 'custom'"
      @change="onCustomChange"
    />
    <Button @click="emit('openSelector')">
      指标选择 ({{ selectedCount }})
    </Button>
    <Button type="primary" :loading="loading" @click="emit('query')">查询</Button>
    <Button :loading="exporting" @click="emit('export')">导出 CSV</Button>
  </div>
</template>
<script lang="ts" setup>
  // @ts-nocheck
  import { ref, watch } from 'vue';
  import { Select, RangePicker, Button } from 'ant-design-vue';
  import dayjs, { Dayjs } from 'dayjs';

  const props = defineProps<{
    loading: boolean;
    exporting: boolean;
    selectedCount: number;
  }>();
  const emit = defineEmits<{
    (e: 'query'): void;
    (e: 'export'): void;
    (e: 'openSelector'): void;
    (e: 'rangeChange', from: number, to: number): void;
  }>();

  const presetOptions = [
    { label: '最近 1 小时', value: '1h' },
    { label: '最近 6 小时', value: '6h' },
    { label: '最近 24 小时', value: '24h' },
    { label: '最近 7 天', value: '7d' },
    { label: '自定义', value: 'custom' },
  ];

  const preset = ref('1h');
  const customRange = ref<[Dayjs, Dayjs]>();

  function presetToSeconds(p: string): [number, number] {
    const now = Math.floor(Date.now() / 1000);
    const map: Record<string, number> = { '1h': 3600, '6h': 21600, '24h': 86400, '7d': 604800 };
    return [now - (map[p] || 3600), now];
  }

  function onPresetChange(v: string) {
    if (v !== 'custom') {
      const [f, t] = presetToSeconds(v);
      emit('rangeChange', f, t);
    }
  }

  function onCustomChange(_v: any, fmtStr: [string, string]) {
    if (fmtStr && fmtStr[0] && fmtStr[1]) {
      const from = dayjs(fmtStr[0]).unix();
      const to = dayjs(fmtStr[1]).unix();
      emit('rangeChange', from, to);
    }
  }

  // 不在子组件 onMounted 自动触发 rangeChange —— 首次查询由父组件
  // 在加载完保存的指标选择后发起，避免用默认字段先查一次。
</script>
