<template>
  <PageWrapper
    :title="t('routes.dashboard.sysSoft')"
    :content="t('routes.dashboard.content.sysContent')"
  >
    <div style="display: flex; flex-direction: row; margin-bottom: 20px">
      <div style="background-color: white; padding-bottom: 10px" v-if="!deviceStore.isSingleBoard">
        <ControlForm :isSysSoft="true" />
      </div>
      <div style="background-color: white; width: 100%" v-else>
        <ControlForm :isSysSoft="true" />
      </div>
      <div
        style="background-color: white; margin-left: 20px; width: 100%"
        v-if="!deviceStore.isSingleBoard"
      >
        <CoreForm ref="core" :isSysSoft="true" />
      </div>
    </div>
    <List />
  </PageWrapper>
</template>
<script lang="ts" setup>
  import { PageWrapper } from '/@/components/Page';
  import CoreForm from './components/coreForm.vue';
  import ControlForm from './components/controlForm.vue';
  import List from './components/list.vue';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { useDeviceInfo } from '/@/store/modules/overview';
  const deviceStore = useDeviceInfo();

  const { t } = useI18n();
</script>
