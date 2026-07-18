<template>
  <BasicModal
    v-bind="$attrs"
    @register="registerModal"
    :title="t('maintenance.firewall.applyConfirmTitle')"
    :can-fullscreen="false"
    :mask-closable="false"
    :closable="false"
    width="520px"
    :ok-text="t('maintenance.firewall.confirmKeep')"
    :cancel-text="t('maintenance.firewall.rollbackNow')"
    @ok="handleConfirm"
    @cancel="handleRollback"
  >
    <div class="firewall-apply-confirm">
      <a-alert
        type="success"
        show-icon
        :message="t('maintenance.firewall.appliedMsg')"
      />
      <p class="my-3">{{ t('maintenance.firewall.confirmPrompt') }}</p>
      <div class="countdown-row">
        <span class="mr-2">{{ t('maintenance.firewall.autoRollbackIn') }}</span>
        <span class="countdown-num">{{ countdown }}</span>
        <span class="ml-1">s</span>
      </div>
      <a-progress :percent="percent" :show-info="false" status="active" />
    </div>
  </BasicModal>
</template>

<script lang="ts" setup>
  import { ref, computed, onUnmounted } from 'vue';
  import { Alert, Progress, message } from 'ant-design-vue';
  import { BasicModal, useModalInner } from '/@/components/Modal';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { confirmApply, rollbackApply } from '/@/api/maintenance/firewall';

  const AAlert = Alert;
  const AProgress = Progress;

  const { t } = useI18n();
  const emit = defineEmits(['success', 'rollback', 'register']);

  const token = ref('');
  const rollbackSeconds = ref(300);
  const countdown = ref(300);
  const percent = computed(() =>
    rollbackSeconds.value > 0
      ? Math.round((countdown.value / rollbackSeconds.value) * 100)
      : 0,
  );

  let timer: ReturnType<typeof setInterval> | null = null;

  function clearTimer() {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
  }

  function startCountdown() {
    clearTimer();
    countdown.value = rollbackSeconds.value;
    timer = setInterval(() => {
      countdown.value -= 1;
      if (countdown.value <= 0) {
        clearTimer();
        // 倒计时归零 → 自动回滚（用户未确认即视为失联，安全侧）
        handleRollback();
      }
    }, 1000);
  }

  const [registerModal, { setModalProps, closeModal }] = useModalInner(async (data) => {
    setModalProps({ confirmLoading: false });
    token.value = data?.token || '';
    rollbackSeconds.value = data?.rollbackSeconds && data.rollbackSeconds > 0 ? data.rollbackSeconds : 300;
    startCountdown();
  });

  async function handleConfirm() {
    if (!token.value) {
      message.error(t('maintenance.firewall.noToken'));
      return;
    }
    try {
      setModalProps({ confirmLoading: true });
      await confirmApply({ token: token.value });
      clearTimer();
      message.success(t('maintenance.firewall.confirmed'));
      emit('success');
      closeModal();
    } catch (e: any) {
      message.error(e?.message || t('maintenance.firewall.confirmFail'));
    } finally {
      setModalProps({ confirmLoading: false });
    }
  }

  async function handleRollback() {
    if (!token.value) {
      closeModal();
      return;
    }
    try {
      setModalProps({ confirmLoading: true });
      await rollbackApply({ token: token.value });
      clearTimer();
      message.warning(t('maintenance.firewall.rolledback'));
      emit('rollback');
      closeModal();
    } catch (e: any) {
      message.error(e?.message || t('maintenance.firewall.rollbackFail'));
    } finally {
      setModalProps({ confirmLoading: false });
    }
  }

  onUnmounted(clearTimer);
</script>

<style lang="less" scoped>
  .firewall-apply-confirm {
    .countdown-row {
      display: flex;
      align-items: baseline;
      margin-bottom: 8px;
    }
    .countdown-num {
      font-size: 22px;
      font-weight: 600;
      color: #0960bd;
    }
  }
</style>
