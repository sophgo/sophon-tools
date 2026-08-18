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
  import { ref, h } from 'vue';
  import { Card, Select, Switch, Modal, message } from 'ant-design-vue';
  import { ExclamationCircleOutlined } from '@ant-design/icons-vue';
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
    getHazardChallenge,
    type Intent,
    type HazardChallenge,
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

  // describeIntent 生成待执行操作的描述文本（确认弹窗展示）。
  function describeIntent(type: string, raw: any, enabled?: boolean): string {
    const names: Record<string, string> = {
      port_allow: t('maintenance.firewall.portAllow'),
      port_deny: t('maintenance.firewall.portDeny'),
      rate_limit: '速率限制',
      ip_whitelist: 'IP 白名单',
      ip_blacklist: 'IP 黑名单',
      icmp: 'ICMP',
    };
    let desc = names[type] || type;
    if (typeof raw === 'string') {
      try {
        raw = JSON.parse(raw);
      } catch {
        /* keep raw */
      }
    }
    if (raw && typeof raw === 'object') {
      desc += `: ${raw.port ?? ''} ${raw.proto ?? ''} ${raw.src ?? ''}`.trim();
    }
    if (typeof enabled === 'boolean') {
      desc += enabled ? '（启用）' : '（禁用）';
    }
    return desc;
  }

  // confirmHighRisk MYS-389 二次确认：取一次性确认码 → 弹确认框展示码 → 用户确认后执行。
  async function confirmHighRisk(desc: string, doIt: (confirm: string) => Promise<void>): Promise<boolean> {
    let ch: HazardChallenge;
    try {
      ch = await getHazardChallenge();
    } catch (e: any) {
      message.error(e?.message || t('maintenance.firewall.challengeFail'));
      return false;
    }
    return await new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: t('maintenance.firewall.highRiskConfirmTitle'),
        icon: h(ExclamationCircleOutlined),
        width: 480,
        content: () =>
          h('div', [
            h('p', { style: { 'font-weight': 550 } }, desc),
            h(
              'p',
              { style: { color: '#fa8c16', margin: '8px 0 4px', 'font-size': '13px' } },
              t('maintenance.firewall.highRiskConfirmContent', {
                code: ch.code,
                secs: ch.expiresInSecs ?? 120,
              }),
            ),
          ]),
        onOk: async () => {
          try {
            await doIt(ch.code);
            resolve(true);
          } catch (e: any) {
            message.error(e?.response?.data?.error_message || e?.message || t('maintenance.firewall.actionFail'));
            resolve(false);
          }
        },
        onCancel: () => resolve(false),
      });
    });
  }

  // rebuildWithConfirm 携带确认码重建防火墙；码过期（403）时自动重新取码重试一次，
  // 保证与用户已确认的操作语义一致，避免因取码到执行间隔超时导致规则残留。
  async function rebuildWithConfirm(initialCode: string): Promise<void> {
    try {
      await rebuildFirewall(initialCode);
    } catch (e: any) {
      const msg = e?.response?.data?.error_message || e?.message || '';
      if (msg.includes('confirmation required')) {
        const ch2 = await getHazardChallenge();
        await rebuildFirewall(ch2?.code || '');
        return;
      }
      throw e;
    }
  }

  async function handleAdd() {
    try {
      const values = await validate();
      adding.value = true;
      const type = currentPreset.value;
      const ok = await confirmHighRisk(`${t('maintenance.firewall.add')}: ${describeIntent(type, values)}`, async (confirm) => {
        await addIntent({ type, params: buildParams(values), enabled: true });
        await rebuildWithConfirm(confirm);
      });
      if (ok) {
        message.success(t('maintenance.firewall.addOk'));
        await resetFields();
      }
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
      const ok = await confirmHighRisk(describeIntent(record.type, record.params, checked), async (confirm) => {
        await addIntent({ ...record, enabled: checked });
        await rebuildWithConfirm(confirm);
      });
      if (ok) {
        message.success(checked ? t('maintenance.firewall.enabledOk') : t('maintenance.firewall.disabledOk'));
      }
      reload(); // 取消时回滚开关显示
    } catch (e: any) {
      message.error(e?.message || t('maintenance.firewall.toggleFail'));
      reload();
    }
  }

  async function handleDelete(record: Intent) {
    if (!record.id) return;
    const ok = await confirmHighRisk(t('maintenance.firewall.delete') + ': ' + describeIntent(record.type, record.params, record.enabled), async (confirm) => {
      await deleteIntent(record.id);
      await rebuildWithConfirm(confirm);
    });
    if (ok) {
      message.success(t('maintenance.firewall.deleteOk'));
    }
    reload();
  }
</script>
