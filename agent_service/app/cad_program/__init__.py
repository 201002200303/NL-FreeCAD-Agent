"""受限 CAD 程序（execute_cad_program）服务端校验与共享规则。

客户端执行前会用同一套校验，避免「服务端过、客户端绕过」。
"""

from app.cad_program.validate import validate_cad_source

__all__ = ["validate_cad_source"]
