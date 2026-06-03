import os, sys, time, urllib.request, json
from seleniumbase import SB

# ==========================================
# 💡 核心配置 (适配全新 g4f.gg 界面)
# ==========================================
TARGET_URL = "https://g4f.gg/renqi" 
MC_USERNAME = "renqi"

TG_TOKEN = os.getenv("TG_TOKEN", "")
TG_CHAT = os.getenv("TG_CHAT_ID", "")

def send_tg(msg):
    if TG_TOKEN and TG_CHAT:
        try:
            url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
            data = json.dumps({"chat_id": TG_CHAT, "text": f"🤖 G4F 自动续期:\n{msg}"}).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=10)
        except:
            pass

print(f"\n===== 🚀 开始执行极速续期 (G4F.GG 赛博朋克全新版) =====")

# 继续使用我们无敌的 WARP 本地代理
proxy_str = "socks5://127.0.0.1:40000"

with SB(uc=True, proxy=proxy_str, headless=False) as sb:
    try:
        print(f"🌐 正在通过 WARP 访问新版目标网址: {TARGET_URL}")
        sb.open(TARGET_URL)
        
        # 给炫酷的 UI 一点加载时间
        sb.sleep(5) 
        
        os.makedirs("screenshots", exist_ok=True)
        sb.save_screenshot("screenshots/1_page_loaded.png")

        print("✍️ 尝试填入游戏ID (OPTIONAL)...")
        try:
            # 根据截图，输入框的 placeholder 是 "Steve, xX_Player_Xx, ..."
            sb.type('input[placeholder*="Steve"]', MC_USERNAME, timeout=5)
            print("✅ ID 填入成功！")
        except:
            print("ℹ️ 未找到输入框，直接继续下一步。")

        print("🚀 寻找 [+ ADD 90 MIN] 核心按钮...")
        # 🌟 核心修复：加上 xpath= 前缀，明确告诉引擎这是 XPath！
        add_btn_xpath = 'xpath=//*[contains(text(), "ADD 90 MIN") or contains(text(), "Add 90 Min")]'
        
        sb.wait_for_element(add_btn_xpath, timeout=15)
        
        print("🖱️ 强行点击续期按钮！")
        # 🌟 核心修复：改用原生霸道点击，完美兼容 XPath
        sb.click(add_btn_xpath)

        print("⏳ 等待服务器响应...")
        sb.sleep(8)
        sb.save_screenshot("screenshots/2_result.png")

        print("✅ 续期点击已执行！")
        send_tg(f"✅ 服务器 [{MC_USERNAME}] 续期按钮已点击！\n官方界面已重构，请查看 GitHub 截图确认是否真正成功增加了时间。")

    except Exception as e:
        print(f"❌ 发生致命错误: {e}")
        os.makedirs("screenshots", exist_ok=True)
        sb.save_screenshot("screenshots/error.png")
        send_tg(f"❌ 自动续期崩溃: {e}")
