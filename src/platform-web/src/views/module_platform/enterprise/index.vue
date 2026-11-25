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
      @cancel="closeEdit"
      @close="closeEdit"
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
      @close="closeDetail"
    >
      <FaDescriptions
        :column="2"
        :data="detailData"
        :items="detailItems"
        label-width="120px"
        max-height="70vh"
      />
    </FaDialog>

    <!-- 成员管理（ADR-001：Owner/Admin 标识＋停用＋移交记录） -->
    <FaDialog
      v-model="bindingsVisible"
      :title="`成员管理 · ${currentEnterprise?.name ?? ''}`"
      form-mode="detail"
      size="lg"
      @close="closeBindings"
    >
      <div class="mb-4 flex flex-wrap items-center gap-3">
        <template v-if="checkPerm('module_platform:enterprise:bind')">
          <FaUserTableSelect
            :model-value="bindForm.user_id"
            @update:model-value="(v: number | undefined) => (bindForm.user_id = v)"
          />
          <ElInput v-model="bindForm.emp_no" placeholder="工号（可空）" class="w-36" clearable />
          <ElButton type="primary" :loading="bindSubmitLoading" @click="submitBind"
            >添加成员</ElButton
          >
          <span class="text-xs text-g-500">无 Owner 租户的首名成员自动成为企业拥有者</span>
        </template>
        <ElButton v-if="checkPerm('module_platform:enterprise:audit')" @click="toggleAudit">
          {{ auditVisible ? "隐藏移交记录" : "移交记录" }}
        </ElButton>
      </div>
      <ElTable v-loading="bindingsLoading" :data="bindings" border>
        <ElTableColumn prop="username" label="登录账号" min-width="130" />
        <ElTableColumn prop="name" label="姓名" min-width="100" />
        <ElTableColumn label="角色" width="140" align="center">
          <template #default="{ row }">
            <FaStatusTag
              :type="row.is_owner ? 'warning' : row.is_admin ? 'primary' : 'info'"
              :label="row.is_owner ? '企业拥有者' : row.is_admin ? '企业管理员' : '普通成员'"
            />
          </template>
        </ElTableColumn>
        <ElTableColumn prop="emp_no" label="工号" min-width="80">
          <template #default="{ row }">{{ row.emp_no || "—" }}</template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="80" align="center">
          <template #default="{ row }">
            <FaStatusTag
              :type="row.status === 0 ? 'success' : 'danger'"
              :label="row.status === 0 ? '正常' : '停用'"
            />
          </template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="110" align="center">
          <template #default="{ row }">
            <ElButton
              v-if="checkPerm('module_platform:enterprise:unbind')"
              link
              type="danger"
              size="small"
              :disabled="row.is_owner"
              :title="row.is_owner ? '企业拥有者须先移交所有权' : ''"
              @click="handleDisable(row, currentEnterprise?.id)"
            >
              停用
            </ElButton>
          </template>
        </ElTableColumn>
      </ElTable>
      <template v-if="auditVisible">
        <ElDivider content-position="left">所有权移交记录</ElDivider>
        <ElTable :data="audits" border size="small">
          <ElTableColumn prop="source" label="来源" width="90" align="center">
            <template #default="{ row }">{{ row.source === "tenant" ? "租户" : "平台" }}</template>
          </ElTableColumn>
          <ElTableColumn prop="from_member_id" label="原Owner" width="90" align="center">
            <template #default="{ row }">{{ row.from_member_id ?? "—" }}</template>
          </ElTableColumn>
          <ElTableColumn prop="to_member_id" label="新Owner" width="90" align="center" />
          <ElTableColumn prop="result" label="结果" width="90" align="center">
            <template #default="{ row }">
              <FaStatusTag
                :type="row.result === 'success' ? 'success' : 'danger'"
                :label="row.result === 'success' ? '成功' : '失败'"
              />
            </template>
          </ElTableColumn>
          <ElTableColumn prop="reason" label="原因" min-width="180" show-overflow-tooltip />
          <ElTableColumn prop="created_time" label="时间" width="170" />
        </ElTable>
      </template>
    </FaDialog>

    <!-- 平台侧所有权移交 -->
    <FaDialog
      v-model="transferVisible"
      title="移交企业拥有者"
      form-mode="create"
      confirm-text="确认移交"
      :confirm-loading="transferSubmitLoading"
      @cancel="closeTransfer"
      @close="closeTransfer"
      @confirm="submitTransfer"
      size="md"
    >
      <ElAlert
        type="warning"
        :closable="false"
        title="移交只改变租户所有权：原 Owner 不自动保留企业管理员，双方旧会话立即失效需重新登录，项目任命与历史归属不变。"
      />
      <div class="mt-4 flex flex-col gap-4">
        <ElSelect
          v-model="transferForm.target_member_id"
          placeholder="选择新 Owner（本租户有效成员，不含当前 Owner）"
          class="w-full"
          filterable
        >
          <ElOption
            v-for="member in transferCandidates"
            :key="member.id"
            :value="member.id!"
            :label="`${member.username}（${member.name}）`"
          />
        </ElSelect>
        <ElInput
          v-model="transferForm.reason"
          type="textarea"
          :rows="3"
          maxlength="500"
          show-word-limit
          placeholder="移交原因（必填，如 Owner 离职、停用、失联等）"
        />
        <ElCheckbox v-model="transferForm.confirm">
          我已二次确认：移交后原 Owner 失去企业拥有者身份，双方需重新登录
        </ElCheckbox>
      </div>
    </FaDialog>
  </div>
</template>

<script setup lang="ts">
import EnterpriseAPI, {
  type EnterpriseCreateForm,
  type EnterpriseTable,
  type OwnerAuditItem,
  type TenantMember,
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
const editRequestToken = ref(0);
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

function isCurrentEditRequest(requestToken: number, enterpriseId: number) {
  return editRequestToken.value === requestToken && editingRow.value?.id === enterpriseId;
}

function closeEdit() {
  editVisible.value = false;
  editRequestToken.value += 1;
  editingRow.value = null;
  editSubmitLoading.value = false;
}

async function openEdit(row: EnterpriseTable) {
  if (row.id == null) return;
  const enterpriseId = row.id;
  const requestToken = ++editRequestToken.value;
  editingRow.value = row;
  editSubmitLoading.value = false;
  const res = await EnterpriseAPI.detailEnterprise(enterpriseId);
  if (!isCurrentEditRequest(requestToken, enterpriseId)) return;
  editForm.value = {
    id: enterpriseId,
    name: res.data?.data?.name ?? "",
    credit_code: res.data?.data?.credit_code ?? undefined,
    description: res.data?.data?.description ?? undefined,
  };
  editVisible.value = true;
}

async function submitEdit() {
  const row = editingRow.value;
  const enterpriseId = editForm.value.id;
  const requestToken = editRequestToken.value;
  if (!row || enterpriseId == null || row.id !== enterpriseId) return;
  await editFormRef.value?.validate();
  if (!isCurrentEditRequest(requestToken, enterpriseId) || editForm.value.id !== enterpriseId) {
    return;
  }
  const payload = {
    name: editForm.value.name,
    credit_code: editForm.value.credit_code || undefined,
    description: editForm.value.description || undefined,
  };
  editSubmitLoading.value = true;
  try {
    const res = await EnterpriseAPI.updateEnterprise(enterpriseId, payload);
    if (!isCurrentEditRequest(requestToken, enterpriseId)) return;
    // 响应即更新后实体，本地修补避免「响应后提交」的刷新竞态
    if (res.data?.data) {
      row.name = res.data.data.name;
      row.credit_code = res.data.data.credit_code;
      row.description = res.data.data.description;
    }
    ElMessage.success("更新企业成功");
    editVisible.value = false;
  } finally {
    if (editRequestToken.value === requestToken) editSubmitLoading.value = false;
  }
}

// ─── 详情 ───
const detailVisible = ref(false);
const detailRequestToken = ref(0);
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

function closeDetail() {
  detailVisible.value = false;
  detailRequestToken.value += 1;
}

async function openDetail(row: EnterpriseTable) {
  if (row.id == null) return;
  const enterpriseId = row.id;
  const requestToken = ++detailRequestToken.value;
  const res = await EnterpriseAPI.detailEnterprise(enterpriseId);
  if (detailRequestToken.value !== requestToken) return;
  detailData.value = res.data?.data ?? {};
  detailVisible.value = true;
}

// ─── 成员管理（ADR-001） ───
const bindingsVisible = ref(false);
const bindingsLoading = ref(false);
const bindSubmitLoading = ref(false);
const bindings = ref<TenantMember[]>([]);
const currentEnterprise = ref<EnterpriseTable | null>(null);
const bindingsRequestToken = ref(0);
const bindingsEnterpriseId = ref<number | undefined>(undefined);
const bindForm = ref({
  user_id: undefined as number | undefined,
  emp_no: undefined as string | undefined,
});

function isCurrentBindingsRequest(requestToken: number, enterpriseId: number) {
  return (
    bindingsRequestToken.value === requestToken && currentEnterprise.value?.id === enterpriseId
  );
}

function isCurrentBindingMember(row: TenantMember, enterpriseId: number, requestToken: number) {
  return (
    isCurrentBindingsRequest(requestToken, enterpriseId) &&
    bindingsEnterpriseId.value === enterpriseId &&
    bindings.value.includes(row) &&
    (row.tenant_id == null || row.tenant_id === enterpriseId)
  );
}

function closeBindings() {
  bindingsVisible.value = false;
  bindingsRequestToken.value += 1;
  bindingsLoading.value = false;
  bindSubmitLoading.value = false;
  bindings.value = [];
  bindingsEnterpriseId.value = undefined;
  auditVisible.value = false;
  audits.value = [];
}

async function loadBindings() {
  const enterpriseId = currentEnterprise.value?.id;
  if (enterpriseId == null) return;
  const requestToken = ++bindingsRequestToken.value;
  bindingsEnterpriseId.value = undefined;
  bindingsLoading.value = true;
  try {
    const res = await EnterpriseAPI.listMembers(enterpriseId);
    if (!isCurrentBindingsRequest(requestToken, enterpriseId)) return;
    bindings.value = res.data?.data ?? [];
    bindingsEnterpriseId.value = enterpriseId;
    return requestToken;
  } finally {
    if (isCurrentBindingsRequest(requestToken, enterpriseId)) bindingsLoading.value = false;
  }
}

async function openBindings(row: EnterpriseTable) {
  if (row.id == null) return;
  currentEnterprise.value = row;
  bindings.value = [];
  bindingsEnterpriseId.value = undefined;
  bindSubmitLoading.value = false;
  bindForm.value = { user_id: undefined, emp_no: undefined };
  bindingsVisible.value = true;
  auditVisible.value = false;
  audits.value = [];
  await loadBindings();
}

async function submitBind() {
  const enterpriseId = currentEnterprise.value?.id;
  if (enterpriseId == null) return;
  const userId = bindForm.value.user_id;
  if (!userId) {
    ElMessage.warning("请选择要绑定的账号");
    return;
  }
  // 写操作开启新代次：较早的 list 响应不得覆盖随后追加的新成员。
  const requestToken = ++bindingsRequestToken.value;
  bindingsLoading.value = false;
  const empNo = bindForm.value.emp_no;
  bindSubmitLoading.value = true;
  try {
    const res = await EnterpriseAPI.bindMember(enterpriseId, {
      user_id: userId,
      emp_no: empNo || undefined,
    });
    if (!isCurrentBindingsRequest(requestToken, enterpriseId)) return;
    ElMessage.success("添加成员成功");
    bindForm.value = { user_id: undefined, emp_no: undefined };
    // 响应即最新成员（含 username/name/is_owner），本地追加避免提交前刷新竞态
    if (res.data?.data) {
      bindings.value = [...bindings.value, res.data.data];
      bindingsEnterpriseId.value = enterpriseId;
    }
  } finally {
    if (isCurrentBindingsRequest(requestToken, enterpriseId)) bindSubmitLoading.value = false;
  }
}

async function handleDisable(row: TenantMember, enterpriseId: number | undefined) {
  const memberId = row.id;
  if (memberId == null || enterpriseId == null) return;
  const requestToken = bindingsRequestToken.value;
  if (!isCurrentBindingMember(row, enterpriseId, requestToken)) return;
  if (row.is_owner) {
    ElMessage.warning("企业拥有者须先移交所有权，禁止直接停用");
    return;
  }
  try {
    await confirmAction(
      `确定停用成员「${row.username ?? row.user_id}」吗？停用后其会话立即失效，历史记录保留。`,
      "停用确认"
    );
    if (!isCurrentBindingMember(row, enterpriseId, requestToken)) return;
    await EnterpriseAPI.disableMember(memberId);
    if (!isCurrentBindingMember(row, enterpriseId, requestToken)) return;
    ElMessage.success("停用成员成功");
    // 停用不物理删除：本地标记状态
    row.status = 1;
  } catch {
    // 用户取消
  }
}

// ─── 所有权移交与审计 ───
const transferVisible = ref(false);
const transferSubmitLoading = ref(false);
const transferForm = ref({
  target_member_id: undefined as number | undefined,
  reason: "",
  confirm: false,
});
const transferCandidates = computed(() =>
  bindings.value.filter((m) => !m.is_owner && m.status === 0)
);

function closeTransfer() {
  transferVisible.value = false;
  bindingsRequestToken.value += 1;
  bindingsLoading.value = false;
  transferSubmitLoading.value = false;
}

async function openTransfer(row: EnterpriseTable) {
  if (row.id == null) return;
  const enterpriseId = row.id;
  currentEnterprise.value = row;
  transferSubmitLoading.value = false;
  transferForm.value = { target_member_id: undefined, reason: "", confirm: false };
  const requestToken = await loadBindings();
  if (requestToken == null || !isCurrentBindingsRequest(requestToken, enterpriseId)) return;
  transferVisible.value = true;
}

async function submitTransfer() {
  const enterpriseId = currentEnterprise.value?.id;
  const targetMemberId = transferForm.value.target_member_id;
  if (enterpriseId == null) return;
  if (!targetMemberId) {
    ElMessage.warning("请选择新 Owner 成员");
    return;
  }
  const reason = transferForm.value.reason.trim();
  if (!reason) {
    ElMessage.warning("请填写移交原因");
    return;
  }
  if (!transferForm.value.confirm) {
    ElMessage.warning("请勾选二次确认");
    return;
  }
  const requestToken = bindingsRequestToken.value;
  transferSubmitLoading.value = true;
  try {
    await EnterpriseAPI.transferOwner(enterpriseId, {
      target_member_id: targetMemberId,
      reason,
      confirm: true,
    });
    if (!isCurrentBindingsRequest(requestToken, enterpriseId)) return;
    ElMessage.success("所有权移交成功，双方需重新登录");
    // 本地更新 Owner 标识（双方会话已清退，无需立即刷新列表）；
    // B-01：移交同事务清除双方 Admin 记录，原 Owner 不自动保留企业管理员
    const oldOwner = bindings.value.find((m) => m.is_owner);
    if (oldOwner) {
      oldOwner.is_owner = false;
      oldOwner.is_admin = false;
    }
    const newOwner = bindings.value.find((m) => m.id === targetMemberId);
    if (newOwner) {
      newOwner.is_owner = true;
      newOwner.is_admin = false;
    }
    transferVisible.value = false;
  } finally {
    if (isCurrentBindingsRequest(requestToken, enterpriseId)) transferSubmitLoading.value = false;
  }
}

const auditVisible = ref(false);
const audits = ref<OwnerAuditItem[]>([]);

async function toggleAudit() {
  auditVisible.value = !auditVisible.value;
  const enterpriseId = currentEnterprise.value?.id;
  if (auditVisible.value && enterpriseId != null) {
    const requestToken = bindingsRequestToken.value;
    const res = await EnterpriseAPI.listOwnerAudit(enterpriseId);
    if (!auditVisible.value || !isCurrentBindingsRequest(requestToken, enterpriseId)) return;
    audits.value = res.data?.data ?? [];
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
      label: "成员管理",
      artType: "more",
      icon: "ri:user-settings-line",
      perm: "module_platform:enterprise:bind",
      run: () => void openBindings(row),
    },
    {
      key: "transfer",
      label: "移交所有权",
      artType: "more",
      icon: "ri:exchange-line",
      perm: "module_platform:enterprise:transfer",
      run: () => void openTransfer(row),
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
