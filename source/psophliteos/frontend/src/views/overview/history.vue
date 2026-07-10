<template>
  <div class="p-16px bg-white" style="min-height: calc(100vh - 100px)">
    <MetricsToolbar
      :loading="loading"
      :exporting="exporting"
      :selected-count="selectedFields.length"
      @range-change="onRangeChange"
      @open-selector="selectorOpen = true"
      @query="onQuery"
      @export="onExport"
    />

    <!-- 异常提示条 -->
    <Alert
      v-if="result?.skipped_files?.length"
      class="mb-16px"
      type="warning"
      show-icon
      :message="`跳过的损坏分段: ${result.skipped_files.join(', ')}`"
    />
    <Alert
      v-if="result?.truncated"
      class="mb-16px"
      type="warning"
      show-icon
      message="结果超过 10000 点，已截断。请缩小时间范围。"
    />

    <!-- 每个指标独立卡片：折线图（恒定值显示为平线） -->
    <div v-if="loading" class="text-center py-40px">
      <Spin tip="加载中..." />
    </div>
    <div
      v-else-if="cards.length"
      class="grid grid-cols-1 lg:grid-cols-2 gap-16px"
    >
      <MetricsChart
        v-for="card in cards"
        :key="card.field"
        :field="card.field"
        :label="card.label"
        :fields="card.fields"
        :points="card.points"
      />
    </div>
    <Empty v-else description="无数据，请选择指标" class="py-40px" />

    <!-- 指标选择弹窗 -->
    <MetricsSelector
      v-model:open="selectorOpen"
      :all-fields="allFields"
      :selected="selectedFields"
      @apply="onSelectorApply"
    />
  </div>
</template>
<script lang="ts" setup>
  // @ts-nocheck
  import { ref, computed, onMounted } from 'vue';
  import { Spin, Alert, Empty, message } from 'ant-design-vue';
  import MetricsToolbar from './history/components/MetricsToolbar.vue';
  import MetricsSelector from './history/components/MetricsSelector.vue';
  import MetricsChart from './history/components/MetricsChart.vue';
  import {
    fieldsApi,
    historyApi,
    exportCsv,
    getSelection,
    type HistoryResult,
  } from '/@/api/overview/metrics';
  import {
    GROUP_DEFS,
    fieldToGroup,
    fieldLabel,
    DEFAULT_FIELDS,
  } from './history/metricsGroup';

  const loading = ref(false);
  const exporting = ref(false);
  const selectorOpen = ref(false);

  const allFields = ref<string[]>([]);
  const selectedFields = ref<string[]>([...DEFAULT_FIELDS]);
  const fromTs = ref(0);
  const toTs = ref(0);
  const result = ref<HistoryResult | null>(null);

  const SEVEN_DAYS = 7 * 86400;

  onMounted(async () => {
    try {
      allFields.value = await fieldsApi();
    } catch {
      message.error('获取字段列表失败');
    }
    // 从后端加载已存选择；无则用默认
    const saved = await getSelection();
    if (saved && saved.length) {
      selectedFields.value = saved;
    }
    // 首次查询：最近 1h，用已加载的（保存的）指标选择
    const now = Math.floor(Date.now() / 1000);
    fromTs.value = now - 3600;
    toTs.value = now;
    onQuery();
  });

  function onRangeChange(from: number, to: number) {
    fromTs.value = from;
    toTs.value = to;
    // 不自动查询：用户改时间范围后需点"查询"（手动刷新，存档历史数据）
  }

  async function onQuery() {
    if (!fromTs.value || !toTs.value) return;
    if (toTs.value - fromTs.value > SEVEN_DAYS) {
      message.warning('时间范围超过 7 天，查询可能较慢');
    }
    loading.value = true;
    try {
      result.value = await historyApi({
        from: fromTs.value,
        to: toTs.value,
        fields: selectedFields.value,
      });
    } catch (e) {
      message.error('查询失败');
    } finally {
      loading.value = false;
    }
  }

  async function onExport() {
    if (!fromTs.value || !toTs.value) return;
    exporting.value = true;
    try {
      await exportCsv(fromTs.value, toTs.value);
      message.success('导出已开始');
    } catch {
      message.error('导出失败');
    } finally {
      exporting.value = false;
    }
  }

  function onSelectorApply(fields: string[]) {
    selectedFields.value = fields;
    onQuery();
  }

  // 每个选中字段一张折线图卡片（恒定值→平线，不再用静态文字）
  const cards = computed(() => {
    if (!result.value || !result.value.fields.length) return [];
    const resFields = result.value.fields; // [timestamp, ...selected]
    const tsIdx = 0;
    const out: any[] = [];
    for (const f of selectedFields.value) {
      const idx = resFields.indexOf(f);
      if (idx < 0) continue; // 该字段不在本次结果（跨版本缺失）
      out.push({
        field: f,
        label: fieldLabel(f),
        fields: ['timestamp', f],
        points: result.value.points.map((row) => [row[tsIdx], row[idx]]),
      });
    }
    return out;
  });
</script>
