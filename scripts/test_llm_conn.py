import sys

sys.path.insert(0, ".")
from app.llm.llm_provider import _get_llm_config, call_llm

api_key, base_url, model = _get_llm_config()
print("key:", api_key[:8] + "...")
print("base_url:", base_url)
print("model:", model)

result = call_llm(
    "只输出一个合法 JSON 对象，内容为 {'status': 'ok', 'echo': 'pong'}",
    "你是一个测试助手，只输出合法 JSON，不要任何多余文本。",
)
print("RESULT:", result)
