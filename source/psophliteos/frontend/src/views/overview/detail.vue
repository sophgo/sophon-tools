<template>
  <Card
    class="!m-4"
    :tab-list="tabListTitle"
    v-bind="$attrs"
    :active-tab-key="activeKey"
    :loading="loading"
    @tab-change="onTabChange"
  >
    <CircleGrid :grid-list="gridList" />
    <a-divider />
    <div v-if="activeKey === 'control'">
      <a-descriptions :title="t('overview.basicInfor')" bordered :column="controlColumn">
        <a-descriptions-item :label="t('overview.device.name')">{{
          originData.deviceName
        }}</a-descriptions-item>
        <a-descriptions-item :label="t('overview.device.type')">{{
          originData.deviceType
        }}</a-descriptions-item>
        <a-descriptions-item :label="t('overview.device.ctrSN')">{{
          originData.ctrlBoardSn
        }}</a-descriptions-item>
        <a-descriptions-item :label="t('overview.device.sdkVersion')">{{
          originData.sdkVersion
        }}</a-descriptions-item>
        <a-descriptions-item :label="t('overview.buildTime')">{{
          originData.bmssmVersion
        }}</a-descriptions-item>
        <a-descriptions-item :label="t('overview.device.ip')">{{
          originData.deviceIp
        }}</a-descriptions-item>
        <a-descriptions-item label="WAN IP">{{ originData.wanIp || '-' }}</a-descriptions-item>
        <a-descriptions-item label="LAN IP">
          {{ (originData.lanIp || '').split(',')[0] || '-' }}
          <br v-if="(originData.lanIp || '').split(',')[1]" />
          {{ (originData.lanIp || '').split(',')[1] || '' }}
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
    </div>
    <a-row v-if="activeKey === 'core'">
      <a-col :xs="24" :lg="12">
        <a-descriptions :title="t('overview.basicInfor')" bordered :column="1">
          <a-descriptions-item :label="t('overview.device.sn')">{{
            currentBoardInfor.boardSn
          }}</a-descriptions-item>
          <a-descriptions-item :label="t('overview.device.sdkVersion')">{{
            currentBoardInfor.sdkVersion
          }}</a-descriptions-item>
          <a-descriptions-item :label="t('overview.device.type')">{{
            currentBoardInfor.boardType
          }}</a-descriptions-item>
          <a-descriptions-item :label="t('overview.chip') + t('overview.health')">{{
            chipStatus[currentBoardInfor.chip?.[0]?.health] ?? '-'
          }}</a-descriptions-item>
          <a-descriptions-item :label="t('overview.ip')">{{
            currentBoardInfor.coreSys?.netCard?.[0]?.ip ||
            currentBoardInfor.netCard?.[0]?.ip
          }}</a-descriptions-item>
          <a-descriptions-item :label="t('overview.bandwidth')">{{
            (currentBoardInfor.coreSys?.netCard?.[0]?.bandwidth ??
              currentBoardInfor.netCard?.[0]?.bandwidth) > 0
              ? (currentBoardInfor.coreSys?.netCard?.[0]?.bandwidth ??
                  currentBoardInfor.netCard?.[0]?.bandwidth) + t('overview.bandwidthUnit')
              : '未连接'
          }}</a-descriptions-item>
          <a-descriptions-item :label="t('overview.mac')">{{
            currentBoardInfor.coreSys?.netCard?.[0]?.mac ||
            currentBoardInfor.netCard?.[0]?.mac
          }}</a-descriptions-item>
        </a-descriptions>
      </a-col>
      <a-col :xs="24" :lg="12" class="!flex items-center">
        <a-row class="w-full">
          <a-col :xs="24" :md="24">
            <GaugeChart
              :value="currentBoardInfor.chip?.[0]?.temperature ?? 0"
              :unit="t('overview.coreTemperature') + '（℃）'"
            />
          </a-col>
        </a-row>
      </a-col>
    </a-row>
    <template #tabBarExtraContent>
      <a-select
        v-show="activeKey === 'core'"
        v-model:value="currentCore"
        style="width: 140px"
        :options="plainOptions"
      />
    </template>
  </Card>
</template>
<script lang="ts" setup>
  import { ref, computed } from 'vue';
  import { Card, Descriptions, Divider, Row, Col } from 'ant-design-vue';
  import { storeToRefs } from 'pinia';
  import { useDeviceInfo } from '/@/store/modules/overview';
  import { useRouter } from 'vue-router';
  import { useI18n } from '/@/hooks/web/useI18n';
  import CircleGrid from './components/CircleGrid.vue';
  import GaugeChart from './components/Gauge.vue';
  import { useWindowSize } from '@vueuse/core';

  const { t } = useI18n();
  const { currentRoute } = useRouter();

  const ADescriptions = Descriptions;
  const ADescriptionsItem = Descriptions.Item;
  const ARow = Row;
  const ACol = Col;
  const ADivider = Divider;

  const loading = ref(false);
  const deviceInfoStore = useDeviceInfo();
  const { deviceStatus, deviceInfo, originData } = storeToRefs(deviceInfoStore);
  if (!deviceInfo.value.deviceSn) {
    loading.value = true;
    deviceInfoStore.getDeviceInfo().then(() => {
      loading.value = false;
    });
  }

  const activeKey = ref('control');
  const chipStatus = {
    0: t('overview.healthy'),
    1: t('overview.hitch'),
  };

  const tabListTitle = [
    {
      key: 'control',
      tab: t('overview.controlBoard'),
    },
    {
      key: 'core',
      tab: t('overview.coreBoard'),
    },
  ];

  function onTabChange(key) {
    activeKey.value = key;
    if (key === 'core') {
      currentCore.value = plainOptions.value[0]?.value;
    }
  }

  // 设备基础信息
  interface Board {
    sn: string;
    title: string;
    number: Number;
  }

  // 核心板选择器
  const plainOptions = computed(() => {
    return deviceStatus.value.map((board: Board) => ({
      value: board.sn,
      label: t('overview.coreBoard') + '-' + board.number,
    }));
  });

  // 当前核心板
  const currentCore = ref('');
  //   watch(plainOptions, () => {
  //     currentCore.value = plainOptions.value[0]?.value;
  //   });
  // 当前核心板信息
  const currentBoardInfor = computed(() => {
    try {
      return (
        originData.value.coreComputingUnit.board.find((board) => {
          return board.boardSn === currentCore.value;
        }) || {}
      );
    } catch (error) {
      console.log(error);
      return {};
    }
  });
  if (currentRoute.value.params.sn) {
    activeKey.value = 'core';
    currentCore.value = currentRoute.value.params.sn as any;
  }
  const gridList = computed(() => {
    let result: any[] = [];
    if (activeKey.value === 'control' && originData.value.cpu) {
      const cpu = originData.value.cpu || {};
      const mem = originData.value.memory || {};
      const disk0 = (originData.value.disk && originData.value.disk[0]) || {};
      result = [
        {
          title: t('overview.cpu'),
          usage: cpu.utilizationRate ?? cpu.usage ?? 0,
          text: `${cpu.cores ?? 0}${t('overview.core')}${
            cpu.frequency ? (cpu.frequency / 1000).toFixed(1) : 0
          }GHz`,
        },
        {
          title: t('overview.memory'),
          usage: mem.total
            ? +(((mem.total - (mem.free ?? mem.available ?? mem.total)) / mem.total) * 100).toFixed(1)
            : 0,
          total: mem.total ?? 0,
        },
        {
          title: t('overview.disk'),
          usage: disk0.total
            ? +(((disk0.total - (disk0.free ?? disk0.total)) / disk0.total) * 100).toFixed(1)
            : 0,
          total: disk0.total ?? 0,
        },
      ];
    } else if (activeKey.value === 'core' && currentBoardInfor.value.boardSn) {
      const board = currentBoardInfor.value;
      const coreSys = board.coreSys || board;
      const cpu = coreSys.cpu || board.cpu || {};
      const mem = coreSys.memory || board.memory || {};
      const disk0 = (board.disk && board.disk[0]) || (originData.value.disk && originData.value.disk[0]) || {};
      const chip0 = board.chip?.[0] || {};
      result = [
        {
          title: t('overview.cpu'),
          usage: cpu.utilizationRate ?? cpu.usage ?? 0,
          text: `${cpu.cores ?? 0}${t('overview.core')}${
            cpu.frequency ? (cpu.frequency / 1000).toFixed(1) : 0
          }GHz`,
        },
        {
          title: t('overview.memory'),
          usage: mem.total
            ? +(((mem.total - (mem.available ?? mem.free ?? mem.total)) / mem.total) * 100).toFixed(1)
            : mem.usage ?? 0,
          total: mem.total ?? 0,
        },
        {
          title: t('overview.disk'),
          usage: disk0.total
            ? +(((disk0.total - (disk0.free ?? disk0.total)) / disk0.total) * 100).toFixed(1)
            : 0,
          total: disk0.total ?? 0,
        },
        {
          title: t('overview.tpu'),
          usage: chip0.utilizationRate ?? chip0.tpuUtililizationRate ?? 0,
          text: computePower.value,
        },
      ];
    }
    return result;
  });
  const computePower = computed(() => {
    const computingPowerList = {
      SE6: 'INT8 17.6TOPS',
      SE8: 'INT8 32.0TOPS',
    };
    return computingPowerList[deviceInfo.value.deviceType];
  });
  const { width } = useWindowSize();
  const controlColumn = computed(() => {
    return width.value > 768 ? 2 : 1;
  });
</script>
