<template>
  <div class="p-4">
    <EnvironmentBar ref="envBarRef" @env-ok="onEnvOk" />
    <Intent v-if="envOk" class="mt-4" />
    <a-empty v-else :description="t('maintenance.firewall.envDisabledHint')" class="mt-4" />
  </div>
</template>

<script lang="ts" setup>
  import { ref } from 'vue';
  import { Empty } from 'ant-design-vue';
  import { useI18n } from '/@/hooks/web/useI18n';
  import EnvironmentBar from './EnvironmentBar.vue';
  import Intent from './Intent.vue';

  const AEmpty = Empty;

  const { t } = useI18n();

  const envOk = ref(true);
  const envBarRef = ref<InstanceType<typeof EnvironmentBar> | null>(null);

  function onEnvOk(ok: boolean) {
    envOk.value = ok;
  }
</script>
