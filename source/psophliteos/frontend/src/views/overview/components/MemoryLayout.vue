<template>
  <div class="mem-layout bg-white">
    <p class="font-bold text-base title">{{ t('overview.memoryLayout') }}</p>
    <div class="rrow" v-if="overall">
      <span class="lab">{{ t('overview.ddrOverall') }}</span>
      <span class="num">{{ unitSize(overall.usedMB) }} / {{ unitSize(overall.totalMB) }}</span>
      <span class="pct">{{ overall.usagePct.toFixed(1) }}%</span>
    </div>
    <div class="rrow" v-for="r in regions" :key="r.label">
      <span class="lab">{{ r.label }}</span>
      <span class="num">{{ unitSize(r.usedMB) }} / {{ unitSize(r.totalMB) }}</span>
      <span class="pct">{{ r.usagePct.toFixed(1) }}%</span>
    </div>
  </div>
</template>
<script lang="ts" setup>
  import { computed } from 'vue';
  import { useI18n } from '/@/hooks/web/useI18n';

  const { t } = useI18n();

  interface MemRegion {
    totalMB: number;
    usedMB: number;
    usagePct: number;
  }
  interface MemoryLayout {
    system: MemRegion;
    tpu: MemRegion;
    vpu: MemRegion;
    vpp: MemRegion;
    chipType: string;
  }

  const props = defineProps<{ layout: MemoryLayout | null | undefined }>();

  const isVPSS = (chip: string) => chip === 'bm1688' || chip === 'cv186ah';

  const regions = computed(() => {
    const lay = props.layout;
    if (!lay) return [];
    const vppLabel = isVPSS(lay.chipType) ? t('overview.vpssMemory') : t('overview.vppMemory');
    const list = [
      { label: t('overview.systemMemory'), r: lay.system },
      { label: t('overview.tpuMemory'), r: lay.tpu },
      { label: t('overview.vpuMemory'), r: lay.vpu },
      { label: vppLabel, r: lay.vpp },
    ];
    return list
      .filter((x) => (x.r?.totalMB ?? 0) > 0)
      .map((x) => ({
        label: x.label,
        totalMB: x.r.totalMB,
        usedMB: x.r.usedMB,
        usagePct: x.r.usagePct,
      }));
  });

  // DDR 整体：system + tpu + vpu + vpp 各分区总量与已用的汇总（类似 eMMC 整体）。
  const overall = computed(() => {
    const rs = regions.value;
    if (rs.length === 0) return null;
    const totalMB = rs.reduce((s, r) => s + r.totalMB, 0);
    const usedMB = rs.reduce((s, r) => s + r.usedMB, 0);
    if (totalMB <= 0) return null;
    return {
      totalMB,
      usedMB,
      usagePct: (usedMB / totalMB) * 100,
    };
  });

  const unitSize = (mb: number) => {
    if (!mb && mb !== 0) return '';
    if (mb < 1024) return mb.toFixed(0) + 'MB';
    return (mb / 1024).toFixed(1) + 'GB';
  };
</script>
<style lang="less" scoped>
  .mem-layout {
    padding: 16px 18px;
    height: 100%;

    .title {
      margin-bottom: 10px;
    }

    .rrow {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 5px 0;
      font-size: 12px;

      .lab {
        width: 72px;
        color: #555;
        flex-shrink: 0;
      }

      .num {
        color: #999;
        width: 116px;
        text-align: right;
        flex-shrink: 0;
      }

      .pct {
        width: 40px;
        text-align: right;
        font-weight: 600;
        flex-shrink: 0;
      }
    }
  }
</style>
