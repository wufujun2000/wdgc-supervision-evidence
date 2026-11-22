<!-- 平台域「租户开通」：列表 + 一步开通（管理员三选一）+ 冻结/解冻 + 绑定管理 -->
<template>
  <div class="fa-full-height">
    <FaSearchBar
      v-show="showSearchBar"
      ref="searchBarRef"
      v-model="searchForm"
      :items="searchItems"
      :is-expand="false"
      :show-expand="false"
      :show-reset="true"
      :show-search="true"
      :disabled-search="false"
      :default-expanded="true"
      @search="handleSearchBarSearch"
      @reset="onResetSearch"
    />

    <ElCard class="fa-table-card" :style="{ 'margin-top': showSearchBar ? '12px' : '0' }">
      <FaTableHeader
        v-model:columns="columnChecks"
        v-model:showSearchBar="showSearchBar"
        :loading="loading"
        @refresh="refreshData"
      >
        <template #left>
          <ElButton
            v-if="checkPerm('module_platform:enterprise:create')"
            type="primary"
            @click="openProvision"
          >
            开通租户
          </ElButton>
        </template>
      </FaTableHeader>

      <FaTable
        ref="faTableRef"
        :loading="loading"
        :data="data"
        :columns="columns"
        :pagination="pagination"
        @pagination:size-change="handleSizeChange"
        @pagination:current-change="handleCurrentChange"
      >
        <template #empty>
          <FaEmptyState
            icon="ri:building-4-line"
            title="暂无企业租户"
            description="开通第一家监理企业租户"
          />
        </template>
      </FaTable>
    </ElCard>

    <!-- 一步开通 -->
    <FaDialog
      v-model="provisionVisible"
      title="开通租户"
      dialog-class="crud-embed-dialog"
      form-mode="create"
      confirm-text="开通"
      :confirm-loading="provisionSubmitLoading"
      @cancel="provisionVisible = false"
      @close="provisionVisible = false"
      @confirm="submitProvision"
      size="lg"
    >
      <FaForm
        :key="provisionFormRenderKey"
        ref="provisionFormRef"
        v-model="provisionForm"
        :items="provisionFormItems"
        :rules="provisionRules"
        label-suffix=":"
        :label-width="110"
        label-position="right"
        :span="24"
        :gutter="16"
        :show-reset="false"
        :show-submit="false"
        scrollbar
        max-height="65vh"
      >
        <template #admin_mode>
          <ElRadioGroup v-model="provisionForm.admin_mode">
            <ElRadio value="create">新建管理员账号</ElRadio>
            <ElRadio value="bind">绑定已有账号</ElRadio>
            <ElRadio value="none">暂不指定</ElRadio>
          </ElRadioGroup>
        </template>
        <template #admin_user_id>
          <FaUserTableSelect
            :model-value="provisionForm.admin_user_id"
            @update:model-value="(v: number | undefined) => (provisionForm.admin_user_id = v)"
          />
        </template>
      </FaForm>
      <ElAlert
        v-if="provisionForm.admin_mode === 'create'"
        type="info"
        :closable="false"
        class="mt-2"
        title="初始密码留空将自动生成，仅在开通成功后显示一次，请线下告知企业管理员（短信通知后续完善）。"
      />
    </FaDialog>

    <!-- 初始密码一次性展示 -->
    <FaDialog
      v-model="passwordVisible"
      title="开通成功 · 初始密码仅显示一次"
      form-mode="detail"
      size="sm"
      @close="passwordVisible = false"
    >
      <ElAlert
        type="warning"
        :closable="false"
        title="请立即复制并线下告知企业管理员。关闭后不可再查，若遗失请使用「用户管理 → 重置密码」。"
      />
      <div class="mt-4 flex flex-col gap-3">
        <ElInput :model-value="passwordInfo.username" readonly>
          <template #prepend>管理员账号</template>
        </ElInput>
        <ElInput :model-value="passwordInfo.password" readonly>
          <template #prepend>初始密码</template>
          <template #append>
            <ElButton @click="copyText(passwordInfo.password)">复制</ElButton>
          </template>
        </ElInput>
      </div>
    </FaDialog>

    <!-- 编辑 -->
    <FaDialog
      v-model="editVisible"
      title="编辑企业"
      form-mode="update"
      :confirm-loading="editSubmitLoading"
      @cancel="editVisible = false"
      @close="editVisible = false"
      @confirm="submitEdit"
      size="md"
    >
      <FaForm
        ref="editFormRef"
        v-model="editForm"
        :items="editFormItems"
        :rules="editRules"
        label-suffix=":"
        :label-width="110"
        label-position="right"
        :span="24"
        :show-reset="false"
        :show-submit="false"
      />
    </FaDialog>

    <!-- 详情 -->
    <FaDialog
      v-model="detailVisible"
      title="企业详情"
      form-mode="detail"
      size="lg"
      @close="detailVisible = false"
    >
      <FaDescriptions
        :column="2"
        :data="detailData"
        :items="detailItems"
        label-width="120px"
        max-height="70vh"
      />
    </FaDialog>

    <!-- 绑定管理 -->
    <FaDialog
      v-model="bindingsVisible"
      :title="`绑定管理 · ${currentEnterprise?.name ?? ''}`"
      form-mode="detail"
      size="lg"
      @close="bindingsVisible = false"
    >
      <div
        v-if="checkPerm('module_platform:enterprise:bind')"
        class="mb-4 flex flex-wrap items-center gap-3"
      >
        <FaUserTableSelect
          :model-value="bindForm.user_id"
          @update:model-value="(v: number | undefined) => (bindForm.user_id = v)"
        />
        <ElCheckbox v-model="bindForm.is_enterprise_admin">企业管理员</ElCheckbox>
        <ElInput v-model="bindForm.emp_no" placeholder="工号（可空）" class="w-36" clearable />
        <ElButton type="primary" :loading="bindSubmitLoading" @click="submitBind"
          >添加绑定</ElButton
        >
      </div>
      <ElTable v-loading="bindingsLoading" :data="bindings" border>
        <ElTableColumn prop="username" label="登录账号" min-width="140" />
        <ElTableColumn prop="name" label="姓名" min-width="120" />
        <ElTableColumn label="角色" width="120" align="center">
          <template #default="{ row }">
            <FaStatusTag
              :type="row.is_enterprise_admin ? 'primary' : 'info'"
              :label="row.is_enterprise_admin ? '企业管理员' : '普通成员'"
            />
          </template>
        </ElTableColumn>
        <ElTableColumn prop="emp_no" label="工号" min-width="100">
          <template #default="{ row }">{{ row.emp_no || "—" }}</template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="100" align="center">
          <template #default="{ row }">
            <ElButton
              v-if="checkPerm('module_platform:enterprise:unbind')"
              link
              type="danger"
              size="small"
              @click="handleUnbind(row)"
            >
              解绑
            </ElButton>
          </template>
        </ElTableColumn>
      </ElTable>
    </FaDialog>
  </div>
</template>

<script setup lang="ts">
import EnterpriseAPI, {
  type EnterpriseCreateForm,
  type EnterpriseTable,
  type TenantUserBinding,
} from "@/api/module_platform/enterprise";
import FaSearchBar, { type SearchFormItem } from "@/components/forms/fa-search-bar/index.vue";
import FaForm, { type FormItem } from "@/components/forms/fa-form/index.vue";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import FaDescriptions from "@/components/display/fa-descriptions/index.vue";
import { useTable } from "@/hooks/core/useTable";
import { confirmAction } from "@/hooks/core/useConfirm";
import { checkPerm } from "@/utils/checkPerm";
import {
  formatDateTime,
  renderTableOperationCell,
  resolveStatusColumns,
  type TableOperationAction,
} from "@utils";
import { ElMessage } from "element-plus";

defineOptions({
  name: "PlatformEnterprise",
  inheritAttrs: false,
});

type EnterpriseSearchForm = {
  name?: string;
  enterprise_code?: string;
  status?: number;
};

const STATUS_OPTIONS = [
  { label: "正常", value: 1 },
  { label: "冻结", value: 0 },
] as const;

const searchForm = ref<EnterpriseSearchForm>({
  name: undefined,
  enterprise_code: undefined,
  status: undefined,
});
const showSearchBar = ref(true);
const searchBarRef = ref<InstanceType<typeof FaSearchBar> | null>(null);

const searchItems = computed<SearchFormItem[]>(() => [
  {
    label: "企业名称",
    key: "name",
    type: "input",
    placeholder: "请输入企业名称",
    clearable: true,
    span: 6,
  },
  {
    label: "企业编码",
    key: "enterprise_code",
    type: "input",
    placeholder: "请输入企业编码",
    clearable: true,
    span: 6,
  },
  {
    label: "状态",
    key: "status",
    type: "select",
    props: { placeholder: "请选择状态", options: STATUS_OPTIONS, clearable: true },
    span: 6,
  },
]);

const faTableRef = ref<{ elTableRef?: { clearSelection: () => void } } | null>(null);

// ─── 列表 ───
const {
  columns,
  columnChecks,
  data,
  loading,
  pagination,
  getData,
  replaceSearchParams,
  resetSearchParams,
  handleSizeChange,
  handleCurrentChange,
  refreshData,
  refreshCreate,
} = useTable({
  core: {
    apiFn: EnterpriseAPI.listEnterprise,
    apiParams: { page_no: 1, page_size: 10 },
    columnsFactory: resolveStatusColumns<EnterpriseTable>(() => [
      { type: "globalIndex", width: 56, label: "序号" },
      { prop: "enterprise_code", label: "企业编码", minWidth: 130, showOverflowTooltip: true },
      { prop: "name", label: "企业名称", minWidth: 160, showOverflowTooltip: true },
      { prop: "credit_code", label: "统一社会信用代码", minWidth: 180, showOverflowTooltip: true },
      {
        prop: "status",
        label: "状态",
        width: 88,
        status: {
          1: { type: "success", text: "正常" },
          0: { type: "danger", text: "冻结" },
        },
      },
      { prop: "description", label: "备注", minWidth: 120, showOverflowTooltip: true },
      {
        prop: "created_time",
        label: "创建时间",
        width: 180,
        showOverflowTooltip: true,
        formatter: (row: EnterpriseTable) => formatDateTime(row.created_time),
      },
      {
        prop: "operation",
        label: "操作",
        width: 230,
        fixed: "right",
        align: "center",
        formatter: (row: EnterpriseTable) => renderOperationCell(row),
      },
    ]),
  },
});

async function handleSearchBarSearch(params: EnterpriseSearchForm) {
  replaceSearchParams({
    name: params.name,
    enterprise_code: params.enterprise_code,
    status: params.status,
  });
  await getData();
}

async function onResetSearch() {
  searchForm.value = { name: undefined, enterprise_code: undefined, status: undefined };
  await resetSearchParams();
}

// ─── 一步开通 ───
type ProvisionFormState = {
  name: string;
  enterprise_code?: string;
  credit_code?: string;
  description?: string;
  admin_mode: "create" | "bind" | "none";
  admin_user_id?: number;
  admin_username?: string;
  admin_name?: string;
  admin_mobile?: string;
  admin_password?: string;
};

const initialProvisionForm: ProvisionFormState = {
  name: "",
  enterprise_code: undefined,
  credit_code: undefined,
  description: undefined,
  admin_mode: "create",
  admin_user_id: undefined,
  admin_username: undefined,
  admin_name: undefined,
  admin_mobile: undefined,
  admin_password: undefined,
};

const provisionVisible = ref(false);
const provisionSubmitLoading = ref(false);
const provisionFormRenderKey = ref(0);
const provisionForm = ref<ProvisionFormState>({ ...initialProvisionForm });
const provisionFormRef = ref<InstanceType<typeof FaForm> | null>(null);

const provisionFormItems = computed<FormItem[]>(() => {
  const mode = provisionForm.value.admin_mode;
  const items: FormItem[] = [
    {
      label: "企业名称",
      key: "name",
      type: "input",
      span: 24,
      props: { placeholder: "请输入企业名称", maxlength: 128 },
    },
    {
      label: "企业编码",
      key: "enterprise_code",
      type: "input",
      span: 24,
      props: { placeholder: "留空自动生成 ENT-xxx", maxlength: 32 },
    },
    {
      label: "信用代码",
      key: "credit_code",
      type: "input",
      span: 24,
      props: { placeholder: "统一社会信用代码（可空）", maxlength: 64 },
    },
    {
      label: "备注",
      key: "description",
      type: "input",
      span: 24,
      props: { type: "textarea", rows: 2, placeholder: "请输入备注（可空）" },
    },
    { label: "企业管理员", key: "admin_mode", type: "radiogroup", span: 24 },
  ];
  if (mode === "create") {
    items.push(
      {
        label: "管理员账号",
        key: "admin_username",
        type: "input",
        span: 24,
        props: { placeholder: "字母开头，3-32 位", maxlength: 32 },
      },
      {
        label: "管理员姓名",
        key: "admin_name",
        type: "input",
        span: 24,
        props: { placeholder: "请输入姓名", maxlength: 32 },
      },
      {
        label: "手机号",
        key: "admin_mobile",
        type: "input",
        span: 24,
        props: { placeholder: "请输入手机号（可空）", maxlength: 11 },
      },
      {
        label: "初始密码",
        key: "admin_password",
        type: "input",
        span: 24,
        props: { type: "password", showPassword: true, placeholder: "留空将自动生成，仅显示一次" },
      }
    );
  } else if (mode === "bind") {
    items.push({ label: "绑定账号", key: "admin_user_id", type: "input", span: 24 });
  }
  return items;
});

const provisionRules = computed(() => {
  const mode = provisionForm.value.admin_mode;
  return {
    name: [{ required: true, message: "请输入企业名称", trigger: "blur" }],
    admin_username:
      mode === "create"
        ? [
            { required: true, message: "请输入管理员账号", trigger: "blur" },
            {
              pattern: /^[A-Za-z][A-Za-z0-9_.-]{2,31}$/,
              message: "账号需以字母开头，3-32 位，仅允许字母、数字、_ . -",
              trigger: "blur",
            },
          ]
        : [],
    admin_name:
      mode === "create" ? [{ required: true, message: "请输入管理员姓名", trigger: "blur" }] : [],
    admin_mobile: [{ pattern: /^1\d{10}$/, message: "手机号格式不正确", trigger: "blur" }],
    admin_password: [{ min: 6, message: "初始密码至少 6 位", trigger: "blur" }],
  };
});

const passwordVisible = ref(false);
const passwordInfo = ref({ username: "", password: "" });

function openProvision() {
  provisionForm.value = { ...initialProvisionForm };
  provisionFormRenderKey.value += 1;
  provisionVisible.value = true;
}

async function submitProvision() {
  await provisionFormRef.value?.validate();
  const f = provisionForm.value;
  if (f.admin_mode === "bind" && !f.admin_user_id) {
    ElMessage.warning("请选择要绑定的账号");
    return;
  }
  const payload: EnterpriseCreateForm = {
    name: f.name,
    enterprise_code: f.enterprise_code || undefined,
    credit_code: f.credit_code || undefined,
    description: f.description || undefined,
  };
  if (f.admin_mode === "create") {
    payload.admin_account = {
      username: f.admin_username!,
      name: f.admin_name!,
      mobile: f.admin_mobile || undefined,
      password: f.admin_password || undefined,
    };
  } else if (f.admin_mode === "bind") {
    payload.admin_user_id = f.admin_user_id;
  }
  provisionSubmitLoading.value = true;
  try {
    const res = await EnterpriseAPI.createEnterprise(payload);
    provisionVisible.value = false;
    const result = res.data?.data;
    if (result?.admin_initial_password) {
      passwordInfo.value = {
        username: result.admin_username ?? "",
        password: result.admin_initial_password,
      };
      passwordVisible.value = true;
    } else {
      ElMessage.success("开通租户成功");
    }
    await refreshCreate();
  } finally {
    provisionSubmitLoading.value = false;
  }
}

async function copyText(text: string) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    ElMessage.success("已复制");
  } catch {
    ElMessage.warning("复制失败，请手动选择复制");
  }
}

// ─── 编辑 ───
const editVisible = ref(false);
const editSubmitLoading = ref(false);
const editForm = ref({
  id: undefined as number | undefined,
  name: "",
  credit_code: undefined as string | undefined,
  description: undefined as string | undefined,
});
const editFormRef = ref<InstanceType<typeof FaForm> | null>(null);
const editingRow = ref<EnterpriseTable | null>(null);
const editRules = { name: [{ required: true, message: "请输入企业名称", trigger: "blur" }] };
const editFormItems: FormItem[] = [
  { label: "企业名称", key: "name", type: "input", span: 24, props: { maxlength: 128 } },
  {
    label: "信用代码",
    key: "credit_code",
    type: "input",
    span: 24,
    props: { maxlength: 64, placeholder: "统一社会信用代码（可空）" },
  },
  {
    label: "备注",
    key: "description",
    type: "input",
    span: 24,
    props: { type: "textarea", rows: 2 },
  },
];

async function openEdit(row: EnterpriseTable) {
  if (row.id == null) return;
  editingRow.value = row;
  const res = await EnterpriseAPI.detailEnterprise(row.id);
  editForm.value = {
    id: row.id,
    name: res.data?.data?.name ?? "",
    credit_code: res.data?.data?.credit_code ?? undefined,
    description: res.data?.data?.description ?? undefined,
  };
  editVisible.value = true;
}

async function submitEdit() {
  await editFormRef.value?.validate();
  if (editForm.value.id == null) return;
  editSubmitLoading.value = true;
  try {
    const res = await EnterpriseAPI.updateEnterprise(editForm.value.id, {
      name: editForm.value.name,
      credit_code: editForm.value.credit_code || undefined,
      description: editForm.value.description || undefined,
    });
    // 响应即更新后实体，本地修补避免「响应后提交」的刷新竞态
    if (editingRow.value && res.data?.data) {
      editingRow.value.name = res.data.data.name;
      editingRow.value.credit_code = res.data.data.credit_code;
      editingRow.value.description = res.data.data.description;
    }
    ElMessage.success("更新企业成功");
    editVisible.value = false;
  } finally {
    editSubmitLoading.value = false;
  }
}

// ─── 详情 ───
const detailVisible = ref(false);
const detailData = ref<EnterpriseTable>({});
const detailItems: import("@/components/display/fa-descriptions/index.vue").DescriptionsItem[] = [
  { label: "企业编码", prop: "enterprise_code" },
  { label: "企业名称", prop: "name" },
  { label: "信用代码", prop: "credit_code" },
  {
    label: "状态",
    prop: "status",
    tag: { map: { 1: { type: "success", text: "正常" }, 0: { type: "danger", text: "冻结" } } },
  },
  { label: "备注", prop: "description", span: 2 },
  { label: "创建时间", prop: "created_time" },
  { label: "更新时间", prop: "updated_time" },
];

async function openDetail(row: EnterpriseTable) {
  if (row.id == null) return;
  const res = await EnterpriseAPI.detailEnterprise(row.id);
  detailData.value = res.data?.data ?? {};
  detailVisible.value = true;
}

// ─── 绑定管理 ───
const bindingsVisible = ref(false);
const bindingsLoading = ref(false);
const bindSubmitLoading = ref(false);
const bindings = ref<TenantUserBinding[]>([]);
const currentEnterprise = ref<EnterpriseTable | null>(null);
const bindForm = ref({
  user_id: undefined as number | undefined,
  is_enterprise_admin: false,
  emp_no: undefined as string | undefined,
});

async function loadBindings() {
  if (currentEnterprise.value?.id == null) return;
  bindingsLoading.value = true;
  try {
    const res = await EnterpriseAPI.listBindings(currentEnterprise.value.id);
    bindings.value = res.data?.data ?? [];
  } finally {
    bindingsLoading.value = false;
  }
}

async function openBindings(row: EnterpriseTable) {
  currentEnterprise.value = row;
  bindForm.value = { user_id: undefined, is_enterprise_admin: false, emp_no: undefined };
  bindingsVisible.value = true;
  await loadBindings();
}

async function submitBind() {
  if (currentEnterprise.value?.id == null) return;
  if (!bindForm.value.user_id) {
    ElMessage.warning("请选择要绑定的账号");
    return;
  }
  bindSubmitLoading.value = true;
  try {
    const res = await EnterpriseAPI.bindUser(currentEnterprise.value.id, {
      user_id: bindForm.value.user_id,
      is_enterprise_admin: bindForm.value.is_enterprise_admin,
      emp_no: bindForm.value.emp_no || undefined,
    });
    ElMessage.success("绑定用户成功");
    bindForm.value = { user_id: undefined, is_enterprise_admin: false, emp_no: undefined };
    // 响应即最新绑定（含 username/name），本地追加避免提交前刷新竞态
    if (res.data?.data) bindings.value = [...bindings.value, res.data.data];
  } finally {
    bindSubmitLoading.value = false;
  }
}

async function handleUnbind(row: TenantUserBinding) {
  if (row.id == null) return;
  try {
    await confirmAction(
      `确定解绑用户「${row.username ?? row.user_id}」吗？解绑后该账号不再归属本企业。`,
      "解绑确认"
    );
    await EnterpriseAPI.unbindUser(row.id);
    ElMessage.success("解绑用户成功");
    bindings.value = bindings.value.filter((item) => item.id !== row.id);
  } catch {
    // 用户取消
  }
}

// ─── 冻结 / 解冻 ───
async function handleFreeze(row: EnterpriseTable) {
  if (row.id == null) return;
  try {
    await confirmAction(
      `冻结后将立即清退「${row.name}」全部在线会话，并实时阻断该企业全部绑定用户。确定冻结吗？`,
      "冻结确认"
    );
    // db_getter 在响应后才提交事务：立即 refreshData 会读到提交前旧值。
    // 冻结只改 status，直接用响应值更新行（解冻同理），不做竞态刷新。
    const res = await EnterpriseAPI.freezeEnterprise(row.id);
    row.status = res.data?.data?.status ?? 0;
    ElMessage.success("冻结企业租户成功");
  } catch {
    // 用户取消
  }
}

async function handleUnfreeze(row: EnterpriseTable) {
  if (row.id == null) return;
  try {
    await confirmAction(`确定解冻「${row.name}」吗？解冻后绑定用户可重新登录。`, "解冻确认");
    const res = await EnterpriseAPI.unfreezeEnterprise(row.id);
    row.status = res.data?.data?.status ?? 1;
    ElMessage.success("解冻企业租户成功");
  } catch {
    // 用户取消
  }
}

// ─── 行操作 ───
function buildRowActions(row: EnterpriseTable): TableOperationAction[] {
  const actions: TableOperationAction[] = [
    {
      key: "detail",
      label: "详情",
      artType: "view",
      perm: "module_platform:enterprise:detail",
      run: () => void openDetail(row),
    },
    {
      key: "edit",
      label: "编辑",
      artType: "edit",
      perm: "module_platform:enterprise:update",
      run: () => void openEdit(row),
    },
    {
      key: "bindings",
      label: "绑定管理",
      artType: "more",
      icon: "ri:user-settings-line",
      perm: "module_platform:enterprise:bind",
      run: () => void openBindings(row),
    },
  ];
  if (row.status === 1) {
    actions.push({
      key: "freeze",
      label: "冻结",
      artType: "delete",
      icon: "ri:lock-line",
      perm: "module_platform:enterprise:freeze",
      run: () => void handleFreeze(row),
    });
  } else {
    actions.push({
      key: "unfreeze",
      label: "解冻",
      artType: "add",
      icon: "ri:lock-unlock-line",
      perm: "module_platform:enterprise:unfreeze",
      run: () => void handleUnfreeze(row),
    });
  }
  return actions;
}

function renderOperationCell(row: EnterpriseTable) {
  return renderTableOperationCell(buildRowActions(row), {
    wrapperClass: "inline-flex flex-wrap items-center justify-end gap-1",
  });
}
</script>
