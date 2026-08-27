<template>
  <div class="!m-4 !p-4 bg-white">
    <a-skeleton :loading="pageLoading" active>
      <a-alert
        :type="enabled ? 'success' : 'info'"
        :message="enabled ? t('maintenance.metricsForward.enabledHint') : t('maintenance.metricsForward.disabledHint')"
        show-icon
        class="!mb-4"
      />

      <a-row :gutter="16">
        <!-- 左列：开关 + Token + 配置示例 -->
        <a-col :span="12">
          <a-card :title="t('maintenance.metricsForward.title')" size="small" class="!mb-4">
            <p class="text-gray-500 text-xs mb-4">{{ t('maintenance.metricsForward.desc') }}</p>
            <div class="flex items-center mb-4">
              <span class="mr-4">{{ t('maintenance.metricsForward.enable') }}</span>
              <a-switch v-model:checked="enabled" :loading="switching" @change="onToggle" />
            </div>

            <template v-if="enabled">
              <a-divider class="!my-3" />
              <div class="mb-1 flex items-center justify-between">
                <span>{{ t('maintenance.metricsForward.token') }}</span>
                <a-space>
                  <a-button size="small" @click="copyText(token)">
                    {{ copied ? t('maintenance.metricsForward.copied') : t('maintenance.metricsForward.copy') }}
                  </a-button>
                  <a-popconfirm
                    :title="t('maintenance.metricsForward.rotateConfirm')"
                    @confirm="onRotate"
                  >
                    <a-button size="small" danger :loading="rotating">
                      {{ t('maintenance.metricsForward.rotate') }}
                    </a-button>
                  </a-popconfirm>
                </a-space>
              </div>
              <a-typography-paragraph :copyable="{ text: token }" class="!mb-1">
                <code class="break-all">{{ token }}</code>
              </a-typography-paragraph>
              <p class="text-gray-400 text-xs">{{ t('maintenance.metricsForward.tokenTip') }}</p>
            </template>
          </a-card>

          <a-card v-if="enabled" :title="t('maintenance.metricsForward.promCfg')" size="small">
            <pre class="text-xs bg-gray-50 p-3 rounded overflow-x-auto">{{ promConfig }}</pre>
            <a-button size="small" @click="copyText(promConfig)">
              {{ copied ? t('maintenance.metricsForward.copied') : t('maintenance.metricsForward.copy') }}
            </a-button>
          </a-card>
        </a-col>

        <!-- 右列：监控 -->
        <a-col :span="12">
          <a-card :title="t('maintenance.metricsForward.monitor')" size="small">
            <a-descriptions :column="1" size="small" bordered>
              <a-descriptions-item :label="t('maintenance.metricsForward.bmssmReachable')">
                <a-tag :color="reachable ? 'green' : 'red'">
                  {{ reachable
                    ? t('maintenance.metricsForward.reachable')
                    : t('maintenance.metricsForward.unreachable') }}
                </a-tag>
              </a-descriptions-item>
              <a-descriptions-item :label="t('maintenance.metricsForward.scrapeOK')">
                {{ stats.scrapeOK }}
              </a-descriptions-item>
              <a-descriptions-item :label="t('maintenance.metricsForward.scrapeErr401')">
                {{ stats.scrapeErr401 }}
              </a-descriptions-item>
              <a-descriptions-item :label="t('maintenance.metricsForward.scrapeErr502')">
                {{ stats.scrapeErr502 }}
              </a-descriptions-item>
              <a-descriptions-item :label="t('maintenance.metricsForward.lastScrapeAt')">
                {{ fmtTime(stats.lastScrapeAt) }}
              </a-descriptions-item>
              <a-descriptions-item :label="t('maintenance.metricsForward.lastError')">
                <span class="text-red-500 break-all">{{ stats.lastError || t('maintenance.metricsForward.none') }}</span>
              </a-descriptions-item>
              <a-descriptions-item :label="t('maintenance.metricsForward.sinceStart')">
                {{ fmtTime(stats.sinceStart) }}
              </a-descriptions-item>
            </a-descriptions>
          </a-card>
        </a-col>
      </a-row>
    </a-skeleton>
  </div>
</template>

<script lang="ts" setup>
  import { ref, computed, onMounted, onUnmounted } from 'vue';
  import {
    Skeleton,
    Alert,
    Card,
    Row,
    Col,
    Switch,
    Divider,
    Space,
    Button,
    Popconfirm,
    Typography,
    Descriptions,
    Tag,
  } from 'ant-design-vue';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { useMessage } from '/@/hooks/web/useMessage';
  import {
    getMetricsForward,
    setMetricsForward,
    rotateMetricsForwardToken,
  } from '/@/api/maintenance/index';

  // 显式注册模板使用的 ant 组件（项目无全局自动注册）
  const ASkeleton = Skeleton;
  const AAlert = Alert;
  const ACard = Card;
  const ARow = Row;
  const ACol = Col;
  const ASwitch = Switch;
  const ADivider = Divider;
  const ASpace = Space;
  const AButton = Button;
  const APopconfirm = Popconfirm;
  const ATypographyParagraph = Typography.Paragraph;
  const ADescriptions = Descriptions;
  const ADescriptionsItem = Descriptions.Item;
  const ATag = Tag;

  const { t } = useI18n();
  const { createMessage } = useMessage();

  const pageLoading = ref(true);
  const enabled = ref(false);
  const token = ref('');
  const reachable = ref(false);
  const switching = ref(false);
  const rotating = ref(false);
  const copied = ref(false);

  const stats = ref({
    scrapeOK: 0,
    scrapeErr401: 0,
    scrapeErr502: 0,
    lastScrapeAt: '',
    lastError: '',
    sinceStart: '',
  });

  // 本机 IP（页面同源访问设备），用于生成可直接复制的抓取配置
  const host = computed(() => window.location.hostname || '<device-ip>');

  const promConfig = computed(
    () => `scrape_configs:
  - job_name: "cv84x2-se13"
    metrics_path: /metrics
    authorization:
      credentials: ${token.value}
    static_configs:
      - targets: ["${host.value}:8080"]`,
  );

  function fmtTime(v: string) {
    if (!v || v.startsWith('0001-')) return t('maintenance.metricsForward.none');
    try {
      return new Date(v).toLocaleString();
    } catch {
      return v;
    }
  }

  async function refresh() {
    try {
      const res: any = await getMetricsForward();
      const d = res?.result || res || {};
      enabled.value = !!d.enabled;
      token.value = d.token || '';
      reachable.value = !!d.bmssmReachable;
      stats.value = {
        scrapeOK: d.stats?.scrapeOK ?? 0,
        scrapeErr401: d.stats?.scrapeErr401 ?? 0,
        scrapeErr502: d.stats?.scrapeErr502 ?? 0,
        lastScrapeAt: d.stats?.lastScrapeAt ?? '',
        lastError: d.stats?.lastError ?? '',
        sinceStart: d.stats?.sinceStart ?? '',
      };
    } finally {
      pageLoading.value = false;
    }
  }

  async function onToggle(v: any) {
    switching.value = true;
    try {
      const res: any = await setMetricsForward(!!v);
      const d = res?.result || {};
      enabled.value = !!d.enabled;
      if (d.token) token.value = d.token;
      createMessage.success(
        v ? t('maintenance.metricsForward.enableOk') : t('maintenance.metricsForward.disableOk'),
      );
      await refresh();
    } catch (e) {
      enabled.value = !v; // 失败回滚
    } finally {
      switching.value = false;
    }
  }

  async function onRotate() {
    rotating.value = true;
    try {
      const res: any = await rotateMetricsForwardToken();
      token.value = res?.result?.token || token.value;
      createMessage.success(t('maintenance.metricsForward.rotate'));
    } finally {
      rotating.value = false;
    }
  }

  async function copyText(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      copied.value = true;
      setTimeout(() => (copied.value = false), 1500);
    } catch {
      // 剪贴板不可用时降级：跳转复制由 typography copyable 提供
    }
  }

  let timer: any = null;
  onMounted(() => {
    refresh();
    timer = setInterval(refresh, 15000); // 15s 自动刷新
  });
  onUnmounted(() => clearInterval(timer));
</script>
