import argparse
import json
import subprocess
import threading
import time
import socket
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import uvicorn

"""
获取Notion Webhook的Token 手动连接
"""
app = FastAPI()
challenge_token = None
env = "server"  # 默认环境

@app.post("/notion/webhook")
async def webhook(request: Request):
    global challenge_token
    body = await request.json()
    print(f"\n📩 收到请求:\n{json.dumps(body, indent=2, ensure_ascii=False)}")
    if body.get("type") == "challenge":
        challenge_token = body["challenge"]
        print(f"\n✅ 收到 Notion Challenge Token: {challenge_token}")
        return PlainTextResponse(challenge_token, status_code=200)
    return {"status": "received"}

def start_server():
    if env == "server":
        uvicorn.run(app, host="0.0.0.0", port=8081,
                    ssl_certfile="./config/cyhank.com.crt",
                    ssl_keyfile="./config/cyhank.com.key")
    else:
        uvicorn.run(app, host="0.0.0.0", port=8081)

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ip

def start_ngrok():
    print("🚇 启动 ngrok 隧道...")
    ngrok = subprocess.Popen(["ngrok", "http", "8080"])
    time.sleep(3)
    try:
        tunnels = subprocess.check_output(["curl", "-s", "http://localhost:4040/api/tunnels"])
        tunnels = json.loads(tunnels)
        for t in tunnels["tunnels"]:
            if t["proto"] == "https":
                public_url = t['public_url']
                print(f"🔗 [local] 请将以下 URL 配置到 Notion webhook：")
                print(f"{public_url}/notion/webhook")
                break
    except Exception as e:
        print("❌ 获取 ngrok URL 失败:", e)
    return ngrok

def main():
    global env

    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=["local", "server"], default="server")
    args = parser.parse_args()
    env = args.env

    threading.Thread(target=start_server, daemon=True).start()
    time.sleep(2)

    if env == "local":
        ngrok_proc = start_ngrok()
    else:
        # ip = get_local_ip()
        print(f"🔗 [server] 请在 Notion 中配置 Webhook：")
        print(f"https://cyhank.com/notion/webhook")
        ngrok_proc = None

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("🛑 正在退出...")
        if ngrok_proc:
            ngrok_proc.terminate()

if __name__ == "__main__":
    main()
