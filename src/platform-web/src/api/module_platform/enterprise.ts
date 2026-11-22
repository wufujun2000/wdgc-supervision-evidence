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

  listMembers(id: number) {
    return request<ApiResponse<TenantMember[]>>({
      url: `${API_PATH}/${id}/members`,
      method: "get",
    });
  },

  bindMember(id: number, body: TenantMemberBindForm) {
    return request<ApiResponse<TenantMember>>({
      url: `${API_PATH}/${id}/members`,
      method: "post",
      data: body,
    });
  },

  disableMember(memberId: number) {
    return request<ApiResponse>({
      url: `${API_PATH}/members/${memberId}/disable`,
      method: "post",
    });
  },

  transferOwner(id: number, body: OwnerTransferForm) {
    return request<ApiResponse<OwnerTransferResult>>({
      url: `${API_PATH}/${id}/owner/transfer`,
      method: "post",
      data: body,
    });
  },

  listOwnerAudit(id: number) {
    return request<ApiResponse<OwnerAuditItem[]>>({
      url: `${API_PATH}/${id}/owner-audit`,
      method: "get",
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

export interface TenantMember extends BaseType {
  tenant_id?: number;
  user_id?: number;
  emp_no?: string;
  /** 0 正常 / 1 停用 */
  status?: number;
  username?: string;
  name?: string;
  is_owner?: boolean;
  is_admin?: boolean;
}

export interface TenantMemberBindForm {
  user_id: number;
  emp_no?: string;
}

export interface OwnerTransferForm {
  target_member_id: number;
  reason: string;
  confirm: true;
}

export interface OwnerTransferResult {
  tenant_id: number;
  from_member_id?: number;
  to_member_id: number;
  version: number;
}

export interface OwnerAuditItem extends BaseType {
  source?: string;
  operator_user_id?: number;
  tenant_id?: number;
  from_member_id?: number;
  to_member_id?: number;
  reason?: string;
  result?: string;
}
