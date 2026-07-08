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
  import { ExclamationCircleOutlined } from '@ant-design/icons-vue';

  import { useI18n } from '/@/hooks/web/useI18n';
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
      const currentNetCard: any = ipData.wan.find((item: any) => item.name === value);
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
    if (result && Array.isArray(result)) {
      ipData.wan = result;
      if (!deviceStore.isSingleBoard) {
        ipData.wan = result.filter(
          (item) => item?.name && item.name.startsWith('enp'),
        );
      }
      setInitValue();
    }
  };
  const setInitValue = () => {
    formItemList[0].options = ipData.wan.map((item: any) => ({
      value: item.name,
      label: item.name,
    }));
    wan.device = formItemList[0].options[0]?.value as any;
  };
  const loading = ref(false);
  const submitForm = () => {
    // 弹窗显示待应用的 IP 参数 + 确认。bm_set_ip 改 IP 后立即生效（不重启），
    // 若 IP 变更，当前连接会当场断开，浏览器在途请求收不到响应——故提示用新 IP 重访。
    const policyText = wan.ipType === 2 ? 'DHCP' : '静态';
    const row = (label: string, val: string) =>
      h('div', { style: { display: 'flex', justifyContent: 'space-between', margin: '4px 0' } }, [
        h('span', { style: { color: '#888' } }, label),
        h('span', { style: { 'font-family': 'monospace', color: '#000' } }, val || '-'),
      ]);
    const content = h('div', { style: { margin: '10px 0' } }, [
      row(t('maintenance.newworkSettings.netCard'), wan.device),
      row(t('maintenance.newworkSettings.ipType'), policyText),
      ...(wan.ipType === 1
        ? [
            row(t('maintenance.newworkSettings.ip'), wan.ip),
            row(t('maintenance.newworkSettings.subnetMask'), wan.subnetMask),
            row(t('maintenance.newworkSettings.gateway'), wan.gateway),
            row(t('maintenance.newworkSettings.dns'), wan.dns),
          ]
        : []),
      h(
        'p',
        { style: { color: '#fa8c16', margin: '12px 0 4px', 'font-size': '13px' } },
        '若 IP 变更，应用后当前连接会立即断开（无需重启），请用新 IP 重新访问页面。',
      ),
      h('p', { style: { color: '#000', 'font-weight': 550 } }, '确认是否继续设置 IP？'),
    ]);
    Modal.confirm({
      title: t('sys.tips'),
      icon: h(ExclamationCircleOutlined),
      width: 480,
      content,
      onOk() {
        loading.value = true;
        const params = {
          ...netMap[activeKey.value],
        };
        ipSet(params)
          .then((res) => {
            // isTransformResponse:false 返回原始信封；code!=0 时按错误提示
            if (res && res.code === 0) {
              createMessage.success(res.msg || 'IP 设置成功');
            } else {
              createMessage.error(res?.error_message || res?.msg || 'IP 设置失败');
            }
          })
          .catch((e) => {
            // 多为 IP 变更后连接断开（收不到响应）；少数为参数非法 400。
            const code = e?.response?.status;
            if (code === 400 || code === 422) {
              createMessage.error(e?.response?.data?.error_message || 'IP 参数不合法');
            } else {
              createMessage.warning(
                'IP 设置请求已提交。若 IP 已变更，连接已断开，请用新 IP 重新访问；若未变更，请重试。',
                5,
              );
            }
          })
          .finally(() => {
            loading.value = false;
          });
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
