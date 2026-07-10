<template>
  <div class="p-24px">
    <a-row :gutter="20" class="top-cards">
      <a-col :xs="24" :sm="12" :xl="6">
        <div class="metric-card">
          <p class="card-title">{{ t('overview.cpu') }}</p>
          <a-progress
            type="circle"
            :percent="cpuCard.usage"
            :stroke-color="cardColor(cpuCard.usage)"
            :format="() => cpuCard.usage.toFixed(1) + '%'"
            class="circle"
          />
          <p class="card-text">{{ cpuCard.text }}</p>
        </div>
      </a-col>
      <a-col :xs="24" :sm="12" :xl="6">
        <div class="metric-card">
          <p class="card-title">{{ t('overview.tpu') }}</p>
          <a-progress
            type="circle"
            :percent="tpuCard.usage"
            :stroke-color="cardColor(tpuCard.usage)"
            :format="() => tpuCard.usage.toFixed(1) + '%'"
            class="circle"
          />
          <p class="card-text">{{ tpuCard.text }}</p>
        </div>
      </a-col>
      <a-col :xs="24" :sm="12" :xl="6">
        <MemoryLayout :layout="originData.memoryLayout" />
      </a-col>
      <a-col :xs="24" :sm="12" :xl="6">
        <DiskLayout :layout="originData.diskLayout" />
      </a-col>
    </a-row>
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
          <a-descriptions-item :label="t('overview.device.runningTime')">
            <a-badge status="processing" :text="dynTime" />
          </a-descriptions-item>
          <a-descriptions-item :label="t('overview.operatingSystem')">{{
            originData.operatingSystem
          }}</a-descriptions-item>
          <a-descriptions-item
            v-for="item in originData.netCard || []"
            :label="t('overview.netCard') + (item.netCardName || item.name || '')"
            :key="item.netCardName || item.name || item.ip"
          >
            {{
              t('overview.bandwidth') +
              '：' +
              (item.bandwidth > 0 ? item.bandwidth + t('overview.bandwidthUnit') : '未连接')
            }}
            <br />
            {{ t('overview.ip') + '：' + (item.ip || '未分配') }}
            <br />
            {{ t('overview.mac') + '：' + item.mac }}
          </a-descriptions-item>
        </a-descriptions>
      </a-col>
      <a-col :xs="24" :lg="12" class="!flex items-center">
        <GaugeChart
          :value="deviceInfo.temperature"
          :unit="t('overview.coreTemperature') + '（℃）'"
        />
      </a-col>
    </a-row>
  </div>
</template>
<script lang="ts" setup>
  import { ref, computed, onUnmounted, nextTick } from 'vue';
  import { Descriptions, Row, Col, Badge, Tooltip, Progress } from 'ant-design-vue';
  import { storeToRefs } from 'pinia';
  import { useDeviceInfo } from '/@/store/modules/overview';
  import { useI18n } from '/@/hooks/web/useI18n';
  import GaugeChart from './components/Gauge.vue';
  import MemoryLayout from './components/MemoryLayout.vue';
  import DiskLayout from './components/DiskLayout.vue';
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
  const AProgress = Progress;
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

  const cpuCard = computed(() => {
    const cpu = originData.value.cpu || {};
    return {
      usage: +(cpu.utilizationRate ?? cpu.usage ?? 0).toFixed(1),
      text: `${cpu.cores ?? 0}${t('overview.core')}${
        cpu.frequency ? (cpu.frequency / 1000).toFixed(1) : 0
      }GHz`,
    };
  });

  const tpuCard = computed(() => {
    const chip0 = originData.value?.coreComputingUnit?.board?.[0]?.chip?.[0] || {};
    return {
      usage: +(chip0.utilizationRate ?? chip0.tpuUtililizationRate ?? 0).toFixed(1),
      text: 'INT8 ' + (chip0.calculationCapacityInt8 ?? chip0.theoretialCalculationCapacity ?? 0) + 'TOPS',
    };
  });

  const cardColor = (pct: number) => {
    if (pct >= 90) return '#ff4d4f';
    if (pct >= 70) return '#faad14';
    return '#108ee9';
  };

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
  .top-cards {
    margin-bottom: 24px;
  }

  .metric-card {
    background-color: white;
    padding: 24px;
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;

    .card-title {
      font-weight: bold;
      font-size: 16px;
      margin-bottom: 12px;
      align-self: flex-start;
    }

    .circle {
      display: flex;
      justify-content: center;
      margin-bottom: 8px;
    }

    .card-text {
      font-size: 12px;
      color: #999;
      text-align: center;
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
