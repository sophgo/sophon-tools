<template>
  <div class="p-4">
    <!-- ============ 区域一：Agent Proxy 配置 ============ -->
    <a-card :bordered="false" title="Agent Proxy 配置" class="mb-4">
      <a-form :label-col="{ span: 5 }" :wrapper-col="{ span: 16 }" class="max-w-2xl">
        <a
          href="https://sophnet.com/"
          target="_blank"
          rel="noopener"
          class="sophnet-promo my-5 block no-underline"
        >
          <div class="flex items-baseline gap-3">
            <span class="sophnet-promo-title">Sophnet</span>
            <span class="sophnet-promo-text"
              >专为开发者打造的 AI 工具平台，让 AI 集成变得简单高效</span
            >
          </div>
        </a>
        <a-form-item label="API Base URL">
          <a-select
            v-model:value="form.llmApiBaseType"
            style="width: 100%"
            :options="apiBaseOptions"
            @change="onApiBaseChange($event)"
          />
        </a-form-item>
        <a-form-item label="API Key">
          <a-input-password
            v-model:value="form.llmApiKey"
            :placeholder="form.llmHasKey ? '已配置（留空保持不变）' : '请输入上游 API Key'"
            autocomplete="new-password"
          />
        </a-form-item>
        <a-form-item label="默认模型名称">
          <a-input-group compact>
            <a-input
              v-model:value="form.llmModel"
              style="width: 60%"
              placeholder="sophnet-deepseek"
            />
            <a-button style="width: 20%" @click="openModelPicker">选择</a-button>
          </a-input-group>
        </a-form-item>
        <a-form-item
          label="覆盖下游请求"
          tooltip="开启后，无论下游请求中的 model 是什么，转接上游时都强制使用上述默认模型名称；关闭时，仅当下游未指定 model 才使用默认模型名称。"
        >
          <a-switch v-model:checked="form.llmOverrideModel" />
        </a-form-item>
      </a-form>

      <!-- 保存 + 测试 -->
      <div class="mt-4 ml-auto flex items-center gap-2">
        <a-button type="primary" :loading="saving" @click="handleSave">保存配置</a-button>
        <a-button :loading="testing" @click="handleTest">测试</a-button>
      </div>

      <!-- 测试结果 -->
      <div v-if="testResults.length" class="mt-3 max-w-2xl">
        <a-alert
          :type="testAllOK ? 'success' : 'error'"
          show-icon
          :message="testAllOK ? '测试全部通过' : '部分测试未通过'"
          class="mb-2"
        />
        <div v-for="(r, idx) in testResults" :key="idx" class="mb-2">
          <div class="font-medium">
            <a-tag :color="r.ok ? 'green' : 'red'">{{ r.ok ? '通过' : '失败' }}</a-tag>
            {{ r.name }}
          </div>
          <div class="text-sm text-gray-600 break-all">{{ r.message }}</div>
        </div>
      </div>
    </a-card>

    <!-- ============ 区域二：Agent 服务管理 ============ -->
    <a-card :bordered="false" title="Agent 服务管理">
      <div class="max-w-2xl">
        <div class="flex items-center justify-between py-2">
          <div class="flex items-center gap-3">
            <span class="text-gray-600">服务开关</span>
            <a-switch
              :checked="serviceEnabled"
              :loading="svcActing"
              :disabled="svcLoading"
              @change="toggleAgentService"
            />
          </div>
          <div class="text-sm text-gray-500">
            <a-tag :color="serviceEnabled ? 'green' : 'red'">
              {{ serviceEnabled ? '运行中' : '已停止' }}
            </a-tag>
            <span v-if="svc && svc.sessionCount" class="ml-2"> 会话 {{ svc.sessionCount }} </span>
          </div>
        </div>
        <p class="mt-3 text-xs text-gray-400">
          控制 Agent（Reasonix）服务的运行状态：关闭后对话不可用，开启后可恢复对话。
        </p>
      </div>
    </a-card>

    <!-- 模型选择弹窗 -->
    <a-modal
      v-model:open="picker.visible"
      title="选择模型"
      @ok="applyPickedModel"
      :ok-button-props="{ disabled: !picker.selected }"
    >
      <div class="mb-3">
        <a-input-search
          v-model:value="picker.custom"
          placeholder="或手动输入模型名，回车确认"
          enter-button="使用"
          @search="applyCustomModel"
        />
      </div>
      <a-select
        v-model:value="picker.selected"
        style="width: 100%"
        placeholder="从供应商拉取模型列表"
        :loading="picker.loading"
        :options="picker.options"
        @dropdown-visible-change="loadModels"
        allow-clear
      />
    </a-modal>
  </div>
</template>

<script lang="ts" setup>
  // @ts-nocheck
  import { reactive, ref, computed, onMounted } from 'vue';
  import {
    Card,
    Form,
    Input,
    Button,
    Switch,
    Alert,
    Modal,
    Select,
    Tag,
    message,
  } from 'ant-design-vue';
  import {
    getAgentConfig,
    saveAgentConfig,
    getProviderModels,
    testAgentConfig,
    getServiceStatus,
    serviceAction,
    type TestResult,
    type ServiceStatus,
  } from '/@/api/aiAgent';

  const ACard = Card;
  const AForm = Form;
  const AFormItem = Form.Item;
  const AInput = Input;
  const AInputPassword = Input.Password;
  const AInputGroup = Input.Group;
  const AInputSearch = Input.Search;
  const AButton = Button;
  const ASwitch = Switch;
  const AAlert = Alert;
  const AModal = Modal;
  const ASelect = Select;
  const ATag = Tag;

  const saving = ref(false);
  const testing = ref(false);
  const testResults = ref<TestResult[]>([]);
  const testAllOK = ref(true);

  // ---- Agent 服务（启用开关 / 服务管理开关共用） ----
  const svc = ref<ServiceStatus | null>(null);
  const svcLoading = ref(false);
  const svcActing = ref(false);
  const serviceEnabled = computed(() => !!svc.value?.active);

  async function refreshService() {
    svcLoading.value = true;
    try {
      svc.value = await getServiceStatus();
    } finally {
      svcLoading.value = false;
    }
  }

  // 启用开关 / 服务管理开关：统一驱动 Reasonix 服务启停
  async function toggleAgentService(checked: boolean) {
    if (svcActing.value) return;
    svcActing.value = true;
    try {
      const res = await serviceAction(checked ? 'start' : 'stop');
      if (res.ok) {
        message.success(checked ? 'Agent 服务已启用' : 'Agent 服务已停止');
      } else {
        message.error(res.message || '操作失败');
      }
    } finally {
      svcActing.value = false;
    }
    await refreshService();
  }

  // API Base URL 预设
  const SOPHNET_API_BASE = 'https://www.sophnet.com/api/open-apis/v1';
  const LOCAL_API_BASE = 'http://127.0.0.1:8000/v1';
  const apiBaseOptions = [
    { label: 'Sophnet', value: 'sophnet' },
    { label: '本地模型', value: 'local' },
  ];
  const apiBaseByType: Record<string, string> = {
    sophnet: SOPHNET_API_BASE,
    local: LOCAL_API_BASE,
  };

  const form = reactive({
    llmApiBase: '',
    llmApiBaseType: 'sophnet',
    llmApiKey: '',
    llmModel: '',
    llmEnabled: true,
    llmOverrideModel: false,
    llmHasKey: false,
  });

  // 根据已存 apiBase 推断类型（匹配预设则对应类型，否则兜底 sophnet）
  function inferApiBaseType(apiBase: string): string {
    for (const [type, url] of Object.entries(apiBaseByType)) {
      if (apiBase && apiBase === url) {
        return type;
      }
    }
    return 'sophnet';
  }

  // 下拉切换：自动填充对应 URL（sophnet 固定，不允许自定义）
  function onApiBaseChange(type: string) {
    form.llmApiBase = apiBaseByType[type] || SOPHNET_API_BASE;
  }

  const picker = reactive({
    visible: false,
    options: [] as { label: string; value: string }[],
    selected: undefined as string | undefined,
    custom: '',
    loading: false,
  });

  async function init() {
    const cfg = await getAgentConfig();
    if (cfg) {
      form.llmApiBase = cfg.llmApiBase || SOPHNET_API_BASE;
      form.llmApiBaseType = inferApiBaseType(cfg.llmApiBase || '');
      form.llmModel = cfg.llmModel || '';
      form.llmEnabled = cfg.llmEnabled !== false;
      form.llmOverrideModel = !!cfg.llmOverrideModel;
      form.llmHasKey = !!cfg.llmHasKey;
    }
  }

  async function handleSave() {
    if (!form.llmApiBase.trim()) {
      message.warning('请配置 API Base URL');
      return;
    }
    saving.value = true;
    const res = await saveAgentConfig({
      llmApiBase: form.llmApiBase.trim(),
      llmApiKey: form.llmApiKey,
      llmModel: form.llmModel.trim() || 'sophnet-deepseek',
      llmEnabled: form.llmEnabled,
      llmOverrideModel: form.llmOverrideModel,
    });
    saving.value = false;
    if (res.ok) {
      message.success('配置已保存，转发服务已生效');
      form.llmApiKey = '';
      form.llmHasKey = true;
    } else {
      message.error(res.message || '保存失败');
    }
  }

  async function handleTest() {
    testing.value = true;
    testResults.value = [];
    const res = await testAgentConfig();
    testing.value = false;
    if (res.ok && res.data) {
      testResults.value = res.data.results || [];
      testAllOK.value = !!res.data.allOk;
    } else {
      testAllOK.value = false;
      testResults.value = [{ name: '测试', ok: false, message: res.message || '测试请求失败' }];
    }
  }

  // --- 模型选择弹窗 ---
  function openModelPicker() {
    picker.selected = undefined;
    picker.custom = '';
    picker.options = [];
    picker.visible = true;
  }

  async function loadModels(open: boolean) {
    if (!open || picker.options.length) return;
    picker.loading = true;
    const ids = await getProviderModels();
    picker.options = ids.map((id) => ({ label: id, value: id }));
    picker.loading = false;
  }

  function applyCustomModel() {
    const v = picker.custom.trim();
    if (!v) return;
    applyModel(v);
  }

  function applyPickedModel() {
    if (picker.selected) {
      applyModel(picker.selected);
    }
  }

  function applyModel(name: string) {
    form.llmModel = name;
    picker.visible = false;
    message.success(`已选择模型 ${name}`);
  }

  onMounted(() => {
    init();
    refreshService();
  });
</script>

<style lang="less" scoped>
  .sophnet-promo {
    // 横幅与上下元素之间留白
    padding: 14px 20px;
    border-radius: 10px;
    border: 1px solid #d6e4ff;
    background: linear-gradient(120deg, #eef4ff, #dceaff, #eef4ff);
    background-size: 200% 100%;
    animation: sophnet-gradient 8s ease infinite;
    box-shadow: 0 1px 4px rgba(26, 115, 232, 0.08);
    transition: box-shadow 0.2s ease, border-color 0.2s ease;
    cursor: pointer;
  }

  .sophnet-promo:hover {
    box-shadow: 0 2px 10px rgba(26, 115, 232, 0.18);
    border-color: #b6d0ff;
  }

  .sophnet-promo-title {
    font-size: 18px;
    font-weight: 700;
    color: #1a73e8;
    white-space: nowrap;
  }

  .sophnet-promo-text {
    font-size: 15px;
    color: #3c5a8f;
    line-height: 1.5;
  }

  @keyframes sophnet-gradient {
    0% {
      background-position: 0% 50%;
    }
    50% {
      background-position: 100% 50%;
    }
    100% {
      background-position: 0% 50%;
    }
  }
</style>
