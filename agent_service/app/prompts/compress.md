<!--
用途: 压缩对话中间段时的 system 指示
调用方: app/workflow/chat.py → compress_context
占位符: 无（正文即整段 prompt）
-->

把以下 CAD 建模对话中间段压缩成一段中文摘要，保留：已确定的坐标系约定、关键尺寸、已创建的主要对象名、未完成事项、用户明确要求。不要编造。输出纯文本，不要 JSON。
