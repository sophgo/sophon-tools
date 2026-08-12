<template>
  <div class="p-4">
    <a-card :bordered="false">
      <template #title>
        <a-space>
          <span>AI Agent</span>
        </a-space>
      </template>
      <WebChat v-if="ready" />
      <a-spin v-else :spinning="true">
        <div class="flex items-center justify-center" style="min-height: 200px"
          >正在初始化 AI Agent…</div
        >
      </a-spin>
    </a-card>
  </div>
</template>

<script lang="ts" setup>
  // @ts-nocheck
  import { ref, onMounted } from 'vue';
  import { Card, Space, Spin } from 'ant-design-vue';
  import WebChat from './WebChat.vue';

  const ACard = Card;
  const ASpace = Space;
  const ASpin = Spin;

  const ready = ref(false);

  onMounted(() => {
    ready.value = true;
  });
</script>
