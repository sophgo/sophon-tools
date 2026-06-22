<template>
  <a-tabs v-model:activeKey="activeKey" class="!m-4 !p-4 bg-white" animated @change="tabChange">
    <a-tab-pane key="control" :tab="controlText">
      <ControlForm :isSsm="true" />
    </a-tab-pane>
    <a-tab-pane
      key="core"
      :tab="t('maintenance.systemUpdate.coreBoardUpdate')"
      v-if="!deviceStore.isSingleBoard"
    >
      <CoreForm :isSsm="true" ref="core" />
    </a-tab-pane>
    <a-tab-pane key="upgradeList" :tab="t('maintenance.ssmUpdate.list')">
      <List />
    </a-tab-pane>
  </a-tabs>
</template>
<script lang="ts" setup>
  import { ref, computed, nextTick } from 'vue';
  import { Tabs } from 'ant-design-vue';
  import CoreForm from '../sysSoft/components/coreForm.vue';
  import ControlForm from '../sysSoft/components/controlForm.vue';
  import List from './list.vue';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { useDeviceInfo } from '/@/store/modules/overview';
  const deviceStore = useDeviceInfo();

  const { t } = useI18n();

  const ATabs = Tabs;
  const ATabPane = Tabs.TabPane;

  const activeKey = ref('control');

  const controlText = computed(() => {
    return !deviceStore.isSingleBoard
      ? t('maintenance.systemUpdate.systemUpdate')
      : t('maintenance.systemUpdate.localUpdate1');
  });
  // 切换tab重置表单验证
  const core = ref();
  const tabChange = (value) => {
    nextTick(() => {
      if (value === 'core') {
        (core.value as any).resetForm();
      }
    });
  };
</script>
