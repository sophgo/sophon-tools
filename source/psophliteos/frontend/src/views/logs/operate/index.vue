<template>
  <BasicTable @register="registerTable" class="p-4">
    <template #form-custom> custom-slot </template>
  </BasicTable>
</template>
<script lang="ts" setup>
  import { BasicTable, useTable } from '/@/components/Table';
  import { getBasicColumns } from './tableData';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { getOperRecord } from '/@/api/logs/index';
  import { useDeviceInfo } from '/@/store/modules/overview';
  const deviceStore = useDeviceInfo();

  if (!deviceStore.deviceType) {
    deviceStore.getDeviceInfo();
  }
  const { t } = useI18n();
  // const operateType = [
  //   {
  //     label: t('logs.operate.operateType.login'),
  //     value: '/api/login',
  //   },

  //   {
  //     label: t('logs.operate.operateType.logout'),
  //     value: '/api/logout',
  //   },
  //   {
  //     label: t('logs.operate.operateType.alarm'),
  //     value: '/api/device/configure/alarm',
  //   },
  //   {
  //     label: t('logs.operate.operateType.basic'),
  //     value: '/api/device/basic',
  //   },
  //   {
  //     label: t('logs.operate.operateType.ip'),
  //     value: '/api/device/ip',
  //   },
  //   {
  //     label: t('logs.operate.operateType.systemUpdate'),
  //     value: '/api/device/ota/upgrade',
  //   },
  //   {
  //     label: t('logs.operate.operateType.UpgradeUpload'),
  //     value: '/api/device/ota/chunked',
  //   },
  //   {
  //     label: '控制板SSM升级',
  //     value: '/api/ssm/upgrade',
  //   },
  //   {
  //     label: 'sophliteos升级',
  //     value: '/api/upgrade',
  //   },

  //   // {
  //   //   label: t('logs.operate.operateType.coreUpgrade'),
  //   //   value: '/api/device/ota/upgrade',
  //   // },
  //   // {
  //   //   label: t('logs.operate.operateType.rollback'),
  //   //   value: '/api/device/ota/rollback',
  //   // },
  // ];
  const [registerTable] = useTable({
    title: t('logs.operate.title'),
    api: getOperRecord,
    columns: getBasicColumns(),
    // useSearchForm: true,
    // formConfig: {
    //   labelWidth: 120,
    //   schemas: [
    //     {
    //       field: 'operationType',
    //       label: t('logs.operate.filter.name'),
    //       component: 'Select',
    //       componentProps: {
    //         options: operateType,
    //       },
    //       colProps: {
    //         xl: 12,
    //         xxl: 8,
    //       },
    //     },
    //     {
    //       field: 'username',
    //       label: t('logs.operate.filter.people'),
    //       component: 'Input',
    //       colProps: {
    //         xl: 12,
    //         xxl: 8,
    //       },
    //     },
    //     {
    //       field: 'operationIp',
    //       label: t('logs.operate.filter.ip'),
    //       component: 'Input',
    //       colProps: {
    //         xl: 12,
    //         xxl: 8,
    //       },
    //     },
    //     {
    //       field: 'startTime',
    //       label: t('sys.table.startTime'),
    //       component: 'DatePicker',
    //       componentProps: {
    //         'show-time': true,
    //       },
    //       colProps: {
    //         xl: 12,
    //         xxl: 8,
    //       },
    //     },
    //     {
    //       field: 'endTime',
    //       label: t('sys.table.endTime'),
    //       component: 'DatePicker',
    //       componentProps: {
    //         'show-time': true,
    //       },
    //       colProps: {
    //         xl: 12,
    //         xxl: 8,
    //       },
    //     },
    //   ],
    // },
    showTableSetting: true,
    tableSetting: { fullScreen: true },
    showIndexColumn: true,
    indexColumnProps: {
      width: 60,
    },
    rowKey: 'recordId',
  });
</script>
