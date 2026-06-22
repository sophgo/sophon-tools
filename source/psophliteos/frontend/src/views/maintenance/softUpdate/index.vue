<template>
  <PageWrapper title="LiteOS" :content="t('routes.dashboard.content.liteContent')">
    <a-tabs v-model:activeKey="activeKey" class="!m-2 !p-2 bg-white" animated>
      <a-tab-pane key="control" :tab="controlText">
        <ControlForm :isSoftware="true" />
      </a-tab-pane>
    </a-tabs>
  </PageWrapper>
</template>
<script lang="ts" setup>
  import { ref } from 'vue';
  import { PageWrapper } from '/@/components/Page';
  import { Tabs } from 'ant-design-vue';
  import ControlForm from '../sysSoft/components/controlForm.vue';
  import { useI18n } from '/@/hooks/web/useI18n';
  // import { useDeviceInfo } from '/@/store/modules/overview';
  // const deviceStore = useDeviceInfo();

  const { t } = useI18n();

  const ATabs = Tabs;
  const ATabPane = Tabs.TabPane;

  const activeKey = ref('control');

  const controlText = t('maintenance.systemUpdate.softwareUpdate');
</script>
