<template>
  <BasicTable
    @register="registerTable"
    :title="t('maintenance.systemUpdate.updateList')"
    :noloading="true"
    :customRow="customRow"
  >
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'status'">
        {{ t(`maintenance.systemUpdate.status.${record.status}`) }}
      </template>
      <template v-if="column.key === 'type'">
        {{ t(`maintenance.systemUpdate.type.${record.type}`) }}
      </template>
      <template v-if="column.key === 'strategy'">
        {{ t(`maintenance.systemUpdate.strategy.${record.strategy}`) }}
      </template>
      <template v-if="column.key === 'info'">
        <span :style="{ color: record.status === 3 ? '#ed4014' : '' }">
          {{ record.info || '-' }}
        </span>
      </template>
    </template>
  </BasicTable>
  <Modal
    v-model:visible="detailVisible"
    :title="t('maintenance.systemUpdate.detail')"
    centered
    width="720px"
    :footer="null"
  >
    <Descriptions :column="1" bordered size="small" :labelStyle="{ width: '140px' }">
      <Descriptions.Item v-for="item in detailRows" :key="item.key" :label="item.label">
        {{ item.value }}
      </Descriptions.Item>
    </Descriptions>
  </Modal>
</template>
<script lang="ts" setup>
  import { BasicTable, useTable } from '/@/components/Table';
  import { getBasicColumns } from './tableData';
  import { upgradeStatusApi } from '/@/api/maintenance/index';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { onBeforeUnmount, onMounted, ref, computed } from 'vue';
  import { Modal, Descriptions } from 'ant-design-vue';
  const { t } = useI18n();

  const detailVisible = ref(false);
  const detailRecord = ref<any>(null);
  const customRow = (record) => ({
    onClick: () => {
      detailRecord.value = record;
      detailVisible.value = true;
    },
    style: { cursor: 'pointer' },
  });
  const detailRows = computed(() => {
    const r = detailRecord.value;
    if (!r) return [];
    return [
      { key: 'name', label: t('maintenance.systemUpdate.taskList.name'), value: r.name },
      { key: 'product', label: t('maintenance.systemUpdate.taskList.product'), value: r.product },
      {
        key: 'moduleName',
        label: t('maintenance.systemUpdate.taskList.moduleName'),
        value: r.moduleName,
      },
      {
        key: 'status',
        label: t('maintenance.systemUpdate.taskList.status'),
        value: t(`maintenance.systemUpdate.status.${r.status}`),
      },
      { key: 'step', label: t('maintenance.systemUpdate.taskList.step'), value: r.step },
      {
        key: 'strategy',
        label: t('maintenance.systemUpdate.taskList.strategy'),
        value: t(`maintenance.systemUpdate.strategy.${r.strategy}`),
      },
      {
        key: 'type',
        label: t('maintenance.systemUpdate.taskList.type'),
        value: t(`maintenance.systemUpdate.type.${r.type}`),
      },
      {
        key: 'fileName',
        label: t('maintenance.systemUpdate.taskList.fileName'),
        value: r.fileName,
      },
      {
        key: 'createTime',
        label: t('maintenance.systemUpdate.taskList.createTime'),
        value: r.createTime,
      },
      {
        key: 'info',
        label: t('maintenance.systemUpdate.taskList.info'),
        value: r.info || '-',
      },
    ];
  });

  const [registerTable, { reload }] = useTable({
    title: t('maintenance.systemUpdate.updateStatus'),
    api: upgradeStatusApi,
    columns: getBasicColumns(),
    showTableSetting: true,
    tableSetting: { fullScreen: true },
    showIndexColumn: true,
    indexColumnProps: {
      width: 60,
    },
    rowKey: 'name',
  });
  onMounted(() => {
    const intervalId = setInterval(reload, 1000);

    // 在组件销毁前清理定时器
    onBeforeUnmount(() => {
      clearInterval(intervalId);
    });
  });
</script>
