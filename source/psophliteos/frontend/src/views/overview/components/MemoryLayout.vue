<template>
  <div class="mem-layout bg-white">
    <p class="font-bold text-base title">{{ t('overview.memoryLayout') }}</p>
    <div class="rrow" v-for="r in regions" :key="r.label">
      <span class="lab">{{ r.label }}</span>
      <span class="bar"><i :style="{ width: r.usagePct + '%', background: barColor(r.usagePct) }"></i></span>
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

  // BM1688/CV186AH 无 VPU（VPU total 为 0），且 VPP 称 VPSS。
  const isVPSS = (chip: string) => chip === 'bm1688' || chip === 'cv186ah';

  const regions = computed(() => {
    const lay = props.layout;
    if (!lay) return [];
    const vppLabel = isVPSS(lay.chipType)
      ? t('overview.vpssMemory')
      : t('overview.vppMemory');
    const list = [
      { label: t('overview.systemMemory'), r: lay.system },
      { label: t('overview.tpuMemory'), r: lay.tpu },
      { label: t('overview.vpuMemory'), r: lay.vpu },
      { label: vppLabel, r: lay.vpp },
    ];
    // total<=0 的区域不展示（SE9 无 VPU → 隐藏 VPU 行）
    return list
      .filter((x) => (x.r?.totalMB ?? 0) > 0)
      .map((x) => ({
        label: x.label,
        totalMB: x.r.totalMB,
        usedMB: x.r.usedMB,
        usagePct: x.r.usagePct,
      }));
  });

  // MB → 人类可读（MB/GB）。
  const unitSize = (mb: number) => {
    if (!mb && mb !== 0) return '';
    if (mb < 1024) return mb.toFixed(0) + 'MB';
    return (mb / 1024).toFixed(1) + 'GB';
  };

  const barColor = (pct: number) => {
    if (pct >= 90) return '#ff4d4f';
    if (pct >= 70) return '#faad14';
    return '#108ee9';
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

      .bar {
        flex: 1;
        height: 6px;
        background: #f0f0f0;
        border-radius: 3px;
        overflow: hidden;

        & > i {
          display: block;
          height: 100%;
        }
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
