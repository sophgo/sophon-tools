<template>
  <div>
    <div v-show="loading" class="m-24px bg-white p-24px" style="width: calc(100% - 48px)">
      <a-skeleton :loading="loading" active :paragraph="{ rows: 6 }" />
    </div>
    <div class="!m-4 enter-y" v-if="!deviceStore.isSingleBoard">
      <Board class="!mb-4" :loading="loading" />
      <Status class="!mb-4" :loading="loading" />
      <DeviceInfo :loading="loading" />
    </div>
    <Detail v-if="deviceStore.isSingleBoard" class="enter-y" />
  </div>
</template>
<script lang="ts" setup>
  import { ref } from 'vue';
  import { storeToRefs } from 'pinia';
  import { Skeleton } from 'ant-design-vue';
  import DeviceInfo from './components/DeviceInfo.vue';
  import Status from './components/Status.vue';
  import Board from './components/Borad.vue';
  import Detail from './detail-se5.vue';

  import { useDeviceInfo } from '/@/store/modules/overview';
  const ASkeleton = Skeleton;
  const deviceStore = useDeviceInfo();
  const { deviceInfo } = storeToRefs(deviceStore);

  const loading = ref(false);
  if (!deviceInfo.value.deviceSn) {
    loading.value = true;
    deviceStore.getDeviceInfo().then(() => {
      loading.value = false;
    });
  }
</script>
