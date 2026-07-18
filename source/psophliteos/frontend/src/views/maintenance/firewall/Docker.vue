<template>
  <div class="firewall-docker">
    <a-card :title="t('maintenance.firewall.addDocker')" size="small" class="mb-3">
      <div class="mb-3 flex items-center" style="gap: 8px">
        <span class="w-24 text-right">{{ t('maintenance.firewall.dockerScene') }}</span>
        <a-select
          v-model:value="currentScene"
          style="width: 280px"
          :options="dockerSceneOptions"
          @change="onSceneChange"
        />
      </div>
      <BasicForm @register="registerForm" />
      <div class="mt-2 flex justify-end" style="gap: 8px">
        <a-button @click="resetForm">{{ t('maintenance.firewall.reset') }}</a-button>
        <a-button type="primary" :loading="adding" @click="handleAdd">
          {{ t('maintenance.firewall.add') }}
        </a-button>
      </div>
    </a-card>

    <BasicTable @register="registerTable">
      <template #toolbar>
        <a-button type="primary" :loading="applying" @click="handleApply">
          {{ t('maintenance.firewall.apply') }}
        </a-button>
      </template>
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

    <BasicModal
      @register="registerRiskModal"
      :title="t('maintenance.firewall.riskTitle')"
      width="560px"
      :ok-text="t('maintenance.firewall.forceApply')"
      :cancel-text="t('maintenance.firewall.cancel')"
      @ok="handleForceApply"
    >
      <a-alert type="warning" show-icon :message="t('maintenance.firewall.riskDetected')" />
      <ul class="mt-2">
        <li v-for="(r, i) in risks" :key="i">
          <span class="font-medium">[{{ r.mode }}]</span> {{ r.description }}
        </li>
      </ul>
    </BasicModal>
  </div>
</template>

<script lang="ts" setup>
  import { ref } from 'vue';
  import { Card, Select, Switch, message } from 'ant-design-vue';
  import { BasicTable, useTable, TableAction } from '/@/components/Table';
  import { BasicForm, useForm } from '/@/components/Form/index';
  import { BasicModal, useModal } from '/@/components/Modal';
  import { useI18n } from '/@/hooks/web/useI18n';
  import {
    getDockerColumns,
    getDockerParamSchema,
    dockerSceneOptions,
  } from './tableData';
  import {
    getDockerRules,
    addDockerRule,
    deleteDockerRule,
    applyFirewall,
    isRiskEnvelope,
    envelopeErr,
    extractRisks,
    type DockerRule,
    type Risk,
  } from '/@/api/maintenance/firewall';

  const ACard = Card;
  const ASelect = Select;
  const ASwitch = Switch;

  const { t } = useI18n();
  const emit = defineEmits<{
    (e: 'apply', payload: { token: string; rollbackSeconds?: number }): void;
  }>();

  const adding = ref(false);
  const applying = ref(false);
  const currentScene = ref<string>('ext_to_container');
  const risks = ref<Risk[]>([]);

  const [registerForm, { setProps: setFormProps, resetFields, validate }] = useForm({
    labelWidth: 100,
    baseColProps: { span: 24 },
    schemas: getDockerParamSchema(currentScene.value),
    showActionButtonGroup: false,
  });

  async function onSceneChange(scene: any) {
    currentScene.value = scene as string;
    await setFormProps({ schemas: getDockerParamSchema(scene as string) });
  }

  const [registerTable, { reload }] = useTable({
    api: getDockerRules,
    columns: getDockerColumns(),
    showIndexColumn: false,
    pagination: false,
    rowKey: 'id',
    actionColumn: {
      width: 80,
      title: t('maintenance.firewall.action'),
      dataIndex: 'action',
    },
  });

  const [registerRiskModal, { openModal: openRiskModal, setModalProps: setRiskModalProps, closeModal: closeRiskModal }] =
    useModal();

  async function handleAdd() {
    try {
      const values = await validate();
      adding.value = true;
      await addDockerRule({
        scene: currentScene.value,
        params: JSON.stringify(values),
        enabled: true,
      });
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

  async function handleToggle(record: DockerRule, checked: boolean) {
    try {
      await addDockerRule({ ...record, enabled: checked });
      message.success(checked ? t('maintenance.firewall.enabledOk') : t('maintenance.firewall.disabledOk'));
      reload();
    } catch (e: any) {
      message.error(e?.message || t('maintenance.firewall.toggleFail'));
      reload();
    }
  }

  async function handleDelete(record: DockerRule) {
    if (!record.id) return;
    try {
      await deleteDockerRule(record.id);
      message.success(t('maintenance.firewall.deleteOk'));
      reload();
    } catch (e: any) {
      message.error(e?.message || t('maintenance.firewall.deleteFail'));
    }
  }

  async function handleApply() {
    applying.value = true;
    try {
      const data = await applyFirewall({ force: false });
      if (data.code === 0 && data.result) {
        emit('apply', { token: data.result.token, rollbackSeconds: data.result.rollbackSeconds ?? 300 });
      } else if (isRiskEnvelope(data)) {
        risks.value = extractRisks(data);
        openRiskModal(true);
      } else {
        message.error(envelopeErr(data) || t('maintenance.firewall.applyFail'));
      }
    } catch (e: any) {
      message.error(e?.message || t('maintenance.firewall.applyFail'));
    } finally {
      applying.value = false;
    }
  }

  async function handleForceApply() {
    try {
      setRiskModalProps({ confirmLoading: true });
      const data = await applyFirewall({ force: true });
      if (data.code === 0 && data.result) {
        closeRiskModal();
        emit('apply', { token: data.result.token, rollbackSeconds: data.result.rollbackSeconds ?? 300 });
      } else if (isRiskEnvelope(data)) {
        risks.value = extractRisks(data);
      } else {
        message.error(envelopeErr(data) || t('maintenance.firewall.applyFail'));
      }
    } catch (e: any) {
      message.error(e?.message || t('maintenance.firewall.applyFail'));
    } finally {
      setRiskModalProps({ confirmLoading: false });
    }
  }
</script>
