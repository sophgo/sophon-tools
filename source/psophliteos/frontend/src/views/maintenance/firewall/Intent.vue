<template>
  <div class="firewall-intent">
    <a-card :title="t('maintenance.firewall.addIntent')" size="small" class="mb-3">
      <div class="mb-3 flex items-center" style="gap: 8px">
        <span class="w-24 text-right">{{ t('maintenance.firewall.intentType') }}</span>
        <a-select
          v-model:value="currentPreset"
          style="width: 280px"
          :options="intentPresetOptions"
          @change="onPresetChange"
        />
      </div>
      <BasicForm @register="registerForm" />
      <div class="mb-2" style="color: #faad14; font-size: 12px; line-height: 1.6">
        提示：拒绝/限速规则会命中保护端口（SSH 等管理端口）。守卫会拦截全网段的保护端口拒绝；
        但指定源网段的拒绝（如 10/8、172.16/12、192.168/16 内的管理机）仍可能锁死管理通道，
        且守卫依赖对保护端口的实时探测（探测不到时不会拦截），请谨慎配置。
      </div>
      <div class="mt-2 flex justify-end" style="gap: 8px">
        <a-button @click="resetForm">{{ t('maintenance.firewall.reset') }}</a-button>
        <a-button type="primary" :loading="adding" @click="handleAdd">
          {{ t('maintenance.firewall.add') }}
        </a-button>
      </div>
    </a-card>

    <BasicTable @register="registerTable">
      <template #bodyCell="{ column, record }">
        <template v-if="column.dataIndex === 'enabled'">
          <a-switch
            :checked="record.enabled"
            @change="(v) => handleToggle(record, v)"
          />
        </template>
        <template v-else-if="column.dataIndex === 'action'">
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
  import { Card, Select, Switch, message } from 'ant-design-vue';
  import { BasicTable, useTable, TableAction } from '/@/components/Table';
  import { BasicForm, useForm } from '/@/components/Form/index';
  import { useI18n } from '/@/hooks/web/useI18n';
  import {
    getIntentColumns,
    getIntentParamSchema,
    intentPresetOptions,
  } from './tableData';
  import {
    getIntents,
    addIntent,
    deleteIntent,
    rebuildFirewall,
    type Intent,
  } from '/@/api/maintenance/firewall';

  const ACard = Card;
  const ASelect = Select;
  const ASwitch = Switch;

  const { t } = useI18n();

  const adding = ref(false);
  const currentPreset = ref<string>('port_allow');

  const [registerForm, { setProps: setFormProps, resetFields, validate }] = useForm({
    labelWidth: 100,
    baseColProps: { span: 24 },
    schemas: getIntentParamSchema(currentPreset.value),
    showActionButtonGroup: false,
  });

  async function onPresetChange(preset: any) {
    currentPreset.value = preset as string;
    await setFormProps({ schemas: getIntentParamSchema(preset as string) });
  }

  const [registerTable, { reload }] = useTable({
    api: getIntents,
    columns: getIntentColumns(),
    showIndexColumn: false,
    pagination: false,
    rowKey: 'id',
    actionColumn: {
      width: 80,
      title: t('maintenance.firewall.action'),
      dataIndex: 'action',
    },
  });

  function buildParams(values: any): string {
    return JSON.stringify(values);
  }

  async function handleAdd() {
    try {
      const values = await validate();
      adding.value = true;
      await addIntent({
        type: currentPreset.value,
        params: buildParams(values),
        enabled: true,
      });
      await rebuildFirewall();
      message.success(t('maintenance.firewall.addOk'));
      await resetFields();
      reload();
    } catch (e: any) {
      if (e?.message) message.error(e.message);
    } finally {
      adding.value = false;
    }
  }

  function resetForm() {
    resetFields();
  }

  async function handleToggle(record: Intent, checked: boolean) {
    try {
      await addIntent({ ...record, enabled: checked });
      await rebuildFirewall();
      message.success(checked ? t('maintenance.firewall.enabledOk') : t('maintenance.firewall.disabledOk'));
      reload();
    } catch (e: any) {
      message.error(e?.message || t('maintenance.firewall.toggleFail'));
      reload();
    }
  }

  async function handleDelete(record: Intent) {
    if (!record.id) return;
    try {
      await deleteIntent(record.id);
      await rebuildFirewall();
      message.success(t('maintenance.firewall.deleteOk'));
      reload();
    } catch (e: any) {
      message.error(e?.message || t('maintenance.firewall.deleteFail'));
    }
  }
</script>
