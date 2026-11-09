<template>
  <div class="p-4">
    <!-- ============ 区域一：Agent Proxy 配置 ============ -->
    <a-card :bordered="false" title="Agent Proxy 配置" class="mb-4">
      <a-form :label-col="{ span: 5 }" :wrapper-col="{ span: 16 }" class="max-w-2xl">
        <!-- Sophnet 推广横幅：仅 Sophnet 模式下展示（自定义 OpenAI API 模式无关） -->
        <a
          v-if="form.llmApiBaseType === 'sophnet'"
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
        <a-form-item
          label="上游类型"
          tooltip="Sophnet：使用算能官方云端（预设地址，只需填 key）。自定义 OpenAI API：填入任意 OpenAI 兼容服务的 Base URL（本地推理服务、第三方云厂商等）。"
        >
          <a-radio-group
            v-model:value="form.llmApiBaseType"
            button-style="solid"
            @change="onApiBaseTypeChange($event)"
          >
            <a-radio-button value="sophnet">Sophnet</a-radio-button>
            <a-radio-button value="custom">自定义 OpenAI API</a-radio-button>
          </a-radio-group>
        </a-form-item>
        <a-form-item
          label="API Base URL"
          :required="form.llmApiBaseType === 'custom'"
          :tooltip="
            form.llmApiBaseType === 'custom'
              ? 'OpenAI 兼容服务的 base 地址，转发时自动拼接 /chat/completions。例如 http://192.168.1.10:8000/v1'
              : ''
          "
        >
          <!-- Sophnet 地址固定；自定义模式放开为可输入的 OpenAI 兼容 base -->
          <a-input
            v-if="form.llmApiBaseType === 'custom'"
            v-model:value="form.llmApiBase"
            style="width: 100%"
            placeholder="http://192.168.1.10:8000/v1"
            allow-clear
          />
          <a-input v-else :value="SOPHNET_API_BASE" style="width: 100%" disabled />
        </a-form-item>
        <a-form-item label="API Key">
          <a-input-password
            v-model:value="form.llmApiKey"
            :placeholder="form.llmHasKey ? '已配置（留空保持不变）' : '请输入上游 API Key'"
            autocomplete="new-password"
          />
          <!-- key 为空时提示获取方式：Sophnet 去官网申请，自定义服务按服务方要求填写 -->
          <div v-if="!form.llmHasKey" class="mt-1 text-xs text-amber-600">
            <template v-if="form.llmApiBaseType === 'custom'">
              目前 key 为空，请填写所接入 OpenAI 兼容服务的 API Key（服务端不校验时可留空）
            </template>
            <template v-else>目前 key 为空，请点击上方 sophnet 链接获取 key</template>
          </div>
        </a-form-item>
        <a-form-item label="默认模型名称">
          <a-input
            v-model:value="form.llmModel"
            style="width: 100%"
            placeholder="DeepSeek-V4.1-Flash-1017"
          />
          <div class="mt-1 text-xs text-gray-400">
            转发时统一使用该模型名；自定义上游请填其实际支持的模型名。
            <template v-if="form.llmApiBaseType === 'custom'">
              非 Sophnet 上游按小上下文（20K）运行，长文档场景请留意截断。
            </template>
          </div>
        </a-form-item>
        <a-form-item
          label="启用 LLM 转发"
          tooltip="控制 llm-proxy 转发服务：开启后保存并启动 18080 转发服务（Reasonix 经此访问上游 LLM）；关闭则停用转发。"
        >
          <div class="flex items-center gap-2">
            <a-switch v-model:checked="form.llmEnabled" @change="onEnabledChange" />
            <a-tag :color="form.llmEnabled ? 'green' : 'red'">
              {{ form.llmEnabled ? '已启用' : '未启用' }}
            </a-tag>
          </div>
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
          </div>
        </div>
        <p class="mt-3 text-xs text-gray-400">
          控制 Agent（Reasonix）服务的运行状态：关闭后对话不可用，开启后可恢复对话。
        </p>
      </div>
    </a-card>
  </div>
</template>

<script lang="ts" setup>
  // @ts-nocheck
  import { reactive, ref, computed, onMounted } from 'vue';
  import { Card, Form, Input, Button, Switch, Alert, Tag, Radio, message } from 'ant-design-vue';
  import {
    getAgentConfig,
    saveAgentConfig,
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
  const AButton = Button;
  const ASwitch = Switch;
  const AAlert = Alert;
  const ATag = Tag;
  const ARadioGroup = Radio.Group;
  const ARadioButton = Radio.Button;

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

  // 上游类型：Sophnet（官方云端，地址固定）/ 自定义 OpenAI API（地址自填）。
  const SOPHNET_API_BASE = 'https://www.sophnet.com/api/open-apis/v1';
  const DEFAULT_LLM_MODEL = 'DeepSeek-V4.1-Flash-1017';

  const form = reactive({
    llmApiBase: '',
    llmApiBaseType: 'sophnet',
    llmApiKey: '',
    llmModel: '',
    llmEnabled: true,
    llmHasKey: false,
  });

  // 根据已存 apiBase 推断上游类型：等于 Sophnet 地址才算 sophnet，其余一律视为
  // 自定义 OpenAI API（含旧版写死的本地 127.0.0.1:8000 与任意第三方兼容服务）。
  function inferApiBaseType(apiBase: string): string {
    return apiBase && apiBase === SOPHNET_API_BASE ? 'sophnet' : 'custom';
  }

  // 类型切换：切到 Sophnet 时地址归位固定值；切到自定义时清空，交给用户填。
  function onApiBaseTypeChange(type: string | { target: { value: string } }) {
    const val = typeof type === 'string' ? type : type?.target?.value;
    if (val === 'sophnet') {
      form.llmApiBase = SOPHNET_API_BASE;
    } else if (form.llmApiBase === SOPHNET_API_BASE) {
      form.llmApiBase = '';
    }
  }

  async function init() {
    const cfg = await getAgentConfig();
    if (cfg) {
      // 空地址视为未配置：回落到出厂默认（Sophnet），避免被判成「自定义但地址空」
      const apiBase = cfg.llmApiBase || SOPHNET_API_BASE;
      form.llmApiBase = apiBase;
      form.llmApiBaseType = inferApiBaseType(apiBase);
      form.llmModel = cfg.llmModel || '';
      form.llmEnabled = cfg.llmEnabled !== false;
      form.llmHasKey = !!cfg.llmHasKey;
    }
  }

  // 提交前校验：自定义上游必须填 Base URL。
  function resolveApiBase(): string | null {
    const base = form.llmApiBase.trim();
    if (form.llmApiBaseType === 'sophnet') {
      return SOPHNET_API_BASE;
    }
    if (!base) {
      message.warning('请填写自定义 OpenAI API 的 Base URL');
      return null;
    }
    return base;
  }

  // llm-proxy 转发服务开关：切换即保存并立即生效（启动/停用 18080 转发服务）。
  // Reasonix 依赖该转发链路访问上游 LLM；关闭后上游转发停用、对话不可用。
  async function onEnabledChange(checked: boolean) {
    const apiBase = form.llmApiBaseType === 'sophnet' ? SOPHNET_API_BASE : form.llmApiBase.trim();
    // 关闭转发不需要上游地址；开启时必须先有地址（自定义模式可能尚未填写）。
    if (checked && !apiBase) {
      message.warning('请填写自定义 OpenAI API 的 Base URL');
      form.llmEnabled = false;
      return;
    }
    saving.value = true;
    const res = await saveAgentConfig({
      llmApiBase: apiBase,
      llmApiKey: form.llmApiKey,
      llmModel: form.llmModel.trim() || DEFAULT_LLM_MODEL,
      llmEnabled: checked,
    });
    saving.value = false;
    if (res.ok) {
      message.success(checked ? 'LLM 转发服务已启用' : 'LLM 转发服务已停用');
    } else {
      message.error(res.message || '切换失败');
    }
    form.llmApiKey = '';
    form.llmHasKey = true;
  }

  async function handleSave() {
    const apiBase = resolveApiBase();
    if (!apiBase) return;
    saving.value = true;
    const res = await saveAgentConfig({
      llmApiBase: apiBase,
      llmApiKey: form.llmApiKey,
      llmModel: form.llmModel.trim() || DEFAULT_LLM_MODEL,
      llmEnabled: form.llmEnabled,
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
