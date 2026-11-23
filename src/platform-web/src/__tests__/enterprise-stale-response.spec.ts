import { computed, ref } from "vue";
import { flushPromises, shallowMount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  listMembers: vi.fn(),
  bindMember: vi.fn(),
  disableMember: vi.fn(),
  detailEnterprise: vi.fn(),
  updateEnterprise: vi.fn(),
  listOwnerAudit: vi.fn(),
  transferOwner: vi.fn(),
}));
const confirm = vi.hoisted(() => ({ action: vi.fn() }));

vi.mock("@/api/module_platform/enterprise", () => ({ default: api }));
vi.mock("@/config", () => ({ default: {} }));
vi.mock("@/config/setting", () => ({ SETTING_DEFAULT_CONFIG: {}, defaultSettings: {} }));
vi.mock("@/hooks/core/useConfirm", () => ({ confirmAction: confirm.action }));
vi.mock("@/utils/checkPerm", () => ({ checkPerm: () => true }));
vi.mock("@/hooks/core/useTable", () => ({
  useTable: () => ({
    columns: ref([]),
    columnChecks: ref([]),
    data: ref([]),
    loading: ref(false),
    pagination: ref({}),
    getData: vi.fn(),
    replaceSearchParams: vi.fn(),
    resetSearchParams: vi.fn(),
    handleSizeChange: vi.fn(),
    handleCurrentChange: vi.fn(),
    refreshData: vi.fn(),
    refreshCreate: vi.fn(),
  }),
}));

function deferred<T>() {
  return Promise.withResolvers<T>();
}

type ApiResponse<T> = { data: { data: T } };
const response = <T>(data: T): ApiResponse<T> => ({ data: { data } });
const member = (id: number, tenantId: number) => ({
  id,
  tenant_id: tenantId,
  user_id: id * 10,
  username: `member-${id}`,
  status: 0,
  is_owner: false,
});

let wrapper: VueWrapper | undefined;

async function mountPage() {
  // SFC 生产构建由 unplugin-auto-import 注入；单测显式提供同样的 Vue API 全局。
  Object.assign(globalThis, { ref, computed });
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (media: string) => ({
      matches: false,
      media,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      onchange: null,
      dispatchEvent: vi.fn(),
    }),
  });
  // Test-only loading boundary：静态 import 会在全局注入前执行 SFC，故此处必须延迟加载。
  const { default: EnterprisePage } = await import("@views/module_platform/enterprise/index.vue");
  wrapper = shallowMount(EnterprisePage, {
    global: { stubs: { ElTable: true, ElTableColumn: true } },
  });
  return wrapper.vm as unknown as {
    bindings: Array<Record<string, unknown>>;
    bindForm: { user_id?: number; emp_no?: string };
    editForm: { id?: number; name: string };
    openBindings(row: { id: number }): Promise<void>;
    closeBindings(): void;
    submitBind(): Promise<void>;
    handleDisable(row: Record<string, unknown>, enterpriseId: number): Promise<void>;
    openEdit(row: { id: number }): Promise<void>;
  };
}

describe("enterprise stale async responses", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
  });

  it("A 慢成员列表响应不得覆盖当前 B 企业", async () => {
    const a = deferred<ApiResponse<unknown>>();
    const b = deferred<ApiResponse<unknown>>();
    api.listMembers.mockImplementation((id: number) => (id === 1 ? a.promise : b.promise));
    const vm = await mountPage();
    const openA = vm.openBindings({ id: 1 });
    const openB = vm.openBindings({ id: 2 });
    b.resolve(response([member(2, 2)]));
    await flushPromises();
    a.resolve(response([member(1, 1)]));
    await Promise.all([openA, openB]);
    expect(vm.bindings.map((row) => row.id)).toEqual([2]);
  }, 15000);

  it("切换企业后 A 的绑定响应不得追加到 B", async () => {
    api.listMembers.mockResolvedValue(response([]));
    const bindA = deferred<ApiResponse<unknown>>();
    api.bindMember.mockReturnValue(bindA.promise);
    const vm = await mountPage();
    await vm.openBindings({ id: 1 });
    vm.bindForm.user_id = 101;
    const pending = vm.submitBind();
    await vm.openBindings({ id: 2 });
    bindA.resolve(response(member(1, 1)));
    await pending;
    expect(vm.bindings).toEqual([]);
  }, 15000);

  it("同企业 list 较慢时不得覆盖先返回的新绑定成员", async () => {
    const listA = deferred<ApiResponse<unknown>>();
    api.listMembers.mockReturnValue(listA.promise);
    api.bindMember.mockResolvedValue(response(member(1, 1)));
    const vm = await mountPage();
    const opening = vm.openBindings({ id: 1 });
    vm.bindForm.user_id = 101;
    await vm.submitBind();
    expect(vm.bindings.map((row) => row.id)).toEqual([1]);
    listA.resolve(response([]));
    await opening;
    expect(vm.bindings.map((row) => row.id)).toEqual([1]);
  }, 15000);

  it("确认停用前切换企业后不得再发送旧成员停用", async () => {
    const aRow = member(1, 1);
    api.listMembers.mockImplementation((id: number) => Promise.resolve(response([member(id, id)])));
    const confirmation = deferred<void>();
    confirm.action.mockReturnValue(confirmation.promise);
    const vm = await mountPage();
    await vm.openBindings({ id: 1 });
    const pending = vm.handleDisable(aRow, 1);
    await vm.openBindings({ id: 2 });
    confirmation.resolve();
    await pending;
    expect(api.disableMember).not.toHaveBeenCalled();
  }, 15000);

  it("连续编辑两行时 A 的详情响应不得写入 B 表单", async () => {
    const a = deferred<ApiResponse<unknown>>();
    const b = deferred<ApiResponse<unknown>>();
    api.detailEnterprise.mockImplementation((id: number) => (id === 1 ? a.promise : b.promise));
    const vm = await mountPage();
    const openA = vm.openEdit({ id: 1 });
    const openB = vm.openEdit({ id: 2 });
    b.resolve(response({ id: 2, name: "B" }));
    await flushPromises();
    a.resolve(response({ id: 1, name: "A" }));
    await Promise.all([openA, openB]);
    expect(vm.editForm.id).toBe(2);
    expect(vm.editForm.name).toBe("B");
  }, 15000);
});
