"""
=============================================================================
FastAPI 教学示例 — 主应用入口 (main.py)
=============================================================================
这个文件是从零搭建的 FastAPI 应用，模拟你们项目 agent_service/app/main.py
的真实结构，但代码量更小、注释更详细，专门用于学习。

你要掌握的四个核心要素，在这个文件中全部体现：

  要素 1: @app.get / @app.post → 声明 URL 路径和 HTTP 方法
  要素 2: response_model=      → 告诉 FastAPI 返回数据长什么样
  要素 3: 函数参数              → FastAPI 自动从请求体解析 JSON → Pydantic 对象
  要素 4: return                → FastAPI 自动把 Pydantic 对象序列化为 JSON

启动方式:
  cd agent_service/tutorial
  pip install -r requirements.txt
  uvicorn main:app --host 127.0.0.1 --port 8765 --reload

启动后访问:
  - Swagger UI 交互文档:  http://127.0.0.1:8765/docs
  - ReDoc 文档:           http://127.0.0.1:8765/redoc
  - 健康检查:             http://127.0.0.1:8765/health

测试命令（另一个终端执行）:
  # 测试 1: 健康检查
  curl http://127.0.0.1:8765/health

  # 测试 2: 生成建模计划（长方体）
  curl -X POST http://127.0.0.1:8765/agent/plan \
    -H "Content-Type: application/json" \
    -d '{"user_input": "画一个 100x60x20mm 的底座"}'

  # 测试 3: 生成建模计划（无法识别）
  curl -X POST http://127.0.0.1:8765/agent/plan \
    -H "Content-Type: application/json" \
    -d '{"user_input": "帮我设计一个复杂的火箭发动机"}'

  # 测试 4: 执行建模计划（嵌套数据）
  curl -X POST http://127.0.0.1:8765/agent/execute \
    -H "Content-Type: application/json" \
    -d '{"conversation_id":"conv_001","plan":[{"step_id":"S1","description":"创建长方体","tool":"create_box","args":{"length":100,"width":60,"height":20},"depends_on":[]},{"step_id":"S2","description":"创建圆柱体","tool":"create_cylinder","args":{"radius":10,"height":30},"depends_on":["S1"]}]}'

  # 测试 5: 故意发送错误数据（缺少必填字段 user_input）
  curl -X POST http://127.0.0.1:8765/agent/plan \
    -H "Content-Type: application/json" \
    -d '{"conversation_id": "test"}'
=============================================================================
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 导入我们自己的模块
from schemas import (
    PlanRequest,
    PlanResponse,
    ExecuteRequest,
    ExecuteResponse,
    HealthResponse,
    ErrorResponse,
    StepResult,
)
from planner import generate_plan, simulate_execution


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Step 1: 创建 FastAPI 应用实例                                         ║
# ╚══════════════════════════════════════════════════════════════════════════╝
# FastAPI() 是整个应用程序的"根对象"。
# 所有路由、中间件、事件处理器都挂在这个对象上。
# title/version/description 会出现在自动生成的 Swagger UI 文档顶部（访问 /docs 可看）。
#
# 类比理解：app = Flask(__name__) 在 Flask 中的作用完全一样。

app = FastAPI(
    title="NL-FreeCAD-Agent 教学版",
    version="0.1.0",
    description="从零学习 FastAPI：自然语言驱动的 CAD 建模 Agent 教学示例",
)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Step 2: 注册中间件（拦截器）                                           ║
# ╚══════════════════════════════════════════════════════════════════════════╝
# 中间件 = 请求流水线上的"检查站"。
# 每个 HTTP 请求在到达你的路由函数之前，都会先经过中间件处理。
#
# CORS（跨域资源共享）中间件的作用：
#   当你的 FreeCAD 插件（运行在另一个端口/进程）向这个服务发请求时，
#   浏览器会先发一个 OPTIONS "预检"请求，问服务端"我能访问你吗？"
#   这个中间件就是回答"可以"的那道门。
#
# 参数说明:
#   allow_origins=["*"]   — 允许任何来源访问（开发环境用，生产环境要限制）
#   allow_methods=["*"]   — 允许所有 HTTP 方法（GET, POST, PUT, DELETE...）
#   allow_headers=["*"]   — 允许所有请求头

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Step 3: 定义路由端点（API 接口）                                       ║
# ║                                                                         ║
# ║  每个 @app.get 或 @app.post 装饰器做了三件事:                            ║
# ║    ① 绑定 URL 路径（如 /health）和 HTTP 方法（GET/POST）                ║
# ║    ② 声明 response_model，让 FastAPI 校验和文档化返回数据              ║
# ║    ③ 让被装饰的函数成为"请求处理器"                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝


# ──────────────────────────────────────────────────────────────────────────
# 端点 1: GET /health — 健康检查
# ──────────────────────────────────────────────────────────────────────────
# 这是最简单的端点，用于验证服务是否正常运行。
# 不需要请求体，不接收参数，只返回一个固定格式的 JSON。
#
# 【要素 2】response_model=HealthResponse 的作用:
#   如果函数不小心返回了错的数据（比如多了字段或字段类型不对），
#   FastAPI 会在返回给客户端之前拦截并报错，避免前端收到格式不正确的数据。
#
# 【要素 4】return HealthResponse(status="ok", version="0.1.0"):
#   FastAPI 自动调用 HealthResponse.model_dump() 转为 dict，
#   然后 json.dumps() 序列化为 JSON 字符串，
#   设置 Content-Type: application/json 头，
#   返回给客户端。

@app.get("/health", response_model=HealthResponse)
async def health():
    """
    健康检查端点。

    测试命令:
      curl http://127.0.0.1:8765/health

    预期响应 (HTTP 200):
      {"status": "ok", "version": "0.1.0"}
    """
    return HealthResponse(status="ok", version="0.1.0")


# ──────────────────────────────────────────────────────────────────────────
# 端点 2: POST /agent/plan — 生成建模计划（你们项目的核心接口）
# ──────────────────────────────────────────────────────────────────────────
# 这个端点完整演示了四个核心要素。
#
# 【要素 1】@app.post("/agent/plan"):
#   - "POST" 表示这是 POST 请求（数据在请求体中）
#   - "/agent/plan" 是 URL 路径
#   - 完整 URL: http://127.0.0.1:8765/agent/plan
#
# 【要素 2】response_model=PlanResponse:
#   - FastAPI 知道这个端点返回的数据必须匹配 PlanResponse 的结构
#   - 返回前自动校验，格式不对就报错
#   - Swagger UI 里会显示 PlanResponse 的所有字段和描述
#
# 【要素 3】request: PlanRequest:
#   - 这是关键！参数类型是 PlanRequest（Pydantic 模型）
#   - FastAPI 看到这个类型声明后，自动做了以下事情：
#
#       客户端发送:
#         POST /agent/plan
#         Content-Type: application/json
#         Body: {"user_input": "画一个底座", "conversation_id": null}
#                          │
#                          ▼
#       FastAPI 内部处理:
#         1. 读取 Body 原始字节: b'{"user_input": "画一个底座", ...}'
#         2. 检测 Content-Type = application/json → 用 JSON 解码器
#         3. json.loads() → {"user_input": "画一个底座", "conversation_id": null}
#         4. PlanRequest(user_input="画一个底座", conversation_id=None)
#         5. 校验: user_input 是 str ✓，conversation_id 是 None ✓
#         6. 传入函数: plan(request) 中 request = PlanRequest 对象
#                          │
#                          ▼
#       你的代码中可以直接使用:
#         request.user_input       → "画一个底座"
#         request.conversation_id  → None
#
#   - 如果客户端没传 user_input，FastAPI 在第 5 步就返回 422，
#     你的函数根本不会被调用！
#
# 【要素 4】return PlanResponse(**result):
#   - **result 是 Python 的字典解包语法：
#       result = {"status": "ok", "goal": "...", "plan": [...]}
#       PlanResponse(**result) 等价于
#       PlanResponse(status="ok", goal="...", plan=[...])
#
#   - FastAPI 拿到 PlanResponse 对象后:
#         1. 用 response_model=PlanResponse 再次校验
#         2. PlanResponse.model_dump() → dict
#         3. json.dumps() → JSON 字符串
#         4. 设置 Content-Type: application/json
#         5. 返回 HTTP 200

@app.post("/agent/plan", response_model=PlanResponse)
async def plan(request: PlanRequest):
    """
    接收用户自然语言输入，返回结构化的建模计划。

    测试命令 (长方体):
      curl -X POST http://127.0.0.1:8765/agent/plan \
        -H "Content-Type: application/json" \
        -d '{"user_input": "画一个 100x60x20mm 的底座"}'

    预期响应 (HTTP 200):
      {
        "status": "ok",
        "goal": "创建一个 100.0×60.0×20.0mm 的长方体",
        "assumptions": ["单位默认为 mm"],
        "missing_params": [],
        "question": null,
        "plan": [
          {
            "step_id": "S1",
            "description": "创建 100.0×60.0×20.0mm 长方体",
            "tool": "create_box",
            "args": {"name": "BaseBlock", "length": 100.0, "width": 60.0, "height": 20.0, "unit": "mm"},
            "depends_on": []
          }
        ]
      }

    测试命令 (无法识别):
      curl -X POST http://127.0.0.1:8765/agent/plan \
        -H "Content-Type: application/json" \
        -d '{"user_input": "帮我设计核反应堆"}'

    预期响应 (HTTP 200):
      {
        "status": "need_more_info",
        "goal": "无法确定建模目标",
        "assumptions": [],
        "missing_params": [],
        "question": "请描述您想创建的模型。当前支持：长方体（底座）、圆柱体、草图。...",
        "plan": []
      }
    """
    # ── 这是真正执行业务逻辑的一行 ──
    # generate_plan 是纯 Python 函数，不依赖 FastAPI
    # 返回值是 dict，结构匹配 PlanResponse
    result = generate_plan(request.user_input)

    # ── 组装响应 ──
    # **result 把 dict 的所有键值对作为关键字参数传给 PlanResponse
    # FastAPI 拿到 PlanResponse 后自动序列化为 JSON
    return PlanResponse(**result)


# ──────────────────────────────────────────────────────────────────────────
# 端点 3: POST /agent/execute — 执行建模计划（演示嵌套数据解析）
# ──────────────────────────────────────────────────────────────────────────
# 这个端点比 plan 更复杂，用来演示 FastAPI 如何解析嵌套的 JSON 结构。
#
# 【要素 3 进阶】request: ExecuteRequest:
#   ExecuteRequest 中有一个字段 plan: list[PlanStep]
#
#   客户端发送的 JSON:
#     {
#       "conversation_id": "conv_001",
#       "plan": [                          ← JSON 数组
#         {
#           "step_id": "S1",               ← JSON 对象
#           "tool": "create_box",
#           "args": {"length": 100},       ← 嵌套的 JSON 对象
#           "depends_on": []               ← JSON 数组
#         },
#         {
#           "step_id": "S2",
#           "tool": "create_cylinder",
#           "args": {"radius": 10},
#           "depends_on": ["S1"]            <-- 引用了前一个步骤
#         }
#       ]
#     }
#
#   FastAPI 自动递归解析：
#     - 外层 → ExecuteRequest 对象
#     - plan[0] → PlanStep 对象 (step_id="S1", tool="create_box", ...)
#     - plan[0].args → dict {"length": 100}
#     - plan[1] → PlanStep 对象 (step_id="S2", ...)
#     - plan[1].depends_on → list ["S1"]
#
#   你的代码中直接使用:
#     for step in request.plan:
#         print(step.step_id)      # 类型安全的属性访问
#         print(step.tool)
#         print(step.depends_on)   # list[str]
#
#   如果用手写 dict 解析，你需要写:
#     for step in request_json["plan"]:
#         step_id = step.get("step_id")   # 可能拼错
#         tool = step.get("tool")         # 可能类型不对
#         # ... 一堆 if 校验 ...
#   Pydantic + FastAPI 全部帮你省掉了。

@app.post("/agent/execute", response_model=ExecuteResponse)
async def execute(request: ExecuteRequest):
    """
    接收建模计划并模拟执行。

    测试命令:
      curl -X POST http://127.0.0.1:8765/agent/execute \
        -H "Content-Type: application/json" \
        -d '{
          "conversation_id": "conv_001",
          "plan": [
            {"step_id": "S1", "description": "创建长方体", "tool": "create_box",
             "args": {"length": 100, "width": 60, "height": 20}, "depends_on": []},
            {"step_id": "S2", "description": "创建圆柱体", "tool": "create_cylinder",
             "args": {"radius": 10, "height": 30}, "depends_on": ["S1"]}
          ]
        }'

    预期响应 (HTTP 200):
      {
        "status": "success",
        "results": [
          {"step_id": "S1", "success": true, "message": "[模拟执行] 调用工具 create_box，参数 {...}"},
          {"step_id": "S2", "success": true, "message": "[模拟执行] 调用工具 create_cylinder，参数 {...}"}
        ]
      }
    """
    # ── 把 Pydantic 对象 list[PlanStep] 转成 list[dict] 传给业务逻辑 ──
    # 方式 1: 手动转换
    plan_dicts = [step.model_dump() for step in request.plan]
    # 方式 2: request.model_dump()["plan"] 也可以，但方式 1 更显式

    # ── 调用纯业务逻辑函数 ──
    exec_results = simulate_execution(plan_dicts)

    # ── 组装响应 ──
    return ExecuteResponse(
        status="success",
        results=[StepResult(**r) for r in exec_results],
    )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Step 4: 启动入口（直接运行 python main.py 时）                        ║
# ╚══════════════════════════════════════════════════════════════════════════╝
# 如果想直接 python main.py 启动而不是用 uvicorn 命令，可以取消下面的注释:
#
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("main:app", host="127.0.0.1", port=8765, reload=True)