"""让控制台输出永不因编码而崩。

Windows 默认控制台是 GBK(cp936)。模型输出里只要出现 GBK 表示不了的字符
（实测 `↔` U+2194），`print(content)` 就会抛 UnicodeEncodeError。
发生在诊断分支里时，异常会顶掉原有的错误处理，把一次普通的
「JSON 解析失败」伪装成「API 调用失败」，并丢掉真正的原始输出。

这里把标准流改成 `errors="replace"`：常见字符正常显示，生僻字符降级成 `?`，
但绝不抛异常。保留原编码，避免整屏变成乱码。
"""

from __future__ import annotations

import sys


def harden_console() -> None:
    """幂等；标准流不支持 reconfigure 时静默跳过。"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except Exception:  # noqa: BLE001 - 尽力而为，不因加固失败而影响启动
            pass


harden_console()
