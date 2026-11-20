"""平台管理域（platform-web）：租户开通（enterprise）与租户用户绑定（tenant_user）。

表空间纪律：sys_* 无 tenant_id；plat_* 平台表无 tenant_id；biz_* 强制 TenantModelMixin。
本域服务超管「开通租户」；租户域业务模块等 PRD 修正后另行落地（B0 不做）。
"""
