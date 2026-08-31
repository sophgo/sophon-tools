<template>
  <div class="log-download">
    <div class="log-download-top">
      <span class="log-download-title">{{ t('logs.logloading.sysLog') }}</span>
      <a-button type="primary" @click="download" :loading="downloading">
        {{ t('logs.logloading.loading') }}
      </a-button>
    </div>

    <a-alert
      v-if="!loading && overview"
      class="log-download-hint"
      type="info"
      show-icon
      :message="t('logs.logloading.hint', { root: overview.root })"
    />

    <div v-if="loading" class="log-download-center">
      <a-spin size="large" />
    </div>

    <div v-else-if="overview" class="log-download-body">
      <a-table
        size="small"
        :columns="columns"
        :data-source="overview.entries"
        :pagination="false"
        :row-key="(r) => r.path"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'size'">
            {{ record.type === 'dir' || record.type === 'file' ? formatBytes(record.size) : '—' }}
          </template>
          <template v-else-if="column.key === 'files'">
            <span v-if="record.type === 'dir'">{{ record.files }}</span>
            <span v-else>—</span>
          </template>
          <template v-else-if="column.key === 'mtime'">
            {{ formatToDateTime(record.mtime * 1000) }}
          </template>
          <template v-else-if="column.key === 'type'">
            <a-tag :color="typeColor(record.type)">{{ typeLabel(record.type) }}</a-tag>
          </template>
        </template>
        <template #summary v-if="overview.entries.length">
          <a-table-summary-row>
            <a-table-summary-cell :index="0" :col-span="2">{{
              t('logs.logloading.total')
            }}</a-table-summary-cell>
            <a-table-summary-cell :index="2">
              {{ formatBytes(overview.total_size) }}
            </a-table-summary-cell>
            <a-table-summary-cell :index="3">
              {{ overview.total_entries }}
            </a-table-summary-cell>
            <a-table-summary-cell :index="4" />
          </a-table-summary-row>
        </template>
      </a-table>
    </div>

    <div v-else class="log-download-center">
      <a-empty :description="t('logs.logloading.noData')" />
    </div>
  </div>
</template>
<script lang="ts" setup>
  import { computed, onMounted, ref } from 'vue';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { useMessage } from '/@/hooks/web/useMessage';
  import { formatToDateTime } from '/@/utils/dateUtil';
  import {
    getLogOverview,
    getLogDownloadUrl,
    LogOverview,
    LogOverviewEntry,
  } from '/@/api/logs/index';
  import { useDeviceInfo } from '/@/store/modules/overview';

  const deviceStore = useDeviceInfo();
  if (!deviceStore.deviceType) {
    deviceStore.getDeviceInfo();
  }
  const { t } = useI18n();
  const { createMessage } = useMessage();

  const loading = ref(false);
  const downloading = ref(false);
  const overview = ref<LogOverview | null>(null);

  const columns = computed(() => [
    { title: t('logs.logloading.colName'), dataIndex: 'name', key: 'name' },
    {
      title: t('logs.logloading.colType'),
      dataIndex: 'type',
      key: 'type',
      width: 90,
    },
    {
      title: t('logs.logloading.colSize'),
      dataIndex: 'size',
      key: 'size',
      width: 110,
    },
    {
      title: t('logs.logloading.colFiles'),
      dataIndex: 'files',
      key: 'files',
      width: 90,
    },
    {
      title: t('logs.logloading.colTime'),
      dataIndex: 'mtime',
      key: 'mtime',
      width: 180,
    },
  ]);

  const typeColor = (type: LogOverviewEntry['type']) =>
    type === 'dir' ? 'blue' : type === 'symlink' ? 'orange' : 'default';
  const typeLabel = (type: LogOverviewEntry['type']) => t(`logs.logloading.type.${type}`);

  function formatBytes(n: number): string {
    if (!n || n < 0) return '0 B';
    if (n < 1024) return n.toFixed(0) + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
    return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
  }

  async function loadOverview() {
    loading.value = true;
    try {
      overview.value = await getLogOverview();
    } catch (e: any) {
      createMessage.error(e?.message || t('logs.logloading.failedOverview'));
    } finally {
      loading.value = false;
    }
  }

  async function download() {
    downloading.value = true;
    try {
      const { url, name } = await getLogDownloadUrl();
      const a = document.createElement('a');
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (e: any) {
      createMessage.error(e?.message || t('logs.logloading.failedDownload'));
    } finally {
      downloading.value = false;
    }
  }

  onMounted(loadOverview);
</script>
<style lang="less" scoped>
  .log-download {
    padding: 16px;
    .log-download-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      .log-download-title {
        font-size: 20px;
        font-weight: bold;
      }
    }
    .log-download-hint {
      margin-bottom: 16px;
    }
    .log-download-center {
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 60px 0;
    }
    .log-download-body {
      max-width: 860px;
    }
  }
</style>
