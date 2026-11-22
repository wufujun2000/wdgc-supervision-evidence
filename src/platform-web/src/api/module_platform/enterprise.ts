import { request } from "@utils";

const API_PATH = "/platform/enterprise";

/** 平台域「开通租户」API（仅超管）。全链路 snake_case。 */
export const EnterpriseAPI = {
  listEnterprise(query: EnterprisePageQuery) {
    return request<ApiResponse<PageResult<EnterpriseTable>>>({
      url: `${API_PATH}/list`,
      method: "get",
      params: query,
    });
  },

  detailEnterprise(id: number) {
    return request<ApiResponse<EnterpriseTable>>({
      url: `${API_PATH}/detail/${id}`,
      method: "get",
    });
  },

  createEnterprise(body: EnterpriseCreateForm) {
    return request<ApiResponse<EnterpriseProvisionResult>>({
      url: `${API_PATH}/create`,
      method: "post",
      data: body,
    });
  },

  updateEnterprise(id: number, body: EnterpriseUpdateForm) {
    return request<ApiResponse<EnterpriseTable>>({
      url: `${API_PATH}/update/${id}`,
      method: "put",
      data: body,
    });
  },

  freezeEnterprise(id: number) {
    return request<ApiResponse<EnterpriseTable>>({
      url: `${API_PATH}/freeze/${id}`,
      method: "post",
    });
  },

  unfreezeEnterprise(id: number) {
    return request<ApiResponse<EnterpriseTable>>({
      url: `${API_PATH}/unfreeze/${id}`,
      method: "post",
    });
  },

  listBindings(id: number) {
    return request<ApiResponse<TenantUserBinding[]>>({
      url: `${API_PATH}/${id}/bindings`,
      method: "get",
    });
  },

  bindUser(id: number, body: TenantUserBindForm) {
    return request<ApiResponse<TenantUserBinding>>({
      url: `${API_PATH}/${id}/bindings`,
      method: "post",
      data: body,
    });
  },

  unbindUser(bindingId: number) {
    return request<ApiResponse>({
      url: `${API_PATH}/bindings/${bindingId}`,
      method: "delete",
    });
  },
};

export default EnterpriseAPI;

export interface EnterpriseTable extends BaseType {
  enterprise_code?: string;
  name?: string;
  credit_code?: string;
  /** 1 正常 / 0 冻结（与 sys_user 0启用 相反，勿混用） */
  status?: number;
  description?: string;
}

export interface EnterpriseProvisionResult extends EnterpriseTable {
  admin_user_id?: number;
  admin_username?: string;
  /** 自动生成的初始密码，仅开通响应返回一次，线下告知企业 */
  admin_initial_password?: string;
}

export interface AdminAccountForm {
  username: string;
  name: string;
  mobile?: string;
  password?: string;
}

export interface EnterpriseCreateForm {
  name: string;
  enterprise_code?: string;
  credit_code?: string;
  description?: string;
  /** 绑定已有账号（与 admin_account 互斥） */
  admin_user_id?: number;
  /** 一步新建管理员账号（与 admin_user_id 互斥） */
  admin_account?: AdminAccountForm;
}

export interface EnterpriseUpdateForm {
  name?: string;
  credit_code?: string;
  description?: string;
}

export interface EnterprisePageQuery extends PageQuery {
  name?: string;
  enterprise_code?: string;
  status?: number;
}

export interface TenantUserBinding extends BaseType {
  tenant_id?: number;
  user_id?: number;
  is_enterprise_admin?: boolean;
  emp_no?: string;
  username?: string;
  name?: string;
}

export interface TenantUserBindForm {
  user_id: number;
  is_enterprise_admin?: boolean;
  emp_no?: string;
}
