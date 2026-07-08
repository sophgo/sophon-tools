<template>
  <div class="p-4">
    <a-card :title="t('maintenance.fileManage.title')">
      <div class="mb-2 flex flex-wrap items-center" style="gap: 8px">
        <!-- 地址栏：默认面包屑（点段跳转、点空白进编辑），编辑态可输入路径回车跳转 -->
        <div class="addrbar" @click="startEdit">
          <a-input
            v-if="editing"
            ref="addrInput"
            v-model:value="editPath"
            size="small"
            class="addr-input"
            placeholder="/absolute/path"
            @keyup.enter="commitEdit"
            @keyup.esc="cancelEdit"
            @blur="cancelEdit"
            @click.stop
          />
          <a-breadcrumb v-else separator="">
            <a-breadcrumb-item>
              <a @click.stop="goRoot">/</a>
            </a-breadcrumb-item>
            <a-breadcrumb-item v-for="(seg, idx) in pathParts" :key="idx">
              <a @click.stop="goToSeg(idx)">{{ seg }}</a>
              <span v-if="idx < pathParts.length - 1" class="sep">/</span>
            </a-breadcrumb-item>
          </a-breadcrumb>
        </div>
        <a-button size="small" @click="goParent" :disabled="!canGoParent">
          {{ t('maintenance.fileManage.parent') }}
        </a-button>
        <a-button size="small" @click="reload">{{ t('maintenance.fileManage.refresh') }}</a-button>
        <a-upload
          :show-upload-list="false"
          :before-upload="handleUpload"
          multiple
        >
          <a-button size="small" type="primary">
            {{ t('maintenance.fileManage.upload') }}
          </a-button>
        </a-upload>
        <a-button size="small" @click="openMkdir">{{ t('maintenance.fileManage.mkdir') }}</a-button>
      </div>

      <a-table
        :columns="columns"
        :data-source="fileList"
        :loading="loading"
        :pagination="false"
        row-key="name"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <a @click="enter(record)">
              <FolderOutlined v-if="record.isDir" />
              <FileOutlined v-else />
              {{ record.name }}
            </a>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space>
              <a-tooltip
                v-if="!record.isDir"
                :title="
                  record.size > MAX_CONTENT_SIZE
                    ? `文件 ${formatBytes(record.size)} 超过 ${formatBytes(MAX_CONTENT_SIZE)}，无法查看内容，请下载`
                    : ''
                "
              >
                <span>
                  <a-button
                    size="small"
                    :disabled="record.size > MAX_CONTENT_SIZE"
                    @click="viewContent(record)"
                  >{{ t('maintenance.fileManage.content') }}</a-button
                  >
                </span>
              </a-tooltip>
              <a-button v-if="!record.isDir" size="small" @click="download(record)">
                {{ t('maintenance.fileManage.download') }}
              </a-button>
              <a-button size="small" @click="openRename(record)">{{
                t('maintenance.fileManage.rename')
              }}</a-button>
              <a-button size="small" @click="openChmod(record)">{{
                t('maintenance.fileManage.chmod')
              }}</a-button>
              <a-button size="small" @click="openChown(record)">{{
                t('maintenance.fileManage.chown')
              }}</a-button>
              <a-popconfirm
                :title="t('maintenance.fileManage.deleteConfirm')"
                @confirm="removeFile(record)"
              >
                <a-button size="small" danger>{{ t('maintenance.fileManage.delete') }}</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <!-- 新建目录 -->
    <a-modal
      v-model:visible="mkdirVisible"
      :title="t('maintenance.fileManage.mkdir')"
      @ok="doMkdir"
    >
      <a-input v-model:value="mkdirPath" placeholder="/path/to/newdir" />
    </a-modal>

    <!-- 重命名 -->
    <a-modal
      v-model:visible="renameVisible"
      :title="t('maintenance.fileManage.renameTo')"
      @ok="doRename"
    >
      <a-input v-model:value="renameTarget" />
    </a-modal>

    <!-- 改权限 -->
    <a-modal
      v-model:visible="chmodVisible"
      :title="t('maintenance.fileManage.chmod')"
      @ok="doChmod"
    >
      <div class="mb-2">{{ t('maintenance.fileManage.mode') }}：</div>
      <div class="mb-2" style="font-family: monospace">
        <Checkbox v-model:checked="perm.ownerRead" @change="syncPerm">r</Checkbox>
        <Checkbox v-model:checked="perm.ownerWrite" @change="syncPerm">w</Checkbox>
        <Checkbox v-model:checked="perm.ownerExec" @change="syncPerm">x</Checkbox>
        <Checkbox v-model:checked="perm.groupRead" @change="syncPerm">r</Checkbox>
        <Checkbox v-model:checked="perm.groupWrite" @change="syncPerm">w</Checkbox>
        <Checkbox v-model:checked="perm.groupExec" @change="syncPerm">x</Checkbox>
        <Checkbox v-model:checked="perm.otherRead" @change="syncPerm">r</Checkbox>
        <Checkbox v-model:checked="perm.otherWrite" @change="syncPerm">w</Checkbox>
        <Checkbox v-model:checked="perm.otherExec" @change="syncPerm">x</Checkbox>
      </div>
      <a-input v-model:value="perm.octal" placeholder="0755" style="font-family: monospace" />
    </a-modal>

    <!-- 改所有权 -->
    <a-modal
      v-model:visible="chownVisible"
      :title="t('maintenance.fileManage.chown')"
      @ok="doChown"
    >
      <div class="mb-2">{{ t('maintenance.fileManage.owner') }}：</div>
      <a-input v-model:value="chownOwner" class="mb-2" />
      <div class="mb-2">{{ t('maintenance.fileManage.group') }}：</div>
      <a-input v-model:value="chownGroup" />
    </a-modal>

    <!-- 查看内容 -->
    <a-modal
      v-model:visible="contentVisible"
      :title="t('maintenance.fileManage.contentTitle')"
      :footer="null"
      width="800px"
    >
      <pre style="max-height: 60vh; overflow: auto">{{ contentText }}</pre>
    </a-modal>

    <!-- 上传进度 -->
    <a-modal
      v-model:visible="progress.visible"
      :title="progress.title"
      :footer="null"
      :closable="false"
      :mask-closable="false"
      :mask="false"
      width="480px"
      :z-index="2000"
    >
      <a-progress :percent="progress.percent" :status="progress.status" />
      <div class="mt-2 text-center" style="color: #888">
        <span v-if="progress.total > 0">
          {{ formatBytes(progress.loaded) }} / {{ formatBytes(progress.total) }}
          ·
        </span>
        <span>{{ progress.percent }}%</span>
        <span v-if="progress.speedText"> · {{ progress.speedText }}</span>
      </div>
    </a-modal>
  </div>
</template>

<script lang="ts" setup>
  import { ref, reactive, computed, onMounted, nextTick } from 'vue';
  import {
    Card,
    Modal,
    Input,
    Table,
    Space,
    Popconfirm,
    Upload,
    Button,
    Checkbox,
    Breadcrumb,
    Progress,
    Tooltip,
  } from 'ant-design-vue';
  import { FolderOutlined, FileOutlined } from '@ant-design/icons-vue';
  import { useI18n } from '/@/hooks/web/useI18n';
  import { useMessage } from '/@/hooks/web/useMessage';
  import {
    listFiles,
    getContent,
    downloadFile,
    uploadFile,
    chmod,
    chown,
    mkdir,
    renameFile,
    deleteFile,
    type FileInfo,
  } from '/@/api/filemanage/index';

  const ACard = Card;
  const AModal = Modal;
  const AInput = Input;
  const ATable = Table;
  const ASpace = Space;
  const AButton = Button;
  const APopconfirm = Popconfirm;
  const AUpload = Upload;
  const ACheckbox = Checkbox;
  const ABreadcrumb = Breadcrumb;
  const ABreadcrumbItem = Breadcrumb.Item;
  const AProgress = Progress;
  const ATooltip = Tooltip;

  const { t } = useI18n();
  const { createMessage } = useMessage();

  const loading = ref(false);
  const fileList = ref<FileInfo[]>([]);
  const currentPath = ref('');

  // 面包屑段：currentPath 形如 /root/sub，拆出非空段。前导 / 在模板里以 /段名 形式呈现，
  // 段间无额外分隔符，避免 // 双斜杠。
  const pathParts = computed(() => currentPath.value.split('/').filter(Boolean));
  const canGoParent = computed(() => pathParts.value.length > 0);

  const columns = computed(() => [
    { title: t('maintenance.fileManage.name'), key: 'name', dataIndex: 'name' },
    { title: t('maintenance.fileManage.size'), dataIndex: 'size', width: 100 },
    { title: t('maintenance.fileManage.mode'), dataIndex: 'mode', width: 120 },
    { title: t('maintenance.fileManage.owner'), dataIndex: 'owner', width: 100 },
    { title: t('maintenance.fileManage.group'), dataIndex: 'group', width: 100 },
    { title: t('maintenance.fileManage.modTime'), dataIndex: 'modTime', width: 160,
      customRender: ({ text }: any) => (text ? new Date(text * 1000).toLocaleString() : '-') },
    { title: '', key: 'action', width: 360 },
  ]);

  async function load(path?: string) {
    loading.value = true;
    try {
      const res = await listFiles(path);
      currentPath.value = res?.path || path || '';
      fileList.value = res?.files || [];
    } catch (e: any) {
      createMessage.error(e?.message || t('maintenance.fileManage.invalidPath'));
    } finally {
      loading.value = false;
    }
  }

  function reload() {
    load(currentPath.value);
  }

  function goToSeg(idx: number) {
    const parts = pathParts.value.slice(0, idx + 1);
    load('/' + parts.join('/'));
  }

  function goRoot() {
    // 跳文件系统根目录 "/"，不能用空串（空串被 ssm ResolvePath 当作家目录）
    load('/');
  }

  function goParent() {
    const parts = currentPath.value.split('/').filter(Boolean);
    parts.pop();
    // 到根时跳 "/"（家目录是空串语义，会卡在 /root 到不了 /）
    load(parts.length ? '/' + parts.join('/') : '/');
  }

  // 地址栏编辑：点空白进编辑态，回车跳转，Esc/blur 取消
  const editing = ref(false);
  const editPath = ref('');
  const addrInput = ref();
  async function startEdit() {
    editPath.value = currentPath.value || '/';
    editing.value = true;
    await nextTick();
    addrInput.value?.focus?.();
    addrInput.value?.select?.();
  }
  function commitEdit() {
    const p = (editPath.value || '').trim();
    editing.value = false;
    if (!p) return;
    load(p);
  }
  function cancelEdit() {
    editing.value = false;
  }

  function enter(record: FileInfo) {
    if (record.isDir) {
      const base = currentPath.value.endsWith('/') ? currentPath.value : currentPath.value + '/';
      load(base + record.name);
    } else {
      viewContent(record);
    }
  }

  // 进度条（上传/下载共用）：弹窗 a-progress 显示百分比 + 速度 + 已传/总大小
  const progress = reactive({
    visible: false,
    title: '',
    percent: 0,
    loaded: 0,
    total: 0,
    speedText: '',
    status: 'active' as 'active' | 'success' | 'exception',
    _lastTime: 0,
    _lastLoaded: 0,
  });

  function startProgress(title: string) {
    progress.visible = true;
    progress.title = title;
    progress.percent = 0;
    progress.loaded = 0;
    progress.total = 0;
    progress.speedText = '';
    progress.status = 'active';
    progress._lastTime = Date.now();
    progress._lastLoaded = 0;
  }

  function updateProgress(loaded: number, total: number) {
    progress.loaded = loaded;
    progress.total = total;
    progress.percent = total > 0 ? Math.min(100, Math.round((loaded / total) * 100)) : 0;
    const now = Date.now();
    const dt = (now - progress._lastTime) / 1000;
    // 每 0.3s 更新一次速度，避免抖动
    if (dt >= 0.3) {
      const dl = loaded - progress._lastLoaded;
      if (dl > 0 && dt > 0) {
        progress.speedText = formatBytes(dl / dt) + '/s';
      }
      progress._lastTime = now;
      progress._lastLoaded = loaded;
    }
  }

  function finishProgress(ok: boolean) {
    progress.status = ok ? 'success' : 'exception';
    if (ok) progress.percent = 100;
    setTimeout(() => {
      progress.visible = false;
    }, 800);
  }

  // 文本查看大小上限（字节），对齐 ssm ReadContent 的 maxContentSize=1MiB：
  // 超过则禁用"查看内容"按钮（点了也会被后端拒），改引导下载。
  const MAX_CONTENT_SIZE = 1 << 20;

  function formatBytes(n: number): string {
    if (!n || n < 0) return '0 B';
    if (n < 1024) return n.toFixed(0) + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
    return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
  }

  // 上传：XHR onUploadProgress 流式回调，弹窗进度
  async function handleUpload(file: File) {
    startProgress(t('maintenance.fileManage.upload') + ': ' + file.name);
    try {
      await uploadFile(currentPath.value, file, (loaded, total) =>
        updateProgress(loaded, total),
      );
      finishProgress(true);
      createMessage.success(t('maintenance.fileManage.upload') + ' OK');
      reload();
    } catch (e: any) {
      finishProgress(false);
      createMessage.error(e?.message || 'upload failed');
    }
    return false; // 阻止 antd 自动上传
  }

  // 下载：原生 <a download>，浏览器流式落盘（低内存），浏览器自带下载进度条。
  // 不再走 XHR blob + 应用内进度弹窗（大文件会撑爆浏览器内存）。
  function download(record: FileInfo) {
    const base = currentPath.value.endsWith('/') ? currentPath.value : currentPath.value + '/';
    const full = base + record.name;
    const { url, name } = downloadFile(full);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  // 查看内容
  const contentVisible = ref(false);
  const contentText = ref('');
  async function viewContent(record: FileInfo) {
    const base = currentPath.value.endsWith('/') ? currentPath.value : currentPath.value + '/';
    const full = base + record.name;
    try {
      const res = await getContent(full);
      contentText.value = res?.content ?? '';
      contentVisible.value = true;
    } catch (e: any) {
      createMessage.error(e?.message || 'read failed');
    }
  }

  // 新建目录
  const mkdirVisible = ref(false);
  const mkdirPath = ref('');
  function openMkdir() {
    mkdirPath.value = currentPath.value.endsWith('/')
      ? currentPath.value
      : currentPath.value + '/';
    mkdirVisible.value = true;
  }
  async function doMkdir() {
    try {
      await mkdir(mkdirPath.value);
      createMessage.success('OK');
      mkdirVisible.value = false;
      reload();
    } catch (e: any) {
      createMessage.error(e?.message || 'mkdir failed');
    }
  }

  // 重命名
  const renameVisible = ref(false);
  const renameTarget = ref('');
  let renameSource = '';
  function openRename(record: FileInfo) {
    const base = currentPath.value.endsWith('/') ? currentPath.value : currentPath.value + '/';
    renameSource = base + record.name;
    renameTarget.value = renameSource;
    renameVisible.value = true;
  }
  async function doRename() {
    try {
      await renameFile(renameSource, renameTarget.value);
      createMessage.success('OK');
      renameVisible.value = false;
      reload();
    } catch (e: any) {
      createMessage.error(e?.message || 'rename failed');
    }
  }

  // 改权限
  const chmodVisible = ref(false);
  const perm = reactive({
    ownerRead: false, ownerWrite: false, ownerExec: false,
    groupRead: false, groupWrite: false, groupExec: false,
    otherRead: false, otherWrite: false, otherExec: false,
    octal: '0755',
  });
  let chmodPath = '';
  function openChmod(record: FileInfo) {
    const base = currentPath.value.endsWith('/') ? currentPath.value : currentPath.value + '/';
    chmodPath = base + record.name;
    parseMode(record.mode);
    chmodVisible.value = true;
  }
  function parseMode(modeStr: string) {
    // 形如 drwxr-xr-x
    const m = (modeStr || '').slice(-9);
    const chk = (i: number, ch: string) => m[i] === ch;
    perm.ownerRead = chk(0, 'r'); perm.ownerWrite = chk(1, 'w'); perm.ownerExec = chk(2, 'x');
    perm.groupRead = chk(3, 'r'); perm.groupWrite = chk(4, 'w'); perm.groupExec = chk(5, 'x');
    perm.otherRead = chk(6, 'r'); perm.otherWrite = chk(7, 'w'); perm.otherExec = chk(8, 'x');
    syncPerm();
  }
  function syncPerm() {
    const o = (perm.ownerRead ? 4 : 0) + (perm.ownerWrite ? 2 : 0) + (perm.ownerExec ? 1 : 0);
    const g = (perm.groupRead ? 4 : 0) + (perm.groupWrite ? 2 : 0) + (perm.groupExec ? 1 : 0);
    const w = (perm.otherRead ? 4 : 0) + (perm.otherWrite ? 2 : 0) + (perm.otherExec ? 1 : 0);
    perm.octal = '0' + String(o) + String(g) + String(w);
  }
  async function doChmod() {
    try {
      await chmod(chmodPath, perm.octal);
      createMessage.success('OK');
      chmodVisible.value = false;
      reload();
    } catch (e: any) {
      createMessage.error(e?.message || 'chmod failed');
    }
  }

  // 改所有权
  const chownVisible = ref(false);
  const chownOwner = ref('');
  const chownGroup = ref('');
  let chownPath = '';
  function openChown(record: FileInfo) {
    const base = currentPath.value.endsWith('/') ? currentPath.value : currentPath.value + '/';
    chownPath = base + record.name;
    chownOwner.value = record.owner || '';
    chownGroup.value = record.group || '';
    chownVisible.value = true;
  }
  async function doChown() {
    try {
      await chown(chownPath, chownOwner.value, chownGroup.value);
      createMessage.success('OK');
      chownVisible.value = false;
      reload();
    } catch (e: any) {
      createMessage.error(e?.message || 'chown failed');
    }
  }

  // 删除
  async function removeFile(record: FileInfo) {
    const base = currentPath.value.endsWith('/') ? currentPath.value : currentPath.value + '/';
    const full = base + record.name;
    try {
      await deleteFile(full);
      createMessage.success('OK');
      reload();
    } catch (e: any) {
      createMessage.error(e?.message || 'delete failed');
    }
  }

  onMounted(() => {
    load('');
  });
</script>
<style lang="less" scoped>
  .addrbar {
    display: inline-flex;
    align-items: center;
    flex: 1 1 320px;
    min-width: 240px;
    max-width: 70%;
    padding: 2px 10px;
    border: 1px solid #d9d9d9;
    border-radius: 4px;
    background: #fafafa;
    font-family: monospace;
    overflow-x: auto;
    cursor: text;

    .addr-input {
      width: 100%;
      font-family: monospace;
    }
    white-space: nowrap;

    a {
      color: #0960bd;
      cursor: pointer;
      &:hover {
        text-decoration: underline;
      }
    }
    .sep {
      color: #bbb;
      margin: 0 2px;
    }
    /* 隐藏 a-breadcrumb-item 默认分隔符容器间距 */
    :deep(.ant-breadcrumb-link) {
      display: inline-flex;
      align-items: center;
    }
  }
</style>
