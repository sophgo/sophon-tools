<template>
  <BasicModal
    :footer="null"
    :title="t('overview.softInfo.title')"
    v-bind="$attrs"
    :height="600"
    width="1080px"
    :class="prefixCls"
    @register="register"
  >
    <div :class="`${prefixCls}__entry`">
      <SoftInfo />
    </div>
  </BasicModal>
</template>
<script lang="ts">
  import { defineComponent, ref } from 'vue';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { useDesign } from '/@/hooks/web/useDesign';
  import { BasicModal, useModalInner } from '/@/components/Modal/index';
  import SoftInfo from './SoftInfo.vue';

  export default defineComponent({
    name: 'SoftwareVersion',
    components: { BasicModal, SoftInfo },

    setup() {
      const loading = ref(false);

      const { t } = useI18n();
      const { prefixCls } = useDesign('header-software-version-modal');

      const [register] = useModalInner();

      return {
        loading,
        t,
        prefixCls,
        register,
      };
    },
  });
</script>
<style lang="less">
  @prefix-cls: ~'@{namespace}-header-change-password-modal';

  .@{prefix-cls} {
    &__entry {
      position: relative;
      //height: 240px;
      padding: 30px;
      border-radius: 10px;
    }

    &__header {
      position: absolute;
      top: 0;
      left: calc(50% - 45px);
      width: auto;
      text-align: center;
    }

    &__footer {
      text-align: center;
    }
  }
</style>
