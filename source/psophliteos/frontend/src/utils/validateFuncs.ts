import { useI18n } from '/@/hooks/web/useI18n';
const { t } = useI18n();

// IP check  粗略校验 {0~255}.{0~255}.{0~255}.{0~255}
export const IpCheck = (_rule, value) => {
  if (value.trim() === '') {
    return Promise.reject(t('maintenance.newworkSettings.inputIp'));
  } else {
    const ip = /^((\d{1,2}|1\d\d|2[0-4]\d|25[0-5])\.){3}(\d{1,2}|1\d\d|2[0-4]\d|25[0-5])$/;
    if (!ip.test(value)) {
      return Promise.reject(t('maintenance.newworkSettings.validateWrong'));
    } else {
      return Promise.resolve();
    }
  }
};

// subnetMask check  粗略校验 {0~255}.{0~255}.{0~255}.{0~255}
export const subnetMaskCheck = (_rule, value) => {
  if (value.trim() === '') {
    return Promise.reject(t('maintenance.newworkSettings.inpuSubnetMask'));
  } else {
    const subnetMask = /^((\d{1,2}|1\d\d|2[0-4]\d|25[0-5])\.){3}(\d{1,2}|1\d\d|2[0-4]\d|25[0-5])$/;
    if (!subnetMask.test(value)) {
      return Promise.reject(t('maintenance.newworkSettings.validateWrong'));
    } else {
      return Promise.resolve();
    }
  }
};

// gateway check  粗略校验 {0~255}.{0~255}.{0~255}.{0~255}；静态 IP 时网关可留空
export const gatewayCheck = (_rule, value) => {
  if (value.trim() === '') {
    return Promise.resolve();
  } else {
    const gateway = /^((\d{1,2}|1\d\d|2[0-4]\d|25[0-5])\.){3}(\d{1,2}|1\d\d|2[0-4]\d|25[0-5])$/;
    if (!gateway.test(value)) {
      return Promise.reject(t('maintenance.newworkSettings.validateWrong'));
    } else {
      return Promise.resolve();
    }
  }
};

// dns check, 粗略校验 {0~255}.{0~255}.{0~255}.{0~255}；静态 IP 时 DNS 可留空
export const dnsCheck = (_rule, value) => {
  if (value.trim() === '') {
    return Promise.resolve();
  } else {
    const dns = /^((\d{1,2}|1\d\d|2[0-4]\d|25[0-5])\.){3}(\d{1,2}|1\d\d|2[0-4]\d|25[0-5])$/;
    if (!dns.test(value)) {
      return Promise.reject(t('maintenance.newworkSettings.validateWrong'));
    } else {
      return Promise.resolve();
    }
  }
};

// multi IP check，
export const IpDoubleCheck = (_rule, value) => {
  if (value.trim() === '') {
    return Promise.reject(t('maintenance.newworkSettings.inputIp'));
  } else {
    const doubleIp =
      /^((\d{1,2}|1\d\d|2[0-4]\d|25[0-5])\.){3}(\d{1,2}|1\d\d|2[0-4]\d|25[0-5]),((\d{1,2}|1\d\d|2[0-4]\d|25[0-5])\.){3}(\d{1,2}|1\d\d|2[0-4]\d|25[0-5])$/;
    if (!doubleIp.test(value)) {
      return Promise.reject(t('maintenance.newworkSettings.validateWrong'));
    } else {
      return Promise.resolve();
    }
  }
};

// 密码校验：大写字母，小写字母、数字，特征字符至少3种，长度8-16位
export const passwordCheck = (_rule, value) => {
  const { t } = useI18n();
  if (value === '') {
    return Promise.reject(t('layout.header.inputNewPassword'));
  } else {
    const password =
      /^(?![\da-z]+$)(?![\dA-Z]+$)(?![\d!@#$%^&*]+$)(?![a-zA-Z]+$)(?![a-z!@#$%^&*]+$)(?![A-Z!@#$%^&*]+$)[\da-zA-z!@#$%^&*]{8,16}$/;
    if (!password.test(value)) {
      return Promise.reject(t('layout.header.passwordFormatError'));
    } else {
      return Promise.resolve();
    }
  }
};
