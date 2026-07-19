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
                return (function(){
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
                })();
            """)
            if removed:
                self.log(f"🧹 已清理 {removed} 个可能遮挡的广告/浮层节点")
        except Exception:
            pass

    def bypass_reward_ad(self, sb):
        """
        绕过 RAMP 激励视频广告门槛。
        页面点击 VOTE 后会调用 window.ramp.manuallyCreateRewardUi() 播放激励广告，
        只有其 Promise resolve 后才会 adWatched=true 并 openVoteModal() 打开含 Turnstile
        的投票模态框。在代理/自动化环境中激励广告往往无填充、Promise 永不 resolve，
        导致模态框永不打开——这是"时间不增加"的首要根因。
        这里将该方法覆盖为立即 resolve，使点击 VOTE 后模态框能正常打开。
        """
        try:
            ok = sb.execute_script("""
                return (function(){
                    try {
                        window.ramp = window.ramp || {};
                        if (!window.ramp.que || typeof window.ramp.que.push !== 'function') {
                            window.ramp.que = { push: function(f){ try{ f(); }catch(e){} } };
                        }
                        window.ramp.manuallyCreateRewardUi = function(){ return Promise.resolve(); };
                        window.ramp.spaAddAds = window.ramp.spaAddAds || function(){};
                        return true;
                    } catch (e) { return false; }
                })();
            """)
            if ok:
                self.log("🎟️ 已短路激励广告门槛（manuallyCreateRewardUi 立即放行）")
            else:
                self.log("⚠️ 激励广告短路脚本执行返回 false")
        except Exception as e:
            self.log(f"⚠️ 激励广告短路注入失败: {e}")

    def wait_for_vote_modal(self, sb, timeout=25):
        """等待投票模态框真正打开（vote-overlay 处于 open/可见）"""
        for _ in range(timeout):
            try:
                opened = sb.execute_script("""
                    return (function(){
                        var ov = document.querySelector('#vote-overlay');
                        if (!ov) return false;
                        var cs = getComputedStyle(ov);
                        return ov.classList.contains('open') || cs.display !== 'none';
                    })();
                """)
                if opened:
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def get_turnstile_token(self, sb):
        """读取 Cloudflare Turnstile 凭证；有值即表示验证已通过（优先用官方 getResponse）"""
        try:
            return sb.execute_script("""
                return (function(){
                    // 1) 官方 API：与页面提交逻辑 window.turnstile.getResponse() 完全一致
                    try {
                        if (window.turnstile && typeof window.turnstile.getResponse === 'function') {
                            var r = window.turnstile.getResponse();
                            if (r && r.length > 20) return r;
                        }
                    } catch (e) {}
                    // 2) 隐藏字段兜底
                    var el = document.querySelector('[name="cf-turnstile-response"]');
                    if (el && el.value && el.value.length > 20) return el.value;
                    return '';
                })();
            """) or ""
        except Exception:
            return ""

    def is_submit_enabled(self, sb):
        """
        #vm-submit 由 Turnstile 的 callback 直接解禁（disabled=false）。
        这是页面自身认定"验证通过"的权威信号，比探测 iframe 更可靠。
        """
        try:
            return bool(sb.execute_script("""
                return (function(){
                    var b = document.querySelector('#vm-submit');
                    return b ? (!b.disabled && b.getAttribute('aria-disabled') !== 'true') : false;
                })();
            """))
        except Exception:
            return False

    def solve_turnstile(self, sb, server_num):
        """
        解模态框内的 Cloudflare Turnstile。
        成功信号 = #vm-submit 解禁 或 turnstile.getResponse() 拿到 token。
        始终拿不到则返回 False（fail-closed），绝不带空凭证提交。
        """
        self.log("📡 等待 Turnstile 组件渲染...")
        # 等 widget 渲染出 iframe / 或已自动通过
        for _ in range(15):
            if self.is_submit_enabled(sb) or self.get_turnstile_token(sb):
                self.log("✅ Turnstile 已通过（无需手动点击）")
                return True
            has_iframe = False
            try:
                has_iframe = bool(sb.execute_script(
                    "return !!document.querySelector('iframe[src*=\"challenges.cloudflare.com\"], iframe[src*=\"turnstile\"]')"
                ))
            except Exception:
                pass
            if has_iframe:
                break
            time.sleep(1)

        self.log("🛡️ 尝试点击 Turnstile 验证框...")
        # 把验证框滚到视口中心，避免 GUI 物理点击打偏
        try:
            sb.execute_script("""
                var t = document.querySelector(
                    'iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"], #ts-widget, .cf-turnstile'
                );
                if (t) t.scrollIntoView({block: 'center', inline: 'center'});
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
            # 每轮开始先检查是否已经通过（Turnstile 可能无交互自动放行）
            if self.is_submit_enabled(sb) or self.get_turnstile_token(sb):
                token = self.get_turnstile_token(sb)
                self.log(f"✅ Turnstile 验证成功（submit 已解禁，token 长度 {len(token)}）")
                return True

            strategy_name, strategy_fn = strategies[(attempt - 1) % len(strategies)]
            try:
                self.log(f"🖱️ 验证尝试 {attempt}/4 使用策略: {strategy_name}")
                strategy_fn()
            except Exception as e:
                self.log(f"⚠️ 策略 {strategy_name} 异常: {e}")

            # 出 token / 解禁有延迟，轮询等待
            for _ in range(6):
                time.sleep(1.5)
                if self.is_submit_enabled(sb) or self.get_turnstile_token(sb):
                    token = self.get_turnstile_token(sb)
                    self.log(f"✅ Turnstile 验证成功（策略 {strategy_name}，token 长度 {len(token)}）")
                    return True

        # 失败诊断
        try:
            diag = sb.execute_script("""
                return {
                    hasIframe: !!document.querySelector('iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"]'),
                    modalOpen: (function(){ var o=document.querySelector('#vote-overlay'); return o ? o.classList.contains('open') : null; })(),
                    submitDisabled: (function(){ var b=document.querySelector('#vm-submit'); return b ? !!b.disabled : null; })(),
                    tokenLen: (function(){ try { var r = window.turnstile && window.turnstile.getResponse ? window.turnstile.getResponse() : ''; return r ? r.length : 0; } catch(e){ return -1; } })(),
                    bodySnippet: (document.body && document.body.innerText || '').slice(0, 200)
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
                    return (function(){
                        var el = document.querySelector('#sd-timer');
                        return el ? el.innerText.trim() : null;
                    })();
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

                # 点击 VOTE 会触发 RAMP 激励视频广告，只有广告"播完"才会打开
                # 含 Turnstile 的投票模态框。自动化/代理环境广告无填充，故先短路广告门槛。
                self.bypass_reward_ad(sb)

                try:
                    self.log("🖱️ 正在点击 'VOTE + ADD 90 MIN'...")
                    self.move_mouse_human_advanced(sb)
                    sb.wait_for_element_visible("#sd-vote-btn", timeout=10)
                    sb.click('#sd-vote-btn')
                except Exception as e:
                    raise Exception(f"未找到打开模态框的按钮: {e}")

                # 广告已短路，模态框应很快打开；若未打开则说明流程被拦截
                if not self.wait_for_vote_modal(sb, timeout=25):
                    # 兜底：某些时序下 ramp 覆盖晚于点击，再补一次并直接调用打开逻辑
                    self.bypass_reward_ad(sb)
                    try:
                        sb.execute_script("if (typeof openVoteModal === 'function') openVoteModal();")
                    except Exception:
                        pass
                    if not self.wait_for_vote_modal(sb, timeout=15):
                        raise Exception("投票模态框未能打开（激励广告门槛未通过）。")
                self.log("✅ 投票模态框已打开")

                try:
                    sb.execute_script("document.querySelector('#vm-submit').scrollIntoView({block: 'center'});")
                    time.sleep(1)
                except:
                    pass

                # 解 Cloudflare Turnstile：拿不到 token/按钮未解禁就直接判失败（fail-closed），
                # 绝不带着空凭证去点提交——页面 handler 对空 token 会静默丢弃请求。
                if not self.solve_turnstile(sb, server_num):
                    raise Exception("Cloudflare Turnstile 验证失败：submit 始终未解禁且无有效 token，已终止提交。")

                self.human_wait(2, 4)

                try:
                    self.log("🖱️ 正在点击最终提交按钮 'VOTE — ADDS 90 MINUTES'...")
                    # 提交前再清一次可能盖住按钮的贴片广告（不碰 CF 组件）
                    self.clear_blocking_ads(sb)
                    # 此时 submit 已由 Turnstile callback 解禁，等待可点击后提交
                    sb.wait_for_element_clickable("#vm-submit", timeout=15)
                    sb.click('#vm-submit')
                    self.human_wait(8, 12)
                except Exception as e:
                    raise Exception("未能点击最终的确认提交按钮，可能是广告仍未加载完成导致按钮未激活。")

                # 优先用页面自身的结果提示 #vm-msg 精确判定（成功会带 'ok' class 与提示文案）
                vote_result = None
                for _ in range(10):
                    try:
                        vote_result = sb.execute_script("""
                            return (function(){
                                var m = document.querySelector('#vm-msg');
                                if (!m) return null;
                                var cls = m.className || '';
                                var txt = (m.textContent || '').trim();
                                if (cls.indexOf('ok') >= 0) return {ok: true, text: txt};
                                if (cls.indexOf('err') >= 0 || cls.indexOf('error') >= 0) return {ok: false, text: txt};
                                if (txt && txt.toLowerCase() !== 'submitting…' && txt.toLowerCase() !== 'submitting...') {
                                    return {pending: true, text: txt};
                                }
                                return null;
                            })();
                        """)
                    except Exception:
                        vote_result = None
                    if vote_result and (vote_result.get('ok') or vote_result.get('ok') is False):
                        break
                    time.sleep(1.5)

                if isinstance(vote_result, dict) and vote_result.get('ok') is False:
                    raise Exception(f"服务器拒绝了投票请求: {vote_result.get('text')}")

                time.sleep(6)

                timestamp_after = self.get_remaining_time(sb)
                self.log(f"🕒 续期后剩余运行时间: {timestamp_after}")

                sec_before = self.time_to_seconds(timestamp_before)
                sec_after = self.time_to_seconds(timestamp_after)

                # 双重校验：页面结果提示 + 时间增量。任一确认失败即报错。
                page_said_ok = isinstance(vote_result, dict) and vote_result.get('ok') is True
                time_increased = sec_after > 0 and sec_before > 0 and sec_after > sec_before + 120

                if not page_said_ok and not time_increased:
                    detail = vote_result.get('text') if isinstance(vote_result, dict) else "无页面提示"
                    raise Exception(f"时间未增加且未收到成功提示（{detail}）。人机验证或广告校验可能未通过。")

                if page_said_ok:
                    self.log(f"✅ 页面确认投票成功: {vote_result.get('text')}")

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
