<template>
  <BasicTable @register="registerTable" style="max-height: 100vh">
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'chipIndex'">
        {{ record.chipIndex === -1 ? '控制板' : '核心板' + record.chipIndex }}
      </template>
    </template>
  </BasicTable>
</template>
<script lang="ts" setup>
  import { BasicTable, useTable } from '/@/components/Table';
  import { getBasicColumns } from './tableData';
  import { ssmStatusApi } from '/@/api/maintenance/index';
  // import { useI18n } from '/@/hooks/web/useI18n';
  // const { t } = useI18n();

  const [registerTable] = useTable({
    api: ssmStatusApi,
    columns: getBasicColumns(),
    showTableSetting: true,
    tableSetting: { fullScreen: true },
    showIndexColumn: false,
    indexColumnProps: {
      width: 60,
    },
    pagination: {
      pageSize: 20,
    },
    canResize: false,
    rowKey: 'deviceSn',
  });
</script>
