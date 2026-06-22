<template>
  <a-tabs v-model:activeKey="activeKey" class="!m-4 !p-4 bg-white" animated>
    <a-tab-pane key="wan" :tab="t('maintenance.newworkSettings.wan')">
      <a-skeleton :loading="pageLoading" active>
        <a-form
          :model="wan"
          v-bind="formItemLayout"
          size="large"
          class="w-1/2 !mx-auto"
          :rules="wanRules"
          @finish="submitForm"
          v-show="!pageLoading"
        >
          <a-form-item
            v-for="item of formItemList"
            :key="item.field"
            :label="item.label"
            :name="item.field"
          >
            <a-select
              v-if="item.type === 'select'"
              ref="select"
              v-model:value="wan[item.field]"
              :options="item.options"
              @change="item.onChange"
            />
            <a-input
              v-if="item.type === 'input'"
              v-model:value="wan[item.field]"
              :placeholder="item.placeholder"
              :disabled="wan.ipType === 2"
            />
          </a-form-item>
          <a-form-item class="!pl-1/6">
            <a-button type="primary" html-type="submit" :loading="loading">{{
              t('sys.btn.confirm')
            }}</a-button>
          </a-form-item>
        </a-form>
      </a-skeleton>
    </a-tab-pane>
    <!-- <a-tab-pane key="lan1" :tab="t('maintenance.newworkSettings.lan')">
      <a-skeleton :loading="pageLoading" active>
        <a-form
          :model="lan1"
          v-bind="formItemLayout"
          size="large"
          class="w-1/2 !mx-auto"
          :rules="lanRules"
          @finish="submitForm"
        >
          <a-form-item
            v-for="item of formItemListLan"
            :key="item.field"
            :label="item.label"
            :name="item.field"
          >
            <a-select
              v-if="item.type === 'select'"
              ref="select"
              v-model:value="lan1[item.field]"
              :options="options"
              @change="handleChange"
              :disabled="item.field === 'ipType'"
            />
            <a-input
              v-if="item.type === 'input'"
              v-model:value="lan1[item.field]"
              :placeholder="item.placeholder"
            />
          </a-form-item>
          <a-form-item class="!pl-1/6">
            <a-button type="primary" html-type="submit" :loading="loading">{{
              t('sys.btn.confirm')
            }}</a-button>
          </a-form-item>
        </a-form>
      </a-skeleton>
    </a-tab-pane> -->
    <!-- <a-tab-pane key="core" :tab="t('maintenance.newworkSettings.core')" disabled>
      {{ t('maintenance.newworkSettings.core') }}
    </a-tab-pane> -->
  </a-tabs>
</template>
<script lang="ts" setup>
  import { reactive, ref, onMounted, computed, watch, h } from 'vue';
  import type { UnwrapRef } from 'vue';
  import { ipGet, ipSet } from '/@/api/maintenance/index';
  import { Tabs, Modal } from 'ant-design-vue';
  import { ExclamationCircleOutlined, CopyOutlined } from '@ant-design/icons-vue';

  import { useI18n } from '/@/hooks/web/useI18n';
  import { copyTextToClipboard } from '/@/hooks/web/useCopyToClipboard';
  import { useMessage } from '/@/hooks/web/useMessage';

  import { IpSetParams } from '/@/api/maintenance/model/index';
  // import { number } from '@intlify/core-base';
  import { IpCheck, subnetMaskCheck, gatewayCheck, dnsCheck } from '/@/utils/validateFuncs';
  import { useDeviceInfo } from '/@/store/modules/overview';
  const deviceStore = useDeviceInfo();
  const { createMessage } = useMessage();

  const { t } = useI18n();
  const ATabs = Tabs;
  const ATabPane = Tabs.TabPane;

  const activeKey = ref('wan');
  const wan: UnwrapRef<IpSetParams> = reactive({
    device: '',
    ipType: 1,
    ip: '',
    subnetMask: '',
    gateway: '',
    dns: '',
  });

  watch(
    () => wan.device,
    (value) => {
      const currentNetCard: any = ipData.wan.find((item: any) => item.netCardName === value);
      if (currentNetCard) {
        wan.ipType = currentNetCard?.dynamic + 1;
        wan.ip = currentNetCard?.ip || '';
        wan.subnetMask = currentNetCard?.netMask || '';
        wan.gateway = currentNetCard?.gateway || '';
        wan.dns = currentNetCard?.dns || '';
      }
    },
  );
  const wanRules = computed(() => {
    return wan.ipType === 1
      ? {
          ip: [
            {
              required: true,
              validator: IpCheck,
              trigger: 'blur',
            },
          ],
          subnetMask: [
            {
              required: true,
              validator: subnetMaskCheck,
              trigger: 'blur',
            },
          ],
          gateway: [
            {
              required: true,
              validator: gatewayCheck,
              trigger: 'blur',
            },
          ],
          dns: [
            {
              required: true,
              validator: dnsCheck,
              trigger: 'blur',
            },
          ],
        }
      : null;
  });

  const netMap = {
    wan,
    // lan1,
  };

  const formItemList = [
    {
      label: t('maintenance.newworkSettings.netCard'),
      field: 'device',
      placeholder: t('sys.form.placeholder'),
      type: 'select',
      options: [],
      onChange() {},
    },
    {
      label: t('maintenance.newworkSettings.ipType'),
      field: 'ipType',
      placeholder: t('sys.form.placeholder'),
      type: 'select',
      options: [
        {
          value: 1,
          label: t('maintenance.newworkSettings.staticIP'),
        },
        {
          value: 2,
          label: t('maintenance.newworkSettings.dynmicIP'),
        },
      ],
      onChange() {},
    },
    {
      label: t('maintenance.newworkSettings.ip'),
      field: 'ip',
      placeholder: t('sys.form.placeholder'),
      type: 'input',
    },
    {
      label: t('maintenance.newworkSettings.subnetMask'),
      field: 'subnetMask',
      placeholder: t('sys.form.placeholder'),
      type: 'input',
    },
    {
      label: t('maintenance.newworkSettings.gateway'),
      field: 'gateway',
      placeholder: t('sys.form.placeholder'),
      type: 'input',
    },
    {
      label: t('maintenance.newworkSettings.dns'),
      field: 'dns',
      placeholder: t('sys.form.placeholder'),
      type: 'input',
    },
  ];

  const formItemLayout = {
    labelCol: { span: 4 },
    wrapperCol: { span: 20 },
  };

  // 查询到的IP数据存储
  const ipData = reactive({
    wan: [],
  });
  const pageLoading = ref(true);
  const init = async () => {
    const result = await ipGet();
    pageLoading.value = false;
    if (result) {
      ipData.wan = result;
      if (!deviceStore.isSingleBoard) {
        ipData.wan = result.filter((item) => item.netCardName.startsWith('enp'));
      }
      setInitValue();
    }
  };
  const setInitValue = () => {
    formItemList[0].options = ipData.wan.map((item: any) => ({
      value: item.netCardName,
      label: item.netCardName,
    }));
    wan.device = formItemList[0].options[0]?.value as any;
  };
  // 复制地址
  const copyAddress = () => {
    const isSuccess = copyTextToClipboard(`${wan.ip}:8080`);
    isSuccess && createMessage.success(t('sys.copySuccess'));
  };
  const loading = ref(false);
  const submitForm = () => {
    const content =
      wan.ipType === 1
        ? h('div', { style: { 'text-align': 'center', color: '#000', margin: '30px 0 0 -30px' } }, [
            h('p', {}, t('maintenance.newworkSettings.ipRightOrNotNetword')),
            h('p', {}, t('maintenance.newworkSettings.restartAfterSubmit')),
            h('p', {}, [
              h('span', {}, `${t('maintenance.newworkSettings.useAddress') + wan.ip}:8080 `),
              h(CopyOutlined, {
                title: t('maintenance.newworkSettings.copyAddress'),
                style: { color: '#0960BC', cursor: 'pointer' },
                onClick: copyAddress,
              }),
              h('span', {}, t('maintenance.newworkSettings.reOpenPage')),
            ]),
          ])
        : h(
            'div',
            { style: { 'text-align': 'center', color: '#000', margin: '30px 0 0 -30px' } },
            t('maintenance.newworkSettings.dynIpDialogContent'),
          );
    Modal.confirm({
      title: t('sys.tips'),
      icon: h(ExclamationCircleOutlined),
      width: 600,
      content,
      onOk() {
        try {
          loading.value = true;
          const params = {
            ...netMap[activeKey.value],
          };
          ipSet(params)
            .then((res) => {
              createMessage.success(res.msg);
            })
            .catch(() => {
              createMessage.error('不支持修改ip');
            });

          // console.log(params);
        } catch (error) {
        } finally {
          loading.value = false;
        }
      },
      onCancel() {},
    });
  };

  onMounted(() => {
    if (!deviceStore.deviceType) {
      deviceStore.getDeviceInfo().then(() => {
        init();
      });
    } else {
      init();
    }
  });
</script>
