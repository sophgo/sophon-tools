<template>
  <div class="p-24px">
    <CircleGrid :grid-list="gridList" class="se5-grid" />
    <a-row class="se5-row">
      <a-col :xs="24" :lg="12">
        <a-descriptions :title="t('overview.basicInfor')" bordered :column="1">
          <a-descriptions-item :label="t('overview.deviceName')">
            <span class="editName">
              <span v-if="!edit">{{ deviceInfo.deviceName }}</span>
              <a-input
                v-if="edit"
                v-model:value="deviceName"
                ref="deviceNameInput"
                @blur="handleBlur"
                @keyup.enter.stop="handleBlur1"
              />
              <a-tooltip :title="title" placement="right" :visible="editType">
                <EditOutlined
                  @click="toggleEdit"
                  v-if="!edit"
                  @mouseenter="editType = true"
                  @mouseleave="editType = false"
                />
              </a-tooltip>
            </span>
          </a-descriptions-item>
          <a-descriptions-item :label="t('overview.device.type')">{{
            originData.deviceType
          }}</a-descriptions-item>
          <a-descriptions-item :label="t('overview.device.sn')">{{
            originData.deviceSn
          }}</a-descriptions-item>
          <a-descriptions-item :label="t('overview.device.sdkVersion')">{{
            originData.sdkVersion
          }}</a-descriptions-item>
          <a-descriptions-item :label="t('overview.buildTime')">{{
            originData.bmssmVersion
          }}</a-descriptions-item>
          <a-descriptions-item label="WAN IP">{{ originData.wanIp }}</a-descriptions-item>
          <a-descriptions-item label="LAN IP">
            {{ originData.lanIp.split(',')[0] || '' }}
            <br />
            {{ originData.lanIp.split(',')[1] || '' }}
          </a-descriptions-item>
          <a-descriptions-item :label="t('overview.device.runningTime')">
            <a-badge status="processing" :text="dynTime" />
          </a-descriptions-item>
          <a-descriptions-item :label="t('overview.operatingSystem')">{{
            originData.operatingSystem
          }}</a-descriptions-item>
          <a-descriptions-item
            v-for="item in originData.netCard"
            :label="t('overview.netCard') + item.name"
            :key="item.ip"
          >
            {{ t('overview.bandwidth') + '：' + item.bandwidth + t('overview.bandwidthUnit') }}
            <br />
            {{ t('overview.ip') + '：' + item.ip }}
            <br />
            {{ t('overview.mac') + '：' + item.mac }}
          </a-descriptions-item>
        </a-descriptions>
      </a-col>
      <a-col :xs="24" :lg="12" class="!flex items-center">
        <a-row class="w-full">
          <a-col :xs="24" :md="24" :xl="24">
            <GaugeChart
              :value="deviceInfo.temperature"
              :unit="t('overview.coreTemperature') + '（℃）'"
            />
          </a-col>
          <!-- <a-col :xs="24" :md="24" :xl="12">
            <GaugeChart
              :value="+(Math.max(0, deviceInfo.fanSpeed || 0) / 1000).toFixed(0)"
              :colors="['#80B1F9', '#0C33F5']"
              :max="20"
              :unit="t('overview.fanSpeed') + '（x1000r/min）'"
            />
          </a-col> -->
        </a-row>
      </a-col>
    </a-row>
  </div>
</template>
<script lang="ts" setup>
  import { ref, computed, onUnmounted, nextTick } from 'vue';
  import { Descriptions, Row, Col, Badge, Tooltip } from 'ant-design-vue';
  import { storeToRefs } from 'pinia';
  import { useDeviceInfo } from '/@/store/modules/overview';
  import { useI18n } from '/@/hooks/web/useI18n';
  import CircleGrid from './components/CircleGrid.vue';
  import GaugeChart from './components/Gauge.vue';
  import { getFormatTime } from '/@/utils/dateUtil';
  import { EditOutlined } from '@ant-design/icons-vue';
  import { setDeviceInfoApi } from '/@/api/overview/index';

  const { t } = useI18n();

  const ADescriptions = Descriptions;
  const ATooltip = Tooltip;
  const ADescriptionsItem = Descriptions.Item;
  const ARow = Row;
  const ACol = Col;
  const ABadge = Badge;
  const title = t('overview.device.editType');
  const loading = ref(false);
  const deviceInfoStore = useDeviceInfo();
  const { originData, deviceInfo } = storeToRefs(deviceInfoStore);
  if (!originData.value.deviceSn) {
    loading.value = true;
    deviceInfoStore.getDeviceInfo().then(() => {
      loading.value = false;
    });
  }

  const gridList = computed(() => {
    if (!originData.value.cpu) {
      return [];
    }
    return [
      {
        title: t('overview.cpu'),
        usage: originData.value.cpu.usage,
        text: `${originData.value.cpu.cores}${t('overview.core')}${
          originData.value.cpu.frequency / 1000
        }GHz`,
      },
      {
        title: t('overview.memory'),
        usage: originData.value.memory.usage,
        total: originData.value.memory.total,
      },
      {
        title: t('overview.disk'),
        usage: originData.value.disk[0].usage,
        total: originData.value.disk[0].total,
      },
      {
        title: t('overview.tpu'),
        usage: originData.value?.coreComputingUnit?.board
          ? originData.value?.coreComputingUnit?.board[0].chip[0].tpuUtililizationRate
          : 0,
        text:
          'INT8 ' +
          (originData.value?.coreComputingUnit?.board
            ? originData.value?.coreComputingUnit?.board[0].chip[0].theoretialCalculationCapacity
            : 0) +
          'TOPS',
      },
    ];
  });

  // 动态运行时间
  const dynTime = computed(() => {
    return getFormatTime(deviceInfo.value.runTime, t);
  });

  const timer = setInterval(() => {
    const netValue = deviceInfo.value.runTime + 1;
    deviceInfoStore.updateDevice('runTime', netValue);
  }, 1000);
  onUnmounted(() => {
    clearInterval(timer);
  });

  // 设备名称
  const deviceName = ref('');

  // 切换编辑状态逻辑
  const edit = ref(false);
  const editType = ref(false); //是否展示tooltip
  const deviceNameInput = ref();
  const toggleEdit = async () => {
    editType.value = false;
    edit.value = true;
    await nextTick();
    deviceNameInput.value.focus();
  };

  // 输入框失去焦点逻辑
  const handleBlur = async () => {
    edit.value = false;
    const deviceNameTrim = deviceName.value.trim();

    if (deviceNameTrim === '') return;
    const params = {
      deviceName: deviceNameTrim,
      deviceType: deviceInfo.value.deviceType,
    };
    const result = await setDeviceInfoApi(params);
    if (result && result.code === 0) {
      deviceInfoStore.updateDevice('deviceName', deviceNameTrim);
    }
  };
  const handleBlur1 = () => {
    edit.value = false;
  };
</script>
<style lang="less" scoped>
  .se5-grid {
    margin-bottom: 24px;
    height: 240px;
    @media (min-width: 2200px) {
      height: 200px !important;
    }

    :deep(.statics) {
      width: calc(100% - 48px);
      top: 190px !important;
    }

    :deep(.ant-divider) {
      display: none;
    }

    :deep(.container) {
      padding: 10px 24px;

      & > p {
        border-bottom: 1px solid #ececec;
        padding-bottom: 4px;
      }
    }
  }

  .se5-row {
    background-color: white;
    padding: 24px;
  }

  .editName {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
</style>
