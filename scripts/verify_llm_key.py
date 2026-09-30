#!/usr/bin/env python3
"""验证 .env 里的豆包凭证是否还活着。只打印结果，不打印凭证。"""
import json, pathlib, urllib.request, urllib.error

env = {}
for line in pathlib.Path("/Volumes/Mac mini/Max agent/Sammy/.env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

url = env["DOUBAO_BASE_URL"].rstrip("/") + "/chat/completions"
payload = {
    "model": env["DOUBAO_MODEL"],
    "messages": [
        {"role": "system", "content": "你是Sammy，一只住在桌面上的小家伙。回答简短、温暖，20字以内。"},
        {"role": "user", "content": "你好呀，你是谁？"},
    ],
    "temperature": 0.8,
}
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode(),
    headers={"Authorization": "Bearer " + env["DOUBAO_API_KEY"], "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.load(r)
    reply = body["choices"][0]["message"]["content"]
    usage = body.get("usage", {})
    print("✅ 豆包 API 还活着")
    print("   model :", body.get("model"))
    print("   回复  :", reply.strip())
    print("   用量  :", usage)
except urllib.error.HTTPError as e:
    detail = e.read().decode(errors="ignore")[:400]
    print(f"❌ HTTP {e.code} —— 凭证可能已失效或被停用")
    print("   服务端返回:", detail)
except Exception as e:
    print(f"❌ 连接失败: {type(e).__name__}: {e}")
