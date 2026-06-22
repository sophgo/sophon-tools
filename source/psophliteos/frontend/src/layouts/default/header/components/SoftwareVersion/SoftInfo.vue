<template>
  <a-card :loading="loading">
    <a-descriptions bordered :column="2">
      <a-descriptions-item :label="t('overview.softInfo.buildName')">{{
        softwareInfo.buildname
      }}</a-descriptions-item>
      <a-descriptions-item :label="t('overview.softInfo.buildTime')">{{
        softwareInfo.buildtime
      }}</a-descriptions-item>
      <a-descriptions-item :label="t('overview.softInfo.versionTitle')">
        <div class="software">
          <span class="title">{{ t('overview.softInfo.branch') }}</span>
          <span class="title">{{ t('overview.softInfo.commit') }}</span>
          <template v-for="item in softwareInfo.modules" :key="item.module">
            <span class="module">{{ item.module }}</span>
            <span class="commit">{{ item.commit }}</span>
          </template>
        </div>
      </a-descriptions-item>
    </a-descriptions>
  </a-card>
</template>
<script lang="ts" setup>
  // @ts-nocheck
  import { ref, onMounted } from 'vue';
  import { Card, Descriptions } from 'ant-design-vue';
  import { getSoftwareInfoApi } from '/@/api/overview/index';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { reactive } from 'vue';
  const { t } = useI18n();

  const ACard = Card;
  const ADescriptions = Descriptions;
  const ADescriptionsItem = Descriptions.Item;

  const loading = ref(false);

  const softwareInfo = reactive({
    buildname: '',
    buildtime: '',
    modules: [],
  });

  onMounted(async () => {
    loading.value = true;
    const result = await getSoftwareInfoApi();
    loading.value = false;
    if (result) {
      Object.keys(softwareInfo).forEach((key) => {
        softwareInfo[key] = result[key];
      });
    }
  });
</script>

<style lang="less" scoped>
  .software {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: repeat(4, 30px);
    grid-column-gap: 20px;
    align-items: center;

    .title {
      background-color: #fafafa;
      border: 1px solid #f0f0f0;
      text-align: center;
    }

    .commit,
    .module {
      border-bottom: 1px dashed #ccc;
      padding: 4px 0;
      text-align: center;
    }
  }
</style>
