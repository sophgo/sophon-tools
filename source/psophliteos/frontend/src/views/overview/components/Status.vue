<template>
  <Card
    :tab-list="tabListTitle"
    v-bind="$attrs"
    :active-tab-key="activeKey"
    :loading="loading"
    @tab-change="onTabChange"
  >
    <p v-if="activeKey === 'tab1'">
      <Usage />
    </p>
    <p v-if="activeKey === 'tab2'">
      <ChipTemperature />
    </p>
    <!-- <p v-if="activeKey === 'tab3'">
      <FanSpeed />
    </p> -->
  </Card>
</template>
<script lang="ts" setup>
  import { ref } from 'vue';
  import { Card } from 'ant-design-vue';
  import Usage from './Usage.vue';
  import ChipTemperature from './ChipTemperature.vue';
  // import FanSpeed from './FanSpeed.vue';
  //SE6 SE8去掉风扇
  import { useI18n } from '/@/hooks/web/useI18n';
  const { t } = useI18n();

  defineProps({
    loading: Boolean,
  });
  const activeKey = ref('tab1');

  const tabListTitle = [
    {
      key: 'tab1',
      tab: t('overview.usage'),
    },
    {
      key: 'tab2',
      tab: t('overview.coreTemperature'),
    },
    // {
    //   key: 'tab3',
    //   tab: t('overview.fanSpeed'),
    // },
  ];

  function onTabChange(key) {
    activeKey.value = key;
  }
</script>
