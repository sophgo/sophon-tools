<template>
  <div class="p-4">
    <WebChat v-if="ready" />
    <a-spin v-else :spinning="true">
      <div class="flex items-center justify-center" style="min-height: 200px"
        >正在初始化 AI Agent…</div
      >
    </a-spin>
  </div>
</template>

<script lang="ts" setup>
  // @ts-nocheck
  import { ref, onMounted } from 'vue';
  import { Spin } from 'ant-design-vue';
  import WebChat from './WebChat.vue';

  const ASpin = Spin;
  const ready = ref(false);

  onMounted(() => {
    ready.value = true;
  });
</script>
