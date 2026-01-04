"""
Telegram 配置测试脚本
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

print("=" * 60)
print("Telegram 配置检查")
print("=" * 60)
print(f"Bot Token: {token[:20]}..." if token else "❌ 未设置")
print(f"Chat ID: {chat_id}" if chat_id else "❌ 未设置")
print()

if token and chat_id:
    print("请确认:")
    print(f"1. 已在 Telegram 打开 @silvio_whale_bot")
    print(f"2. 已点击 START 按钮")
    print(f"3. Chat ID 是纯数字: {chat_id}")
    print()
    
    # 测试发送
    import asyncio
    import aiohttp
    
    async def test():
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": "🤖 测试消息",
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data) as resp:
                result = await resp.json()
                print("API 返回:")
                print(result)
                if result.get("ok"):
                    print("\n✅ 发送成功!")
                else:
                    print(f"\n❌ 发送失败: {result.get('description')}")
    
    asyncio.run(test())
else:
    print("请在 .env 文件配置:")
    print("TELEGRAM_BOT_TOKEN=your_token")
    print("TELEGRAM_CHAT_ID=your_chat_id")
