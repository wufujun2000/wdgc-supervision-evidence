import { computed, defineComponent, h, ref } from "vue";
import { flushPromises, shallowMount, type Stubs, type VueWrapper } from "@vue/test-utils";
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

type ApiResponse<T> = { data: { data: T } };
const response = <T>(data: T): ApiResponse<T> => ({ data: { data } });

let wrapper: VueWrapper | undefined;

// 审计结果列测试专用 stub：ElTable 渲染列插槽；result 列以成功/失败两行驱动作用域插槽
const tableStub = { name: "ElTable", template: "<div><slot /></div>" };
const columnStub = defineComponent({
  name: "ElTableColumn",
  props: { prop: { type: String, default: "" }, label: { type: String, default: "" } },
  setup(props, { slots }) {
    return () =>
      props.prop === "result"
        ? h("div", { class: "result-column" }, [
            ...(slots.default?.({ row: { result: "success" } }) ?? []),
            ...(slots.default?.({ row: { result: "failed" } }) ?? []),
          ])
        : h("div");
  },
});

async function mountPage(stubs: Stubs = { ElTable: true, ElTableColumn: true }) {
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
  wrapper = shallowMount(EnterprisePage, { global: { stubs } });
  return wrapper.vm as unknown as {
    bindings: Array<Record<string, unknown>>;
    transferForm: { target_member_id?: number; reason: string; confirm: boolean };
    openBindings(row: { id: number }): Promise<void>;
    openTransfer(row: { id: number }): Promise<void>;
    submitTransfer(): Promise<void>;
    auditVisible: boolean;
    audits: Array<Record<string, unknown>>;
    toggleAudit(): Promise<void>;
  };
}

describe("enterprise transfer & audit sync (F-04)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
  });

  it("移交成功后同步 Owner 标识并清除双方 is_admin", async () => {
    api.listMembers.mockResolvedValue(
      response([
        { id: 1, tenant_id: 7, user_id: 10, username: "old-owner", status: 0, is_owner: true, is_admin: true },
        { id: 2, tenant_id: 7, user_id: 20, username: "new-owner", status: 0, is_owner: false, is_admin: true },
      ])
    );
    api.transferOwner.mockResolvedValue(response({ tenant_id: 7, from_member_id: 1, to_member_id: 2, version: 2 }));
    const vm = await mountPage();
    await vm.openTransfer({ id: 7 });
    vm.transferForm.target_member_id = 2;
    vm.transferForm.reason = "移交测试";
    vm.transferForm.confirm = true;
    await vm.submitTransfer();
    expect(api.transferOwner).toHaveBeenCalledWith(7, { target_member_id: 2, reason: "移交测试", confirm: true });
    const oldOwner = vm.bindings.find((m) => m.id === 1)!;
    const newOwner = vm.bindings.find((m) => m.id === 2)!;
    expect(oldOwner.is_owner).toBe(false);
    expect(oldOwner.is_admin).toBe(false);
    expect(newOwner.is_owner).toBe(true);
    expect(newOwner.is_admin).toBe(false);
  }, 15000);

  it("审计表含 result 成功/失败列并加载结果数据", async () => {
    api.listMembers.mockResolvedValue(response([]));
    api.listOwnerAudit.mockResolvedValue(
      response([
        { id: 1, source: "platform", from_member_id: null, to_member_id: 2, reason: "开通初始化", result: "success" },
        { id: 2, source: "tenant", from_member_id: 2, to_member_id: 3, reason: "冲突移交", result: "failed" },
      ])
    );
    const vm = await mountPage({ ElTable: tableStub, ElTableColumn: columnStub });
    await vm.openBindings({ id: 7 });
    await vm.toggleAudit();
    await flushPromises();
    expect(vm.audits.map((a) => a.result)).toEqual(["success", "failed"]);
    const success = wrapper!.find('[label="成功"]');
    expect(success.exists()).toBe(true);
    expect(success.attributes("type")).toBe("success");
    const failed = wrapper!.find('[label="失败"]');
    expect(failed.exists()).toBe(true);
    expect(failed.attributes("type")).toBe("danger");
  }, 15000);
});
