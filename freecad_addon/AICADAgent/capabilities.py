# capabilities.py — CAD 程序契约握手策略（不依赖 FreeCAD / Qt）
#
# Agent 与插件是两份独立安装，插件执行程序前会比较两端 cad_api_version。
# 原则：**没有明确证据就不阻断**。探测失败、服务端尚未启动、字段缺失都不是漂移证据，
# 只有「拿到了明确且不同的版本号」才算不兼容。

_MISMATCH_TEMPLATE = "CAD 程序契约不兼容：插件={local} 服务端={remote}"


def evaluate_cad_api_compatibility(remote_version, local_version) -> tuple[bool, str]:
    """Return (blocked, reason) for a capability handshake result.

    blocked=True only when both sides reported a version and they differ.
    """
    remote = str(remote_version or "").strip()
    local = str(local_version or "").strip()
    if not remote or not local or remote == local:
        return False, ""
    return True, _MISMATCH_TEMPLATE.format(local=local, remote=remote)
