<template>
  <div>
    <a-tabs v-model:activeKey="activeKey" class="!m-4 !p-4 bg-white" animated @change="tabChange">
      <a-tab-pane key="sys" :tab="t('maintenance.coreBoardMap.sysMap')">
        <BasicTable @register="registerSysTable"
      /></a-tab-pane>

      <a-tab-pane key="User" :tab="tabTitle()">
        <BasicTable @register="registerUserTable">
          <template #toolbar>
            <a-button type="primary" @click="add()">
              {{ t('maintenance.coreBoardMap.add') }}
            </a-button>
          </template>
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'action'">
              <TableAction
                :actions="[
                  {
                    // label: '删除',
                    icon: 'ic:outline-delete-outline',
                    color: 'error',
                    tooltip: '删除',
                    popConfirm: {
                      title: '确认删除？',
                      confirm: handleDelete.bind(null, record),
                    },
                  },
                ]"
              />
            </template>
          </template>
        </BasicTable>
      </a-tab-pane>
    </a-tabs>
    <AddUserIp @register="registerModal" @success="handleSuccess" />
  </div>
</template>

<script lang="ts" setup>
  import { ref, nextTick, h } from 'vue';
  import { Tabs, Tooltip } from 'ant-design-vue';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { BasicTable, useTable, TableAction } from '/@/components/Table';
  import { getSysColumns } from './tableData';
  import { useModal } from '/@/components/Modal';
  import { getSysTables, getUserTables, DeleteUserTables } from '/@/api/maintenance/index';
  import AddUserIp from './AddUserIp.vue';

  const ATabs = Tabs;
  const ATabPane = Tabs.TabPane;
  const { t } = useI18n();
  const activeKey = ref('sys');
  const sys = ref();
  const [registerModal, { openModal }] = useModal();
  const tabChange = (value) => {
    nextTick(() => {
      if (value === 'sys') {
        sys.value as any;
      }
    });
  };
  const [registerUserTable, { reload }] = useTable({
    api: getUserTables,
    columns: getSysColumns(),
    showTableSetting: true,
    tableSetting: { fullScreen: true },
    showIndexColumn: true,
    actionColumn: {
      width: 160,
      title: '操作',
      dataIndex: 'action',
    },
    indexColumnProps: {
      width: 120,
    },
    pagination: false,
    rowKey: 'deviceSn',
  });
  const [registerSysTable] = useTable({
    api: getSysTables,
    columns: getSysColumns(),
    showTableSetting: false,
    tableSetting: { fullScreen: true },
    showIndexColumn: true,
    indexColumnProps: {
      width: 120,
    },
    pagination: false,
    rowKey: 'deviceSn',
  });

  async function add() {
    const res = await getSysTables();
    openModal(true, { res });
  }
  async function handleDelete(record) {
    await DeleteUserTables({ num: record.num });
    reload();
  }
  function handleSuccess() {
    reload();
  }
  function tabTitle() {
    const ATooltip = Tooltip;
    return h(
      ATooltip, // 组件名称
      {
        title: t('maintenance.coreBoardMap.msg'), // a-tooltip组件的title属性
        placement: 'right',
      },
      [
        h('span', t('maintenance.coreBoardMap.UserDefineMap')), // a-tooltip包裹的内容
      ],
    );
  }
</script>
