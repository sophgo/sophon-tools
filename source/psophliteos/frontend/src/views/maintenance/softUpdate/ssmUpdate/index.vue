<template>
  <PageWrapper title="SSM" :content="t('routes.dashboard.content.ssmContent')">
    <div style="display: flex; flex-direction: row; margin-bottom: 20px">
      <div style="background-color: white" v-if="!deviceStore.isSingleBoard">
        <ControlForm :isSsm="true" />
      </div>
      <div style="background-color: white; width: 100%" v-else>
        <ControlForm :isSsm="true" />
      </div>
      <div
        v-if="!deviceStore.isSingleBoard"
        style="background-color: white; margin-left: 20px; width: 100%"
      >
        <CoreForm ref="core" :isSsm="true"
      /></div>
    </div>
    <List />
  </PageWrapper>
</template>
<script lang="ts" setup>
  import { PageWrapper } from '/@/components/Page';
  import CoreForm from '../../sysSoft/components/coreForm.vue';
  import ControlForm from '../../sysSoft/components/controlForm.vue';
  import List from './list.vue';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { useDeviceInfo } from '/@/store/modules/overview';
  const deviceStore = useDeviceInfo();

  const { t } = useI18n();
</script>
