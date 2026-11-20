"""监理企业租户主表（plat_enterprise）。"""

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin


class EnterpriseModel(ModelMixin):
    """监理企业租户主表（平台域 plat_* 表空间，无 tenant_id）。

    状态语义与 sys_user 相反：**1=正常 / 0=冻结**。
    冻结后该租户全部绑定用户会话立即清退（H-02），请求实时阻断。
    """

    __tablename__: str = "plat_enterprise"
    __table_args__: dict[str, str] = {"comment": "监理企业租户表"}

    enterprise_code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False, comment="企业编码(ENT-xxx)")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="企业名称")
    credit_code: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True, comment="统一社会信用代码")
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="状态(1:正常 0:冻结)")
    description: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="备注")
