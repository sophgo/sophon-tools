<template>
  <a-card :title="t('overview.deviceBaseInformation')" :loading="loading">
    <a-descriptions bordered>
      <a-descriptions-item :label="t('overview.deviceName')">
        <span class="editName">
          <span v-if="!edit">{{ deviceInfo.deviceName }}</span>
          <a-input
            v-if="edit"
            v-model:value="deviceName"
            ref="deviceNameInput"
            @blur="handleBlur"
            @keyup.enter="handleBlur1"
          />
          <a-tooltip :title="t('overview.device.editType')" placement="right" :visible="editType">
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
        deviceInfo.deviceType
      }}</a-descriptions-item>
      <a-descriptions-item :label="t('overview.device.sn')">{{
        deviceInfo.deviceSn
      }}</a-descriptions-item>
      <a-descriptions-item :label="t('overview.device.system')">{{
        deviceInfo.operatingSystem
      }}</a-descriptions-item>
      <a-descriptions-item :label="t('overview.device.sdkVersion')">{{
        deviceInfo.sdkVersion
      }}</a-descriptions-item>
      <a-descriptions-item :label="t('overview.device.runningTime')">
        <a-badge status="processing" :text="dynTime" />
      </a-descriptions-item>
      <a-descriptions-item :label="t('overview.device.ip')">{{
        deviceInfo.deviceIp
      }}</a-descriptions-item>
      <a-descriptions-item label="WAN IP">{{ deviceInfo.wanIp }}</a-descriptions-item>
      <a-descriptions-item label="LAN IP">
        {{ deviceInfo.lanIp.split(',')[0] }}
        <br />
        {{ deviceInfo.lanIp.split(',')[1] }}
      </a-descriptions-item>
      <a-descriptions-item :label="t('overview.int8Power')">{{
        formatPower(deviceInfo.int8Count, 'low')
      }}</a-descriptions-item>
      <a-descriptions-item :label="t('overview.fp16Power')">{{
        formatPower(deviceInfo.fp16Count, 'low')
      }}</a-descriptions-item>
      <a-descriptions-item :label="t('overview.fp32Power')">{{
        formatPower(deviceInfo.fp32Count, 'low')
      }}</a-descriptions-item>
      <a-descriptions-item :label="t('overview.cpuCapacity')">{{
        formatPower(deviceInfo.cpuCount, 'low')
      }}</a-descriptions-item>
      <a-descriptions-item :label="t('overview.memory')" span="2">{{
        formatPower(deviceInfo.memoryCount, 2)
      }}</a-descriptions-item>
      <a-descriptions-item :label="t('overview.emmc')">{{
        formatPower(deviceInfo.eMMCCount, 2)
      }}</a-descriptions-item>
      <a-descriptions-item :label="t('overview.diskCapacity')" span="2"
        >{{ formatPower(deviceInfo.diskCount, 2) }}
      </a-descriptions-item>
    </a-descriptions>
  </a-card>
</template>
<script lang="ts" setup>
  // @ts-nocheck
  import { ref, nextTick, computed, onUnmounted } from 'vue';
  import { Card, Descriptions, Badge, Tooltip } from 'ant-design-vue';
  import { storeToRefs } from 'pinia';
  import { EditOutlined } from '@ant-design/icons-vue';
  import { useDeviceInfo } from '/@/store/modules/overview';
  import { setDeviceInfoApi } from '/@/api/overview/index';
  import { getFormatTime } from '/@/utils/dateUtil';
  import { useI18n } from '/@/hooks/web/useI18n';
  const { t } = useI18n();
  // import dayjs from 'dayjs';
  // import duration from 'dayjs/plugin/duration';
  // dayjs.extend(duration);
  defineProps({
    loading: Boolean,
  });

  const ACard = Card;
  const ABadge = Badge;
  const ADescriptions = Descriptions;
  const ADescriptionsItem = Descriptions.Item;
  const ATooltip = Tooltip;
  // 设备基础信息
  const deviceInfoStore = useDeviceInfo();
  const { deviceInfo } = storeToRefs(deviceInfoStore);

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

  // 格式化峰值算力
  const formatPower = ({ total, unit, desc }, dot = 0) => {
    if (dot === 'low') {
      return `${Math.floor(total)}${unit} ${desc}`;
    }
    return `${total.toFixed(dot)}${unit} ${desc}`;
  };
</script>
<style lang="less" scoped>
  .editName {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
</style>
