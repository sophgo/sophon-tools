<template>
  <div class="disk-layout bg-white">
    <p class="font-bold text-base title">{{ t('overview.diskLayout') }}</p>
    <div class="rrow" v-if="overall">
      <span class="lab">{{ t('overview.emmcOverall') }}</span>
      <span class="num">{{ unitSize(overall.usedMB) }} / {{ unitSize(overall.totalMB) }}</span>
      <span class="pct">{{ overall.usagePct.toFixed(1) }}%</span>
    </div>
    <div class="rrow" v-for="p in partitions" :key="p.device">
      <span class="lab">{{ p.mountOn }}</span>
      <span class="num">{{ unitSize(p.usedMB) }} / {{ unitSize(p.totalMB) }}</span>
      <span class="pct">{{ p.usagePct.toFixed(1) }}%</span>
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
  interface DiskPart {
    device: string;
    mountOn: string;
    totalMB: number;
    usedMB: number;
    usagePct: number;
  }
  interface DiskLayout {
    emmcOverall: MemRegion;
    partitions: DiskPart[];
  }

  const props = defineProps<{ layout: DiskLayout | null | undefined }>();

  const overall = computed(() => {
    const r = props.layout?.emmcOverall;
    return r && r.totalMB > 0 ? r : null;
  });

  const partitions = computed(() => {
    const list = props.layout?.partitions || [];
    return list.filter((p) => (p?.totalMB ?? 0) > 0);
  });

  const unitSize = (mb: number) => {
    if (!mb && mb !== 0) return '';
    if (mb < 1024) return mb.toFixed(0) + 'MB';
    return (mb / 1024).toFixed(1) + 'GB';
  };
</script>
<style lang="less" scoped>
  .disk-layout {
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
        width: 110px;
        color: #555;
        flex-shrink: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
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
