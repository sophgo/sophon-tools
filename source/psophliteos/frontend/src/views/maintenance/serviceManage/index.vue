<template>
  <div class="p-4">
    <a-card title="服务管理">
      <div class="mb-2 flex flex-wrap items-center" style="gap: 8px">
        <a-button size="small" @click="reload" :loading="loading">刷新</a-button>
        <a-input-search
          v-model:value="keyword"
          placeholder="按名称/描述过滤"
          size="small"
          style="width: 260px"
          allow-clear
        />
        <a-button size="small" @click="onDaemonReload" :loading="reloading">重载 systemd 配置</a-button>
        <a-dropdown>
          <a-button size="small">导出启动报告 <DownOutlined /></a-button>
          <template #overlay>
            <a-menu @click="onExport">
              <a-menu-item key="text">文本报告 (.txt)</a-menu-item>
              <a-menu-item key="svg">SVG 时序图 (.svg)</a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
      </div>

      <a-table
        :columns="columns"
        :data-source="filtered"
        :loading="loading"
        :pagination="{ pageSize: 20, showSizeChanger: true }"
        row-key="name"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <a-button type="link" size="small" @click="showDetail(record.name)">{{ record.name }}</a-button>
          </template>
          <template v-else-if="column.key === 'active_state'">
            <a-tag :color="activeColor(record)">{{ record.active_state }} / {{ record.sub_state }}</a-tag>
          </template>
          <template v-else-if="column.key === 'enabled_state'">
            <a-tag :color="record.enabled_state === 'enabled' ? 'green' : 'default'">{{ record.enabled_state || '-' }}</a-tag>
          </template>
          <template v-else-if="column.key === 'protected'">
            <a-tag v-if="record.protected" color="red">关键</a-tag>
            <a-tag v-else color="default">普通</a-tag>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space size="small">
              <a-button size="small" :disabled="record.protected" @click="doAction(record, 'start')">启动</a-button>
              <a-popconfirm title="确定停止该服务？" @confirm="doAction(record, 'stop')">
                <a-button size="small" danger :disabled="record.protected">停止</a-button>
              </a-popconfirm>
              <a-button size="small" :disabled="record.protected" @click="doAction(record, 'restart')">重启</a-button>
              <a-button size="small" :disabled="record.protected" @click="doAction(record, 'reload')">重载</a-button>
              <a-popconfirm v-if="record.enabled_state === 'enabled'" title="确定禁用开机自启？" @confirm="doAction(record, 'disable')">
                <a-button size="small" :disabled="record.protected">禁用自启</a-button>
              </a-popconfirm>
              <a-button v-else size="small" :disabled="record.protected" @click="doAction(record, 'enable')">启用自启</a-button>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-drawer
      v-model:visible="detailOpen"
      :title="detail?.name"
      width="680"
      placement="right"
    >
      <a-spin :spinning="detailLoading">
        <div v-if="detail">
          <a-descriptions size="small" :column="2" bordered>
            <a-descriptions-item label="Load">{{ detail.load_state }}</a-descriptions-item>
            <a-descriptions-item label="Active">{{ detail.active_state }} / {{ detail.sub_state }}</a-descriptions-item>
            <a-descriptions-item label="MainPID">{{ detail.main_pid }}</a-descriptions-item>
            <a-descriptions-item label="Fragment">{{ detail.fragment_path }}</a-descriptions-item>
            <a-descriptions-item label="ExecStart" :span="2">{{ detail.exec_start }}</a-descriptions-item>
          </a-descriptions>
          <a-divider>Unit 文件（只读）</a-divider>
          <pre class="code-block">{{ detail.unit_file }}</pre>
          <a-divider>状态</a-divider>
          <pre class="code-block">{{ detail.status_text }}</pre>
        </div>
      </a-spin>
    </a-drawer>
  </div>
</template>

<script lang="ts" setup>
  // @ts-nocheck
  import { ref, computed, onMounted } from 'vue';
  import {
    Card, Input, Table, Space, Button, Tag, Popconfirm, Drawer, Dropdown, Menu,
    Spin, Descriptions, Divider, message,
  } from 'ant-design-vue';
  import { DownOutlined } from '@ant-design/icons-vue';
  import {
    getServices, getServiceDetail, postServiceAction, postDaemonReload, exportBootReport,
    type ServiceInfo, type ServiceDetail,
  } from '/@/api/maintenance/ops';

  const ACard = Card;
  const AInputSearch = Input.Search;
  const ATable = Table;
  const ASpace = Space;
  const AButton = Button;
  const ATag = Tag;
  const APopconfirm = Popconfirm;
  const ADrawer = Drawer;
  const ADropdown = Dropdown;
  const AMenu = Menu;
  const AMenuItem = Menu.Item;
  const ASpin = Spin;
  const ADescriptions = Descriptions;
  const ADescriptionsItem = Descriptions.Item;
  const ADivider = Divider;

  const loading = ref(false);
  const reloading = ref(false);
  const keyword = ref('');
  const services = ref<ServiceInfo[]>([]);

  const detailOpen = ref(false);
  const detailLoading = ref(false);
  const detail = ref<ServiceDetail | null>(null);

  const columns = [
    { title: '服务名', dataIndex: 'name', key: 'name', width: 240 },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    { title: 'Active', key: 'active_state', width: 160 },
    { title: '开机自启', key: 'enabled_state', width: 110 },
    { title: '类型', key: 'protected', width: 80 },
    { title: '操作', key: 'action', width: 320 },
  ];

  const filtered = computed(() => {
    const kw = keyword.value.trim().toLowerCase();
    if (!kw) return services.value;
    return services.value.filter(
      (s) => s.name.toLowerCase().includes(kw) || (s.description || '').toLowerCase().includes(kw),
    );
  });

  function activeColor(r: ServiceInfo) {
    if (r.active_state === 'active' && r.sub_state === 'running') return 'green';
    if (r.active_state === 'failed') return 'red';
    return 'default';
  }

  async function load() {
    loading.value = true;
    try {
      services.value = await getServices();
    } catch (e: any) {
      message.error(e?.message || '加载服务列表失败');
    } finally {
      loading.value = false;
    }
  }
  function reload() {
    load();
  }

  async function showDetail(name: string) {
    detailOpen.value = true;
    detail.value = null;
    detailLoading.value = true;
    try {
      detail.value = await getServiceDetail(name);
    } catch (e: any) {
      message.error(e?.message || '加载详情失败');
    } finally {
      detailLoading.value = false;
    }
  }

  async function doAction(r: ServiceInfo, action: string) {
    try {
      await postServiceAction(r.name, action);
      message.success(`${action} ${r.name} 已执行`);
      await load();
    } catch (e: any) {
      message.error(e?.message || `${action} 失败`);
    }
  }

  async function onDaemonReload() {
    reloading.value = true;
    try {
      await postDaemonReload();
      message.success('daemon-reload 完成');
    } catch (e: any) {
      message.error(e?.message || 'daemon-reload 失败');
    } finally {
      reloading.value = false;
    }
  }

  async function onExport({ key }: { key: string }) {
    try {
      await exportBootReport(key as 'text' | 'svg');
      message.success('导出已开始');
    } catch (e: any) {
      message.error(e?.message || '导出失败');
    }
  }

  onMounted(load);
</script>

<style scoped>
  .code-block {
    background: #f5f5f5;
    padding: 8px 12px;
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 360px;
    overflow: auto;
    border-radius: 4px;
  }
</style>
