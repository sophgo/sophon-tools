<template>
  <div class="p-4">
    <a-card title="端口状态">
      <div class="mb-2 flex flex-wrap items-center" style="gap: 8px">
        <a-select
          v-model:value="proto"
          style="width: 140px"
          :options="protoOptions"
          @change="reload"
        />
        <a-button size="small" @click="reload" :loading="loading">刷新</a-button>
      </div>
      <a-table
        :columns="columns"
        :data-source="sockets"
        :loading="loading"
        :pagination="{ pageSize: 50, showSizeChanger: true }"
        :row-key="rowKey"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'proto'">
            <a-tag :color="record.proto === 'tcp' || record.proto === 'tcp6' ? 'green' : 'blue'">{{ record.proto }}</a-tag>
          </template>
        </template>
      </a-table>
    </a-card>
  </div>
</template>

<script lang="ts" setup>
  // @ts-nocheck
  import { ref, onMounted } from 'vue';
  import { Card, Select, Table, Tag, message } from 'ant-design-vue';
  import { getPortColumns } from './tableData';
  import { getListeningPorts, type ListeningSocket } from '/@/api/maintenance/ops';

  const ACard = Card;
  const ASelect = Select;
  const ATable = Table;
  const ATag = Tag;

  const loading = ref(false);
  const proto = ref<'all' | 'tcp' | 'udp'>('all');
  const sockets = ref<ListeningSocket[]>([]);
  const columns = getPortColumns();

  const protoOptions = [
    { label: '全部', value: 'all' },
    { label: 'TCP', value: 'tcp' },
    { label: 'UDP', value: 'udp' },
  ];

  function rowKey(r: ListeningSocket) {
    return `${r.proto}:${r.local_ip}:${r.local_port}:${r.pid}:${r.inode}`;
  }

  async function reload() {
    loading.value = true;
    try {
      const p = proto.value === 'all' ? undefined : (proto.value as 'tcp' | 'udp');
      sockets.value = await getListeningPorts(p);
    } catch (e: any) {
      message.error(e?.message || '加载端口列表失败');
    } finally {
      loading.value = false;
    }
  }

  onMounted(reload);
</script>
