import os, sys, time, urllib.request, json
from seleniumbase import SB

# ==========================================
# 💡 核心配置 (G4F.GG 双重核武制导版)
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

print(f"\n===== 🚀 开始执行极速续期 (终极双重核武狙击版) =====")

proxy_str = "socks5://127.0.0.1:40000"

with SB(uc=True, proxy=proxy_str, headless=False, window_size="1920,1080") as sb:
    try:
        print("⏳ 正在为虚拟显示器安装 xdotool 物理鼠标引擎...")
        os.system("sudo apt-get update > /dev/null 2>&1")
        os.system("sudo apt-get install -y xdotool > /dev/null 2>&1")

        print(f"🌐 正在通过 WARP 访问新版目标网址: {TARGET_URL}")
        sb.open(TARGET_URL)
        sb.sleep(6) 
        
        os.makedirs("screenshots", exist_ok=True)
        sb.save_screenshot("screenshots/1_page_loaded.png")

        print("✍️ 尝试填入游戏ID (OPTIONAL)...")
        try:
            sb.type('input[placeholder*="Steve"], input[placeholder*="Player"]', MC_USERNAME, timeout=4)
            print("✅ ID 填入成功！")
        except:
            print("ℹ️ 未找到输入框或无需填入，继续下一步。")

        print("🚀 触发 [+ ADD 90 MIN] 核心按钮...")
        
        js_click_code = """
        let els = document.querySelectorAll('button, a, input, div, span');
        for (let i = els.length - 1; i >= 0; i--) {
            let el = els[i];
            let text = (el.innerText || el.value || '').toUpperCase();
            if (text.includes('ADD 90')) {
                el.click();
                break;
            }
        }
        """
        sb.execute_script(js_click_code)
        
        try:
            sb.click('xpath=//*[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "add 90")]', timeout=2)
        except:
            pass

        print("⏳ 盲等 6 秒钟，等待 CF 盾在屏幕上展开...")
        time.sleep(6) 
        
        print("🛡️ 启动【穿甲雷达】模块，递归撕裂 Shadow DOM！")
        
        # 🌟 修复：引入递归函数，强行穿透所有 Shadow DOM 黑盒寻找 iframe
        js_radar = """
        (function() {
            function getIframe(root) {
                let iframes = root.querySelectorAll('iframe');
                for(let f of iframes) {
                    let s = (f.src || '').toLowerCase();
                    if(s.includes('cloudflare') || s.includes('turnstile')) return f;
                }
                let all = root.querySelectorAll('*');
                for(let el of all) {
                    if(el.shadowRoot) {
                        let found = getIframe(el.shadowRoot);
                        if(found) return found;
                    }
                }
                return null;
            }
            
            let cf = getIframe(document);
            if (cf) {
                let rect = cf.getBoundingClientRect();
                let ui_y = 85; 
                let target_x = rect.left + 30;
                let target_y = rect.top + ui_y + (rect.height / 2);
                document.body.setAttribute('data-cf-coords', Math.round(target_x) + ',' + Math.round(target_y));
            } else {
                document.body.setAttribute('data-cf-coords', 'NOT_FOUND');
            }
        })();
        """
        sb.execute_script(js_radar)
        
        coords = None
        try:
            coords = sb.get_attribute("body", "data-cf-coords")
        except:
            pass
        
        # 🌟 双重核武判定：如果雷达找到就用雷达，找不到直接启用黄金坐标！
        if coords and coords != "NOT_FOUND":
            target_x, target_y = coords.split(",")
            print(f"🎯 穿甲雷达精确锁定 CF 盾绝对靶心: ({target_x}, {target_y})")
        else:
            print("⚠️ 雷达未能穿透深层黑盒，启用【黄金盲狙坐标】！")
            # 在 1920x1080 且有 85px 浏览器顶栏的情况下，绝对居中遮罩的复选框永远在这！
            target_x, target_y = "820", "580"
            print(f"🎯 锁定黄金物理坐标: ({target_x}, {target_y})")

        print("🖱️ 物理鼠标按下扳机！")
        os.system(f"xdotool mousemove {target_x} {target_y} click 1")
        
        print("⏳ 射击完毕！静默等待 8 秒，让子弹飞一会儿 (等待盾转圈通过)...")
        time.sleep(8)
            
        try:
            sb.save_screenshot("screenshots/2_result.png")
            print("📸 最终战况截图已保存。")
        except:
            print("⚠️ 截图保存失败。")

        print("✅ 流程执行完毕！")
        send_tg(f"✅ 服务器 [{MC_USERNAME}] 续期脚本运行完毕！\n【破盾方式: 双重核武物理盲狙】请查阅 GitHub 截图确认战果。")

    except Exception as e:
        print(f"❌ 发生致命错误: {e}")
        try:
            os.makedirs("screenshots", exist_ok=True)
            sb.save_screenshot("screenshots/error.png")
        except:
            pass
        send_tg(f"❌ 自动续期崩溃: {e}")
