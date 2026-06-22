<template>
  <span :class="`${prefixCls}__extra-redo`" @click="handleRedo">
    <RedoOutlined :spin="loading" />
  </span>
</template>
<script lang="ts">
  import { defineComponent, ref } from 'vue';
  import { RedoOutlined } from '@ant-design/icons-vue';
  import { useDesign } from '/@/hooks/web/useDesign';
  import { useTabs } from '/@/hooks/web/useTabs';
  import { useDeviceInfo } from '/@/store/modules/overview';

  export default defineComponent({
    name: 'TabRedo',
    components: { RedoOutlined },

    setup() {
      const loading = ref(false);

      const { prefixCls } = useDesign('multiple-tabs-content');
      const { refreshPage } = useTabs();

      async function handleRedo() {
        loading.value = true;
        // resource接口有缓存，点击刷新时，重新获取数据
        const deviceStore = useDeviceInfo();
        deviceStore.getDeviceInfo();

        await refreshPage();
        setTimeout(() => {
          loading.value = false;
          // Animation execution time
        }, 1200);
      }
      return { prefixCls, handleRedo, loading };
    },
  });
</script>
