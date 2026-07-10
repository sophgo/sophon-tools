<template>
  <a-tabs v-model:activeKey="activeKey" class="!m-4 !p-4 bg-white">
    <a-tab-pane key="wan" :tab="t('maintenance.threshold.title')">
      <a-skeleton :loading="pageLoading" active>
        <a-form
          :model="formState"
          v-bind="formItemLayout"
          class="flex flex-wrap justify-around"
          size="large"
        >
          <a-form-item
            v-for="item of formItemList"
            :key="item.field"
            :label="item.label"
            class="w-2/5"
          >
            <a-input v-model:value="formState[item.field]" :placeholder="placeholder">
              <template #addonAfter>
                <span v-if="item.unit" :style="{ color }">{{ item.unit }}</span>
                <percentage-outlined v-else :style="{ color }" />
              </template>
            </a-input>
          </a-form-item>
          <a-form-item class="w-2/5" />
          <a-form-item :wrapper-col="{ offset: 8, span: 16 }" class="w-2/5 !mr-1/2">
            <a-button type="primary" @click="submitForm" :loading="loading">{{
              t('sys.btn.confirm')
            }}</a-button>
          </a-form-item>
        </a-form>
      </a-skeleton>
    </a-tab-pane>
  </a-tabs>
</template>
<script lang="ts" setup>
  import { reactive, ref, onMounted } from 'vue';
  import { PercentageOutlined } from '@ant-design/icons-vue';
  import type { UnwrapRef } from 'vue';
  import { setAlarm, getAlarm } from '/@/api/maintenance/index';
  import { Tabs } from 'ant-design-vue';
  import { useMessage } from '/@/hooks/web/useMessage';
  import { useI18n } from '/@/hooks/web/useI18n';
  // import { useMessage } from '/@/hooks/web/useMessage';

  import { AlarmParams } from '/@/api/maintenance/model/index';
  import { useDeviceInfo } from '/@/store/modules/overview';
  const deviceStore = useDeviceInfo();
  onMounted(() => {
    if (!deviceStore.deviceType) {
      deviceStore.getDeviceInfo().then(() => {
        init();
      });
    } else {
      init();
    }
  });
  // const { createErrorModal } = useMessage();
  const { t } = useI18n();
  const { createMessage } = useMessage();
  const ATabs = Tabs;
  const ATabPane = Tabs.TabPane;

  const placeholder = t('sys.form.phNumber');
  const color = '#0960BD';

  const activeKey = ref('wan');
  const formItemList = [
    {
      label: t('maintenance.threshold.boardTemperature'),
      field: 'boardTemperature',
      unit: '°C',
    },
    {
      label: t('maintenance.threshold.coreTemperature'),
      field: 'coreTemperature',
      unit: '°C',
    },
    {
      label: t('maintenance.threshold.cpuRate'),
      field: 'cpuRate',
    },
    {
      label: t('maintenance.threshold.totalMemoryScale'),
      field: 'totalMemoryScale',
    },
    {
      label: t('maintenance.threshold.tpuScale'),
      field: 'tpuScale',
    },
    {
      label: t('maintenance.threshold.diskRate'),
      field: 'diskRate',
    },
    {
      label: 'tpu使用率',
      field: 'tpuRate',
    },
  ];
  const formState: UnwrapRef<AlarmParams> = reactive({
    boardTemperature: 0,
    coreTemperature: 0,
    cpuRate: 90,
    totalMemoryScale: 90,
    tpuScale: 90,
    diskRate: 90,
    tpuRate: 90,
  });
  const formItemLayout = {
    labelCol: { span: 8 },
    wrapperCol: { span: 16 },
  };

  const pageLoading = ref(true);
  const init = async () => {
    const result = await getAlarm();
    pageLoading.value = false;
    if (result) {
      formState.boardTemperature = result.boardTemperature;
      formState.coreTemperature = result.coreTemperature;
      // cpuRate/diskRate/tpuRate ssm 已是百分比（0-100），不再 *100
      formState.cpuRate = Math.round(result.cpuRate);
      formState.diskRate = Math.round(result.diskRate);
      formState.tpuRate = Math.round(result.tpuRate);
      // *Scale 字段为 0-1 分数，*100 转百分比
      formState.totalMemoryScale = Math.round(result.totalMemoryScale * 100);
      formState.tpuScale = Math.round(result.tpuScale * 100);
    }
  };
  const loading = ref(false);
  function areAllPropertyValuesValid(obj) {
    for (var key in obj) {
      if (obj.hasOwnProperty(key)) {
        var value = obj[key];

        // 使用正则表达式判断是否是整数
        var isInteger = /^\d+$/.test(value);
        // 判断整数范围
        if (!isInteger || parseInt(value, 10) <= 0 || parseInt(value, 10) > 100) {
          return false;
        }
      }
    }
    return true;
  }
  const submitForm = async () => {
    try {
      loading.value = true;

      const isParams = areAllPropertyValuesValid(formState);
      if (!isParams) {
        createMessage.error(placeholder, 2);
        init();
      } else {
        const params = {
          ...formState,
        };
        for (const key in params) {
          if (params.hasOwnProperty(key)) {
            params[key] = Number(params[key]);
          }
        }
        // 不需要 /100 的字段：已是百分比或绝对值
        const staticFields = [
          'boardTemperature',
          'coreTemperature',
          'cpuRate',
          'diskRate',
          'tpuRate',
        ];
        Object.keys(params).forEach((key) => {
          if (!staticFields.includes(key)) {
            params[key] = params[key] / 100;
          }
        });
        await setAlarm(params)
          .then(() => {
            createMessage.success('操作成功');
          })
          .catch(() => {
            createMessage.error('操作失败');
          });
      }
    } catch (error) {
      // createErrorModal({
      //   title: t('sys.api.errorTip'),
      //   content: (error as unknown as Error).message || t('sys.api.networkExceptionMsg'),
      //   getContainer: () => document.body,
      // });
    } finally {
      loading.value = false;
    }
  };
</script>
