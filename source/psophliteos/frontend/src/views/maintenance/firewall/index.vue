<template>
  <div class="p-4">
    <EnvironmentBar ref="envBarRef" @env-ok="onEnvOk" />

    <a-tabs
      v-model:activeKey="activeKey"
      class="!p-4 bg-white"
      animated
      :disabled="!envOk"
    >
      <a-tab-pane key="intent" :tab="t('maintenance.firewall.tabIntent')" :disabled="!envOk">
        <Intent v-if="envOk" @apply="onApply" />
        <a-empty v-else :description="t('maintenance.firewall.envDisabledHint')" />
      </a-tab-pane>
      <a-tab-pane key="raw" :tab="t('maintenance.firewall.tabRaw')" :disabled="!envOk" v-if="advancedOpen">
        <Raw v-if="envOk" />
        <a-empty v-else :description="t('maintenance.firewall.envDisabledHint')" />
      </a-tab-pane>
      <a-tab-pane key="docker" :tab="t('maintenance.firewall.tabDocker')" :disabled="!envOk" v-if="advancedOpen">
        <Docker v-if="envOk" @apply="onApply" />
        <a-empty v-else :description="t('maintenance.firewall.envDisabledHint')" />
      </a-tab-pane>
    </a-tabs>

    <div class="mt-4 flex justify-end">
      <a-button v-if="!advancedOpen" @click="onOpenAdvanced">
        {{ t('maintenance.firewall.advancedOpen') }}
      </a-button>
      <a-button v-else danger @click="advancedOpen = false">
        {{ t('maintenance.firewall.advancedClose') }}
      </a-button>
    </div>

    <ApplyConfirm @register="registerApplyModal" @success="onApplySuccess" @rollback="onApplyRollback" />
  </div>
</template>

<script lang="ts" setup>
  import { ref } from 'vue';
  import { Tabs, Empty, Button, Modal } from 'ant-design-vue';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { useModal } from '/@/components/Modal';
  import EnvironmentBar from './EnvironmentBar.vue';
  import Intent from './Intent.vue';
  import Raw from './Raw.vue';
  import Docker from './Docker.vue';
  import ApplyConfirm from './ApplyConfirm.vue';

  const ATabs = Tabs;
  const ATabPane = Tabs.TabPane;
  const AEmpty = Empty;
  const AButton = Button;

  const { t } = useI18n();

  const activeKey = ref('intent');
  const envOk = ref(true);
  const envBarRef = ref<InstanceType<typeof EnvironmentBar> | null>(null);
  const advancedOpen = ref(false);

  const [registerApplyModal, { openModal: openApplyModal }] = useModal();

  function onEnvOk(ok: boolean) {
    envOk.value = ok;
    if (!ok) {
      advancedOpen.value = false;
    }
  }

  function onOpenAdvanced() {
    Modal.warning({
      title: t('maintenance.firewall.advancedWarningTitle'),
      content: t('maintenance.firewall.advancedWarningContent'),
      okText: t('maintenance.firewall.advancedWarningOk'),
      onOk: () => {
        advancedOpen.value = true;
        activeKey.value = 'raw';
      },
    });
  }

  function onApply(payload: { token: string; rollbackSeconds?: number }) {
    openApplyModal(true, {
      token: payload.token,
      rollbackSeconds: payload.rollbackSeconds ?? 300,
    });
  }

  function onApplySuccess() {}
  function onApplyRollback() {
    envBarRef.value?.reload?.();
  }
</script>
