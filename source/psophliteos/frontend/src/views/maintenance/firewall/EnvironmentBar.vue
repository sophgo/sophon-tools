<template>
  <div class="firewall-env-bar">
    <a-alert
      v-if="ok"
      type="success"
      show-icon
      :message="t('maintenance.firewall.envOk')"
    />
    <a-alert
      v-else
      type="error"
      show-icon
      :message="t('maintenance.firewall.envBad')"
      :description="t('maintenance.firewall.envBadDesc')"
    >
      <template #default>
        <div class="mt-2">
          <div v-for="(issue, i) in issues" :key="i" class="mb-2">
            <div class="font-medium">{{ issue.check }}: {{ issue.message }}</div>
            <div class="flex items-center mt-1" style="gap: 8px">
              <a-typography-text code copyable :content="issue.fix_cmd">
                {{ issue.fix_cmd }}
              </a-typography-text>
              <a-button size="small" type="primary" ghost @click="copyCmd(issue.fix_cmd)">
                {{ t('maintenance.firewall.copyFix') }}
              </a-button>
            </div>
          </div>
        </div>
      </template>
    </a-alert>
  </div>
</template>

<script lang="ts" setup>
  import { ref, onMounted } from 'vue';
  import { Alert, Typography, message } from 'ant-design-vue';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { copyTextToClipboard } from '/@/hooks/web/useCopyToClipboard';
  import { getStatus, type EnvIssue } from '/@/api/maintenance/firewall';

  const AAlert = Alert;
  const ATypographyText = Typography.Text;

  const { t } = useI18n();
  const emit = defineEmits<{ (e: 'env-ok', ok: boolean): void }>();

  const ok = ref(true);
  const issues = ref<EnvIssue[]>([]);

  async function load() {
    try {
      const res = await getStatus();
      ok.value = res?.environment?.ok ?? false;
      issues.value = res?.environment?.issues ?? [];
    } catch (e: any) {
      // errorMessageMode:'none' —— 静默失败，按环境异常处理
      ok.value = false;
      issues.value = [
        { check: 'status', message: e?.message || t('maintenance.firewall.envFetchFail'), fix_cmd: '' },
      ];
    } finally {
      emit('env-ok', ok.value);
    }
  }

  function copyCmd(cmd: string) {
    if (!cmd) return;
    const success = copyTextToClipboard(cmd);
    if (success) {
      message.success(t('maintenance.firewall.copied'));
    } else {
      message.error(t('maintenance.firewall.copyFail'));
    }
  }

  defineExpose({ reload: load });
  onMounted(load);
</script>

<style lang="less" scoped>
  .firewall-env-bar {
    margin: 8px 0;
  }
</style>
