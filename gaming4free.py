import time
import os
import json
import re
import random
import requests

# 智能环境配置
if "DISPLAY" not in os.environ:
    os.environ["DISPLAY"] = ":1"
    
if "XAUTHORITY" not in os.environ:
    if os.path.exists("/home/headless/.Xauthority"):
        os.environ["XAUTHORITY"] = "/home/headless/.Xauthority"

from seleniumbase import SB

# ================= 配置区域 =================
PROXY_URL = os.getenv("PROXY", "")  
TG_TOKEN = os.getenv("TG_TOKEN")  
TG_CHAT_ID = os.getenv("TG_CHAT_ID")  
SERVERS = os.getenv("SERVERS", "").strip()  

SERVER_LIST = []
if SERVERS:
    for item in SERVERS.split("|"):
        try:
            num, region = item.split(",", 1)
            SERVER_LIST.append({"num": num.strip(), "region": region.strip()})
        except:
            print(f"⚠️ SERVERS 配置格式错误: {item}")
# ===========================================

class Game4FreeRenewal:
    def __init__(self):
        self.BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        self.screenshot_dir = os.path.join(self.BASE_DIR, "artifacts")
        if not os.path.exists(self.screenshot_dir):
            os.makedirs(self.screenshot_dir)

    def log(self, msg):
        timestamp = time.strftime('%H:%M:%S')
        print(f"[{timestamp}] [INFO] {msg}", flush=True)

    def human_wait(self, min_s=6, max_s=10):
        time.sleep(random.uniform(min_s, max_s))

    def time_to_seconds(self, t_str):
        """将 HH:MM:SS 格式转换为秒数，用于严格校验续期是否生效"""
        try:
            h, m, s = map(int, t_str.strip().split(':'))
            return h * 3600 + m * 60 + s
        except:
            return 0

    def clear_blocking_ads(self, sb):
        """清理可能遮挡 Turnstile/提交按钮的广告层（不触碰 Cloudflare iframe）"""
        try:
            removed = sb.execute_script("""
                var sel = 'ins, iframe[src*="google"], iframe[src*="doubleclick"], '
                        + 'div[id^="google_ads"], div[class*="ad-"], div[id^="ad_"], '
                        + 'div[class*="overlay"][style*="z-index"], '
                        + '[id*="sp_message"], .fc-consent-root';
                var nodes = document.querySelectorAll(sel);
                var n = 0;
                for (var i = 0; i < nodes.length; i++) {
                    var el = nodes[i];
                    // 绝不动 Cloudflare / Turnstile 相关节点
                    var html = (el.outerHTML || '').toLowerCase();
                    if (html.indexOf('cloudflare') >= 0 || html.indexOf('turnstile') >= 0 || html.indexOf('cf-') >= 0) {
                        continue;
                    }
                    el.remove();
                    n++;
                }
                return n;
            """)
            if removed:
                self.log(f"🧹 已清理 {removed} 个可能遮挡的广告/浮层节点")
        except Exception:
            pass

    def get_turnstile_token(self, sb):
        """读取 Cloudflare Turnstile 凭证；有值即表示验证已通过"""
        try:
            return sb.execute_script("""
                var selectors = [
                    '[name="cf-turnstile-response"]',
                    'textarea[name="cf-turnstile-response"]',
                    'input[name="cf-turnstile-response"]',
                    '[name="g-recaptcha-response"]'
                ];
                for (var i = 0; i < selectors.length; i++) {
                    var el = document.querySelector(selectors[i]);
                    if (el && el.value && el.value.length > 20) {
                        return el.value;
                    }
                }
                // 某些站点把 token 挂在 turnstile widget 的 data 属性上
                var widget = document.querySelector('[data-sitekey], .cf-turnstile, #cf-turnstile');
                if (widget) {
                    var t = widget.getAttribute('data-response') || widget.getAttribute('data-token');
                    if (t && t.length > 20) return t;
                }
                return '';
            """) or ""
        except Exception:
            return ""

    def has_cloudflare_widget(self, sb):
        """探测页面是否存在 Cloudflare Turnstile 组件"""
        try:
            return bool(sb.execute_script("""
                return !!(
                    document.querySelector('iframe[src*="challenges.cloudflare.com"]')
                    || document.querySelector('iframe[src*="turnstile"]')
                    || document.querySelector('iframe[title*="Cloudflare"]')
                    || document.querySelector('[name="cf-turnstile-response"]')
                    || document.querySelector('.cf-turnstile')
                    || document.querySelector('#cf-turnstile')
                );
            """))
        except Exception:
            return False

    def solve_turnstile(self, sb, server_num):
        """
        解 Cloudflare Turnstile。
        成功返回 True；探测到验证框却始终拿不到 token 时返回 False（fail-closed）。
        未探测到验证框则视为免检，返回 True。
        """
        self.log("📡 开始扫描 Cloudflare 验证框...")
        cf_found = False
        for _ in range(8):
            if self.has_cloudflare_widget(sb):
                cf_found = True
                break
            # 可能已经自动通过
            if self.get_turnstile_token(sb):
                self.log("✅ 已存在 Turnstile 凭证，无需手动点击")
                return True
            time.sleep(1)

        if not cf_found:
            # 再等一小会，部分站点延迟注入 widget
            time.sleep(2)
            if self.get_turnstile_token(sb):
                self.log("✅ 延迟检测到 Turnstile 凭证")
                return True
            if not self.has_cloudflare_widget(sb):
                self.log("✅ 扫描未发现验证框，当前 IP 免检")
                return True
            cf_found = True

        self.log("🛡️ 锁定 Cloudflare 验证框，执行物理点击...")
        self.clear_blocking_ads(sb)

        # 尽量把验证框滚到视口中心，避免 GUI 点击打偏
        try:
            sb.execute_script("""
                var iframe = document.querySelector(
                    'iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"], iframe[title*="Cloudflare"]'
                );
                var widget = document.querySelector('.cf-turnstile, #cf-turnstile, [data-sitekey]');
                var target = iframe || widget;
                if (target) {
                    target.scrollIntoView({block: 'center', inline: 'center'});
                } else {
                    var submit = document.querySelector('#vm-submit');
                    if (submit) submit.scrollIntoView({block: 'center'});
                }
            """)
            time.sleep(1)
        except Exception:
            pass

        strategies = [
            ("uc_gui_click_captcha", lambda: sb.uc_gui_click_captcha()),
            ("uc_gui_click_captcha(retry)", lambda: sb.uc_gui_click_captcha(retry=True)),
            ("uc_gui_click_captcha(blind)", lambda: sb.uc_gui_click_captcha(blind=True)),
            ("uc_gui_handle_captcha", lambda: sb.uc_gui_handle_captcha()),
        ]

        for attempt in range(1, 5):
            strategy_name, strategy_fn = strategies[(attempt - 1) % len(strategies)]
            try:
                self.log(f"🖱️ 验证尝试 {attempt}/4 使用策略: {strategy_name}")
                strategy_fn()
            except Exception as e:
                self.log(f"⚠️ 策略 {strategy_name} 异常: {e}")

            # Turnstile 出 token 有时需要数秒
            for wait_i in range(6):
                time.sleep(1.5)
                token = self.get_turnstile_token(sb)
                if token:
                    self.log(f"✅ Turnstile 验证成功（token 长度 {len(token)}，策略 {strategy_name}）")
                    return True

            self.clear_blocking_ads(sb)

        # 失败诊断
        token = self.get_turnstile_token(sb)
        try:
            diag = sb.execute_script("""
                return {
                    hasIframe: !!document.querySelector('iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"]'),
                    hasResponseField: !!document.querySelector('[name="cf-turnstile-response"]'),
                    responseLen: (document.querySelector('[name="cf-turnstile-response"]') || {}).value
                        ? document.querySelector('[name="cf-turnstile-response"]').value.length : 0,
                    submitDisabled: (function() {
                        var b = document.querySelector('#vm-submit');
                        return b ? (!!b.disabled || b.getAttribute('aria-disabled') === 'true') : null;
                    })(),
                    bodySnippet: (document.body && document.body.innerText || '').slice(0, 300)
                };
            """)
            self.log(f"🩺 验证失败诊断: {json.dumps(diag, ensure_ascii=False) if isinstance(diag, dict) else diag}")
        except Exception:
            pass

        try:
            fail_shot = f"{self.screenshot_dir}/captcha_fail_{server_num}.png"
            sb.save_screenshot(fail_shot)
            self.log(f"📸 已保存验证失败截图: {fail_shot}")
        except Exception:
            pass

        if token:
            self.log(f"✅ 末次检查拿到 token（长度 {len(token)}）")
            return True

        return False

    def move_mouse_human_advanced(self, sb):
        """生成更复杂的随机鼠标移动轨迹"""
        try:
            time.sleep(random.uniform(0.1, 0.4))
            width = sb.execute_script("return window.innerWidth;")
            height = sb.execute_script("return window.innerHeight;")

            regions = [
                (0.1 * width, 0.1 * height, 0.4 * width, 0.4 * height),
                (0.6 * width, 0.6 * height, 0.9 * width, 0.9 * height),
                (width / 2, height / 2, width / 2, height / 2)
            ]
            num_paths = random.randint(2, 3)

            for _ in range(num_paths):
                target_region = random.choice(regions)
                x_dest = random.randint(int(target_region[0]), int(target_region[2]))
                y_dest = random.randint(int(target_region[1]), int(target_region[3]))
                x_offset = random.randint(-5, 5)
                y_offset = random.randint(-5, 5)

                sb.execute_script(f"""
                    var evt = new MouseEvent("mousemove", {{
                        bubbles: true,
                        cancelable: true,
                        clientX: {x_dest + x_offset},
                        clientY: {y_dest + y_offset}
                    }});
                    document.body.dispatchEvent(evt);
                """)
                time.sleep(random.uniform(0.8, 1.5))
        except:
            pass
    
    def get_remaining_time(self, sb):
        remaining_text = "未知"
        try:
            sb.wait_for_element_visible('#sd-timer', timeout=15)
            time.sleep(1)
            remaining_text = sb.get_text('#sd-timer').strip()
        except Exception as e:
            try:
                remaining_text = sb.execute_script("""
                    var el = document.querySelector('#sd-timer');
                    return el ? el.innerText.trim() : null;
                """)
                if not remaining_text:
                    remaining_text = "未知"
            except:
                remaining_text = "未知"
        return remaining_text

    def send_telegram_notify(self, message, photo_path=None):
        if not TG_TOKEN or not TG_CHAT_ID:
            self.log("⚠️ 未配置 TG_TOKEN，跳过推送。")
            return
        try:
            if photo_path and os.path.exists(photo_path):
                url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
                with open(photo_path, 'rb') as f:
                    requests.post(url, data={'chat_id': TG_CHAT_ID, 'caption': message}, files={'photo': f})
            else:
                url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
                requests.post(url, data={'chat_id': TG_CHAT_ID, 'text': message})
            self.log("✅ TG 推送已发送")
        except Exception as e:
            self.log(f"❌ TG 推送失败: {e}")

    def run_single_server(self, server_num, region):
        URL_APP_PANEL = f"https://gaming4free.net/servers/{server_num}"

        self.log("=" * 40)
        self.log(f"🚀 开始续期 [{region}] ({server_num})")
        
        USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"

        with SB(
            uc=True,
            test=True,
            headed=True,
            headless=False,
            xvfb=False,
            chromium_arg=f"--no-sandbox,--disable-dev-shm-usage,--disable-gpu,--window-position=0,0,--start-maximized,--disable-blink-features=AutomationControlled,--disable-infobars,--disable-popup-blocking,--user-agent={USER_AGENT}",
            proxy=PROXY_URL if PROXY_URL else None
        ) as sb:
            try:
                self.log("✅ 浏览器已启动！")

                try:
                    sb.open("https://api.ipify.org?format=json")
                    ip_val = json.loads(re.search(r'\{.*\}', sb.get_text("body")).group(0)).get('ip', 'Unknown')
                    parts = ip_val.split('.')
                    self.log(f"✅ 当前出口 IP: {parts[0]}.{parts[1]}.***.{parts[-1]}")
                except:
                    pass

                self.log(f"📂 正在进入续期面板 [{region}] ...")
                sb.uc_open_with_reconnect(URL_APP_PANEL, reconnect_time=5)
                self.human_wait(8, 12)

                if "login" in sb.get_current_url().lower():
                    raise Exception("登录状态失效或权限被拒绝。")

                cookie_btns = ['//button[contains(., "Continue with Recommended Cookies")]', '//button[contains(., "Accept")]', '//button[contains(., "I Agree")]', '//button[contains(., "Consent")]']
                for btn in cookie_btns:
                    if sb.is_element_present(btn):
                        try:
                            sb.click(btn)
                            break
                        except:
                            pass

                timestamp_before = self.get_remaining_time(sb)
                self.log(f"🕒 续期前剩余运行时间: {timestamp_before}")

                sb.execute_script("window.scrollBy(0,800);")
                self.human_wait(2, 4)
                
                try:
                    self.log("🖱️ 正在迹点击 'VOTE + ADD 90 MIN'...")
                    self.move_mouse_human_advanced(sb)
                    sb.wait_for_element_visible("#sd-vote-btn", timeout=10)
                    sb.click('#sd-vote-btn')
                except Exception as e:
                    raise Exception(f"未找到打开模态框的按钮: {e}")

                self.log("⏳ 观看视频广告...")
                time.sleep(35) 
                
                try:
                    sb.execute_script("document.querySelector('#vm-submit').scrollIntoView({block: 'center'});")
                    time.sleep(1)
                except:
                    pass

                # 解 Cloudflare Turnstile：拿不到 token 就直接判失败（fail-closed），
                # 绝不带着空凭证去提交——那正是"时间没增加"的根因。
                if not self.solve_turnstile(sb, server_num):
                    raise Exception("Cloudflare Turnstile 验证失败：始终未能获取有效凭证，已终止提交以避免无效续期。")

                self.human_wait(2, 4)

                try:
                    self.log("🖱️ 正在点击最终提交按钮 'VOTE — ADDS 90 MINUTES'...")
                    # 提交前再清一次可能盖住按钮的贴片广告（不碰 CF 组件）
                    self.clear_blocking_ads(sb)
                    # 确保按钮不仅可见，还要处于可点击的激活状态（防广告遮挡或倒计时锁定）
                    sb.wait_for_element_clickable("#vm-submit", timeout=15)
                    sb.click('#vm-submit')
                    self.human_wait(8, 12)
                except Exception as e:
                    raise Exception("未能点击最终的确认提交按钮，可能是广告仍未加载完成导致按钮未激活。")

                time.sleep(8)
                
                timestamp_after = self.get_remaining_time(sb)
                self.log(f"🕒 续期后剩余运行时间: {timestamp_after}")

                sec_before = self.time_to_seconds(timestamp_before)
                sec_after = self.time_to_seconds(timestamp_after)
                
                if sec_after > 0 and sec_before > 0:
                    if sec_after <= sec_before + 120:  
                        raise Exception("时间并未增加！人机验证失败或提交请求被服务器拦截。")

                final_screenshot = f"{self.screenshot_dir}/final_success_{server_num}.png"
                sb.save_screenshot(final_screenshot)

                msg = f"✅ [{region}] 续期成功\n🖥️ 编号: {server_num}\n🕒 续期前剩余时间: {timestamp_before}\n🎉 续期后剩余时间: {timestamp_after}"
                self.send_telegram_notify(msg, final_screenshot)

            except Exception as e:
                self.log(f"❌ 运行异常: {e}")
                sb.save_screenshot(f"{self.screenshot_dir}/error_{server_num}.png")
                self.send_telegram_notify(f"❌ [{region}] 执行失败: {e}\n🖥️ 编号: {server_num}", f"{self.screenshot_dir}/error_{server_num}.png")

    def run(self):
        if not SERVER_LIST:
            self.log("❌ 未配置 SERVERS")
            return
        for server in SERVER_LIST:
            self.run_single_server(server["num"], server["region"])


if __name__ == "__main__":
    Game4FreeRenewal().run()
