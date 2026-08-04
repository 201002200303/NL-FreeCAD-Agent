"""
=============================================================================
数据全链路追踪脚本 — 模拟一次 POST /agent/plan 请求流经 5 层
=============================================================================
运行方式:
    cd agent_service/tutorial
    python trace_data_flow.py

这个脚本不用启动真实服务器，使用 FastAPI TestClient 发送模拟请求。
每一层都打印出：
  - 当前是哪一层
  - 数据长什么样（原始格式 → 转换后格式）
  - 谁调用了谁

对照你项目的架构图看：
  请求进来 → [1.应用实例] → [2.中间件] → [3.路由端点] → [4.Schema校验] → [5.业务逻辑] → 响应返回
=============================================================================
"""

import sys
import os
import json

# 确保能找到 app 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

# ═══════════════════════════════════════════════════════════════════════════
# 步骤 0：构建一个带追踪的 app 副本（用中间件拦截，打印每层数据）
# ═══════════════════════════════════════════════════════════════════════════

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import VERSION
from app.schemas.request import PlanRequest
from app.schemas.response import PlanResponse, HealthResponse
from app.llm.planner import generate_plan

# 重新创建一个 app 实例（和真实 main.py 一模一样的配置）
app = FastAPI(
    title="NL-FreeCAD-Agent [TRACE MODE]",
    version=VERSION,
    description="全链路追踪模式",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════════════════
# 添加一个追踪中间件 — 用来看请求怎么穿过第 2 层
# ═══════════════════════════════════════════════════════════════════════════

class TraceMiddleware(BaseHTTPMiddleware):
    """
    这个自定义中间件会在 CORS 之后、路由函数之前执行，
    让你看到原始 HTTP 请求长什么样。
    """
    async def dispatch(self, request: Request, call_next):
        print("\n" + "=" * 70)
        print("  [第 2 层] 中间件层 — CORS 已放行，准备进入路由")
        print("=" * 70)
        print(f"  请求方法:    {request.method}")
        print(f"  请求路径:    {request.url.path}")
        print(f"  Content-Type: {request.headers.get('content-type', 'N/A')}")

        # 读取原始 Body（注意：TestClient 环境下可以直接读）
        body_bytes = await request.body()
        try:
            body_str = body_bytes.decode("utf-8")
            body_json = json.loads(body_str)
            print(f"  原始 Body (JSON):")
            print(f"    {json.dumps(body_json, indent=4, ensure_ascii=False)}")
        except:
            print(f"  原始 Body (bytes): {body_bytes[:200]}...")

        # 继续传递给下一个中间件/路由
        response = await call_next(request)

        # 响应回来时
        print(f"\n  ← 中间件层收到响应: HTTP {response.status_code}")
        return response


# 追踪中间件放在 CORS 之后（后加的先执行，但这里我们用 BaseHTTPMiddleware 会在路由前执行 dispatch）
# 注意：add_middleware 的顺序：先加的在外层。我们要在 CORS 之后拦截，所以 CORS 先加，Trace 后加
# 实际上 Starlette 中后加的中间件包裹在外层... 但这里我们的 TraceMiddleware 的 dispatch 会在
# CORS 处理后、路由前执行，因为 CORSMiddleware 对非 OPTIONS 请求只是透传。
app.add_middleware(TraceMiddleware)


# ═══════════════════════════════════════════════════════════════════════════
# 和真实 main.py 一模一样的路由定义
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", version=VERSION)


@app.post("/agent/plan", response_model=PlanResponse)
async def plan(request: PlanRequest):
    """
    这个函数就是第 3 层 + 第 4 层 + 第 5 层的交汇点。
    到这一步时，FastAPI 已经完成了 Schema 校验（第 4 层）。
    """
    # ═══════════════════════════════════════════════════════════════════
    # 第 3 层：路由端点 — 函数被调用时，request 已经是 PlanRequest 对象
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  [第 3 层] 路由端点 — @app.post('/agent/plan') 命中！")
    print("=" * 70)

    # ═══════════════════════════════════════════════════════════════════
    # 第 4 层：Schema 校验 — 数据已通过 Pydantic 校验
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n  [第 4 层] Schema 校验 — FastAPI 已完成 PlanRequest 校验")
    print(f"  ─────────────────────────────────────────────────")
    print(f"  request 的类型:     {type(request).__name__}")
    print(f"  request.user_input:  \"{request.user_input}\"")
    print(f"  request.document_state: {request.document_state}")
    print(f"  request.conversation_id: {request.conversation_id}")
    print(f"\n  PlanRequest 完整模型:")
    print(f"  {request.model_dump()}")

    # ═══════════════════════════════════════════════════════════════════
    # 第 5 层：业务逻辑 — 调用 generate_plan()
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  [第 5 层] 业务逻辑 — 调用 generate_plan()")
    print("=" * 70)
    print(f"  传入参数:")
    print(f"    user_input      = \"{request.user_input}\"")
    print(f"    document_state  = {request.document_state}")

    # ── 执行业务逻辑 ──
    result = generate_plan(request.user_input, request.document_state)

    print(f"\n  业务逻辑返回 (dict):")
    print(f"    status:    {result['status']}")
    print(f"    goal:      {result['goal']}")
    print(f"    plan 步数:  {len(result['plan'])}")
    if result["plan"]:
        for step in result["plan"]:
            print(f"      - {step['step_id']}: {step['tool']}({step['args']})")

    # ═══════════════════════════════════════════════════════════════════
    # 响应组装：dict → Pydantic → FastAPI 自动序列化为 JSON
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  [响应组装] dict → PlanResponse → JSON")
    print("=" * 70)

    response_obj = PlanResponse(**result)
    print(f"  PlanResponse 对象已构造:")
    print(f"    type: {type(response_obj).__name__}")
    print(f"    status: {response_obj.status}")
    print(f"    plan[0] type: {type(response_obj.plan[0]).__name__ if response_obj.plan else 'N/A'}")

    # model_dump() 是 Pydantic 把对象转成 dict 的方法
    response_dict = response_obj.model_dump()
    print(f"\n  序列化前的 dict:")
    print(f"  {json.dumps(response_dict, indent=2, ensure_ascii=False)}")

    print(f"\n  → 接下来 FastAPI 会:")
    print(f"    1. 用 response_model=PlanResponse 再校验一次")
    print(f"    2. json.dumps() 序列化为 JSON 字符串")
    print(f"    3. 设置 Content-Type: application/json")
    print(f"    4. 返回 HTTP 200")

    return response_obj


# ═══════════════════════════════════════════════════════════════════════════
# 主程序：模拟客户端发送请求
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 创建 TestClient（不启动真实服务器，直接在内存中模拟 HTTP 请求）
    client = TestClient(app)

    print("=" * 70)
    print("  NL-FreeCAD-Agent 全链路数据追踪")
    print("=" * 70)

    # ═══════════════════════════════════════════════════════════════════
    # 模拟请求 1：正常的长方体建模请求
    # ═══════════════════════════════════════════════════════════════════

    print("""
╔══════════════════════════════════════════════════════════════════════════╗
║                   测试 1: 长方体建模请求                                  ║
║  用户说: "画一个 100x60x20mm 的底座"                                     ║
╚══════════════════════════════════════════════════════════════════════════╝""")

    # ═══════════════════════════════════════════════════════════════════
    # 第 1 层：应用实例 — TestClient 找到 app，准备发请求
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  [第 1 层] 应用实例 — FastAPI app 接收请求")
    print("=" * 70)
    print(f"  app.title: {app.title}")
    print(f"  app.version: {app.version}")
    print(f"  已注册路由:")
    for route in app.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            print(f"    {route.methods} {route.path}")

    # 客户端要发送的 JSON 数据
    request_body = {
        "user_input": "画一个 100x60x20mm 的底座",
        "document_state": None,
        "conversation_id": None,
    }

    print(f"\n  客户端准备发送的 JSON:")
    print(f"  {json.dumps(request_body, indent=2, ensure_ascii=False)}")
    print(f"\n  → 发送: POST /agent/plan")
    print(f"  → Content-Type: application/json")
    print(f"  → Body: {json.dumps(request_body)} 字节")

    # ── 发起请求（这会触发整个链路）──
    response = client.post("/agent/plan", json=request_body)

    # ── 最终结果 ──
    print("\n" + "=" * 70)
    print("  [最终响应] 客户端收到的完整响应")
    print("=" * 70)
    print(f"  HTTP 状态码: {response.status_code}")
    print(f"  Content-Type: {response.headers.get('content-type')}")
    print(f"\n  响应 Body (JSON):")
    print(f"  {json.dumps(response.json(), indent=2, ensure_ascii=False)}")

    # ═══════════════════════════════════════════════════════════════════
    # 模拟请求 2：无法识别的请求
    # ═══════════════════════════════════════════════════════════════════

    print("""
╔══════════════════════════════════════════════════════════════════════════╗
║                 测试 2: 无法识别的请求                                    ║
║  用户说: "帮我设计核反应堆"                                              ║
╚══════════════════════════════════════════════════════════════════════════╝""")

    print("\n  [第 1 层] 应用实例 — 准备接收新请求...")

    response2 = client.post("/agent/plan", json={
        "user_input": "帮我设计核反应堆",
        "document_state": None,
        "conversation_id": None,
    })

    print(f"\n  [最终响应] HTTP {response2.status_code}")
    resp_json = response2.json()
    print(f"  status:   {resp_json['status']}")
    print(f"  question: {resp_json.get('question', 'N/A')}")


    # ═══════════════════════════════════════════════════════════════════
    # 总结：整个链路的数据变形过程
    # ═══════════════════════════════════════════════════════════════════

    print("""
╔══════════════════════════════════════════════════════════════════════════╗
║                         数 据 变 形 总 结                                  ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  Python dict ──JSON序列化──→ HTTP Body (bytes)                           ║
║       ↓  (客户端发送)                                                     ║
║  [1.应用实例] FastAPI app 接收 TCP 连接                                   ║
║       ↓                                                                  ║
║  [2.中间件] CORS 放行 → TraceMiddleware 捕获原始 Body                     ║
║       ↓                                                                  ║
║  [3.路由端点] URL /agent/plan + POST 匹配到 plan() 函数                  ║
║       ↓                                                                  ║
║  [4.Schema校验] json.loads() → PlanRequest(**dict)                       ║
║       │  bytes 变成 Pydantic 对象                                          ║
║       │  request.user_input  = "画一个 100x60x20mm 的底座"                ║
║       ↓                                                                  ║
║  [5.业务逻辑] generate_plan(request.user_input)                           ║
║       │  规则匹配 → 返回 dict                                              ║
║       │  result = {"status":"ok", "goal":"...", "plan":[...]}            ║
║       ↓                                                                  ║
║  [响应组装] PlanResponse(**result) — dict → Pydantic 对象                 ║
║       ↓                                                                  ║
║  FastAPI 自动: model_dump() → json.dumps() → HTTP 200                    ║
║       │  Pydantic 对象 变成 JSON 字符串                                     ║
║       ↓                                                                  ║
║  客户端收到: {"status":"ok","goal":"创建一个 100.0×60.0×20.0mm...",...}   ║
║                                                                          ║
║  数据经历了 3 次形态转换:                                                  ║
║    dict → PlanRequest对象 → dict(业务逻辑输出) → PlanResponse对象 → JSON  ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
""")