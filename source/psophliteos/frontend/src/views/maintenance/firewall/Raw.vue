<template>
  <div class="firewall-raw">
    <a-card :title="t('maintenance.firewall.addRaw')" size="small" class="mb-3">
      <div class="flex flex-wrap items-center" style="gap: 8px">
        <span class="w-20 text-right">chain</span>
        <a-select
          v-model:value="chain"
          style="width: 160px"
          :options="rawChainOptions"
        />
        <span class="text-right" style="width: 56px">args</span>
        <a-input
          v-model:value="args"
          style="width: 360px"
          :placeholder="t('maintenance.firewall.rawArgsPh')"
          @press-enter="handleAdd"
        />
        <a-button type="primary" :loading="adding" @click="handleAdd">
          {{ t('maintenance.firewall.add') }}
        </a-button>
      </div>
      <div class="mt-1 text-gray-400 text-xs">{{ t('maintenance.firewall.rawArgsTip') }}</div>
    </a-card>

    <BasicTable @register="registerTable">
      <template #bodyCell="{ column, record }">
        <template v-if="column.dataIndex === 'action'">
          <TableAction
            :actions="[
              {
                icon: 'ic:outline-delete-outline',
                color: 'error',
                tooltip: t('maintenance.firewall.delete'),
                popConfirm: {
                  title: t('maintenance.firewall.confirmDelete'),
                  confirm: handleDelete.bind(null, record),
                },
              },
            ]"
          />
        </template>
      </template>
    </BasicTable>
  </div>
</template>

<script lang="ts" setup>
  import { ref } from 'vue';
  import { Card, Select, Input, message } from 'ant-design-vue';
  import { BasicTable, useTable, TableAction } from '/@/components/Table';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { getRawColumns, rawChainOptions } from './tableData';
  import {
    getRawRules,
    addRawRule,
    deleteRawRule,
    type LiveRule,
  } from '/@/api/maintenance/firewall';

  const ACard = Card;
  const ASelect = Select;
  const AInput = Input;

  const { t } = useI18n();

  const chain = ref('INPUT');
  const args = ref('');
  const adding = ref(false);

  const [registerTable, { reload }] = useTable({
    api: getRawRules,
    columns: getRawColumns(),
    showIndexColumn: false,
    pagination: { pageSize: 50, showSizeChanger: true },
    rowKey: (r: LiveRule) => String(r.num),
    actionColumn: {
      width: 80,
      title: t('maintenance.firewall.action'),
      dataIndex: 'action',
    },
  });

  function parseArgs(s: string): string[] {
    return s
      .trim()
      .split(/\s+/)
      .filter((x) => x.length > 0);
  }

  async function handleAdd() {
    const argList = parseArgs(args.value);
    if (!chain.value || argList.length === 0) {
      message.warning(t('maintenance.firewall.rawArgsRequired'));
      return;
    }
    adding.value = true;
    try {
      await addRawRule({ chain: chain.value, args: argList });
      message.success(t('maintenance.firewall.addOk'));
      args.value = '';
      reload();
    } catch (e: any) {
      message.error(e?.message || t('maintenance.firewall.addFail'));
    } finally {
      adding.value = false;
    }
  }

  async function handleDelete(record: LiveRule) {
    try {
      await deleteRawRule(record.target || 'INPUT', record.num);
      message.success(t('maintenance.firewall.deleteOk'));
      reload();
    } catch (e: any) {
      message.error(e?.message || t('maintenance.firewall.deleteFail'));
    }
  }
</script>
