<template>
  <BasicTable @register="registerTable">
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'componentType'">
        {{ t(`logs.${record.componentType}`) }}
      </template>
    </template>
  </BasicTable>
</template>
<script lang="ts" setup>
  import { BasicTable, useTable } from '/@/components/Table';
  import { getBasicColumns } from './tableData';
  import { getAlarmRecord } from '/@/api/logs/index';

  import { useI18n } from '/@/hooks/web/useI18n';
  const { t } = useI18n();

  import { useDeviceInfo } from '/@/store/modules/overview';
  const deviceStore = useDeviceInfo();

  if (!deviceStore.deviceType) {
    deviceStore.getDeviceInfo();
  }
  // enum WarningTypes {
  //   'cpu' = 'CPU',
  //   'memory' = '内存',
  //   'disk' = '磁盘',
  //   'netCard' = '网卡',
  //   'board' = '板卡',
  //   'chip' = '芯片',
  // }
  const WarningType = [
    {
      label: 'CPU',
      value: 'cpu',
    },
    {
      label: t('logs.memory'),
      value: 'memory',
    },
    {
      label: t('logs.disk'),
      value: 'disk',
    },
    // {
    //   label: t('logs.netCard'),
    //   value: 'netCard',
    // },
    {
      label: t('logs.board'),
      value: 'board',
    },
    {
      label: t('logs.chip'),
      value: 'chip',
    },
  ];
  const [registerTable] = useTable({
    title: t('logs.warning.title'),
    api: getAlarmRecord,
    columns: getBasicColumns(),
    useSearchForm: true,
    formConfig: {
      labelWidth: 120,
      schemas: [
        {
          field: 'componentType',
          label: t('logs.warning.type'),
          component: 'Select',
          componentProps: {
            options: WarningType,
          },
          colProps: {
            xl: 12,
            xxl: 8,
            span: 12,
          },
        },
        {
          field: 'startTime',
          label: t('sys.table.startTime'),
          component: 'DatePicker',
          componentProps: {
            'show-time': true,
          },
          colProps: {
            xl: 12,
            xxl: 8,
            span: 12,
          },
        },
        {
          field: 'endTime',
          label: t('sys.table.endTime'),
          component: 'DatePicker',
          componentProps: {
            'show-time': true,
          },
          colProps: {
            xl: 12,
            xxl: 8,
            span: 12,
          },
        },
      ],
    },
    showTableSetting: true,
    tableSetting: { fullScreen: true },
    showIndexColumn: true,
    indexColumnProps: {
      width: 60,
    },
    rowKey: 'ID',
  });
</script>
