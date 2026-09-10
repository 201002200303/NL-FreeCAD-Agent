# Agent Service Application
#
# 导入 app 下任何子模块都会先执行这里，因此控制台加固对所有服务端代码生效：
# 避免模型输出里的生僻字符（如 `↔`）在 GBK 控制台上 print 崩溃。
from app.console import harden_console  # noqa: E402,F401  (import 即生效)
