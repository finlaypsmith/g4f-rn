/**
 * Gaming4Free 自动续期（投票面板版）
 *
 * 过 Cloudflare Turnstile 的核心：puppeteer-real-browser 的 turnstile:true 自动求解，
 * 且其反检测指纹足够真，通常让 CF 直接 invisible 放行、不弹 interactive challenge。
 * 这是 SeleniumBase + pyautogui 物理点击方案（在模态框内坐标不准、被 CF 判可疑）
 * 无法解决的死结所在。
 *
 * 已探明的投票面板真实流程（见 chrome-devtools 调试结论）：
 *   点 #sd-vote-btn → RAMP 激励视频广告 manuallyCreateRewardUi() 的 Promise resolve
 *   后才 adWatched=true 且 openVoteModal() 打开含 Turnstile 的模态框 → Turnstile 通过
 *   后 callback 解禁 #vm-submit → 点提交时 getResponse() 拿 token，空 token 静默丢弃
 *   → POST control.gaming4free.net/api/servers/{slug}/vote → 成功时 #vm-msg 加 'ok' class。
 *
 * 环境变量（沿用旧 Python 版约定，无需改 Secrets）：
 *   PROXY       socks5://127.0.0.1:10808
 *   TG_TOKEN    Telegram bot token
 *   TG_CHAT_ID  Telegram chat id
 *   SERVERS     "num1,region1|num2,region2"
 */

const { connect } = require('puppeteer-real-browser');

const PROXY_URL = process.env.PROXY || '';
const TG_TOKEN = process.env.TG_TOKEN;
const TG_CHAT_ID = process.env.TG_CHAT_ID;
const SERVERS = (process.env.SERVERS || '').trim();

const SERVER_LIST = [];
if (SERVERS) {
    for (const item of SERVERS.split('|')) {
        const idx = item.indexOf(',');
        if (idx > 0) {
            SERVER_LIST.push({
                num: item.slice(0, idx).trim(),
                region: item.slice(idx + 1).trim(),
            });
        } else {
            log(`⚠️ SERVERS 配置格式错误: ${item}`);
        }
    }
}

function log(msg) {
    const t = new Date().toTimeString().slice(0, 8);
    console.log(`[${t}] [INFO] ${msg}`);
}

function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
}

function humanWait(minS = 2, maxS = 4) {
    return sleep((minS + Math.random() * (maxS - minS)) * 1000);
}

function timeToSeconds(t) {
    if (!t) return 0;
    const m = String(t).trim().match(/(\d{1,2}):(\d{2}):(\d{2})/);
    if (!m) return 0;
    return (+m[1]) * 3600 + (+m[2]) * 60 + (+m[3]);
}

async function sendTelegram(message) {
    if (!TG_TOKEN || !TG_CHAT_ID) {
        log('⚠️ 未配置 TG_TOKEN，跳过推送。');
        return;
    }
    try {
        const res = await fetch(`https://api.telegram.org/bot${TG_TOKEN}/sendMessage`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chat_id: TG_CHAT_ID, text: message }),
        });
        if (res.ok) log('✅ TG 推送已发送');
        else log(`❌ TG 推送失败: HTTP ${res.status}`);
    } catch (e) {
        log(`❌ TG 推送失败: ${e.message}`);
    }
}

// 读取 #sd-timer 剩余时间文本
async function getRemainingTime(page) {
    try {
        return await page.evaluate(() => {
            const el = document.querySelector('#sd-timer');
            return el ? el.innerText.trim() : '未知';
        });
    } catch (e) {
        return '未知';
    }
}

// 短路 RAMP 激励广告门槛：覆盖 manuallyCreateRewardUi 为立即 resolve
async function bypassRewardAd(page) {
    try {
        await page.evaluate(() => {
            window.ramp = window.ramp || {};
            if (!window.ramp.que || typeof window.ramp.que.push !== 'function') {
                window.ramp.que = { push: (f) => { try { f(); } catch (e) {} } };
            }
            window.ramp.manuallyCreateRewardUi = () => Promise.resolve();
            window.ramp.spaAddAds = window.ramp.spaAddAds || function () {};
        });
        log('🎟️ 已短路激励广告门槛（manuallyCreateRewardUi 立即放行）');
    } catch (e) {
        log(`⚠️ 激励广告短路注入失败: ${e.message}`);
    }
}

// 投票模态框是否打开
async function isVoteModalOpen(page) {
    try {
        return await page.evaluate(() => {
            const ov = document.querySelector('#vote-overlay');
            if (ov && (ov.classList.contains('open') || getComputedStyle(ov).display !== 'none')) return true;
            const m = document.querySelector('.vote-modal');
            return !!(m && getComputedStyle(m).display !== 'none' && m.offsetParent !== null);
        });
    } catch (e) {
        return false;
    }
}

async function waitForVoteModal(page, timeoutS = 25) {
    for (let i = 0; i < timeoutS; i++) {
        if (await isVoteModalOpen(page)) return true;
        await sleep(1000);
    }
    return false;
}

// 读取 Turnstile token（与页面提交逻辑 getResponse() 一致，隐藏字段兜底）
async function getTurnstileToken(page) {
    try {
        return await page.evaluate(() => {
            try {
                if (window.turnstile && typeof window.turnstile.getResponse === 'function') {
                    const r = window.turnstile.getResponse();
                    if (r && r.length > 20) return r;
                }
            } catch (e) {}
            const el = document.querySelector('[name="cf-turnstile-response"]');
            return el && el.value && el.value.length > 20 ? el.value : '';
        });
    } catch (e) {
        return '';
    }
}

// #vm-submit 是否已解禁（Turnstile callback 权威信号）
async function isSubmitEnabled(page) {
    try {
        return await page.evaluate(() => {
            const b = document.querySelector('#vm-submit');
            return b ? (!b.disabled && b.getAttribute('aria-disabled') !== 'true') : false;
        });
    } catch (e) {
        return false;
    }
}

// 等 Turnstile 被 puppeteer-real-browser 自动求解：轮询 submit 解禁 / token 非空
async function waitTurnstileSolved(page, timeoutS = 60) {
    log('📡 等待 puppeteer-real-browser 自动求解 Turnstile...');
    for (let i = 0; i < timeoutS; i++) {
        if (await isSubmitEnabled(page) || (await getTurnstileToken(page))) {
            const token = await getTurnstileToken(page);
            log(`✅ Turnstile 已通过（submit 解禁，token 长度 ${token.length}）`);
            return true;
        }
        if (i === 20) log('⏳ Turnstile 仍在求解中（可能出现 interactive checkbox，自动求解器处理中）...');
        await sleep(1500);
    }
    return false;
}

async function runSingleServer(num, region) {
    const url = `https://gaming4free.net/servers/${num}`;
    log('='.repeat(40));
    log(`🚀 开始续期 [${region}] (${num})`);

    const args = [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--window-size=1280,1200',
    ];
    if (PROXY_URL) args.push(`--proxy-server=${PROXY_URL}`);

    let browser, page;
    try {
        ({ browser, page } = await connect({
            headless: false,
            turnstile: true, // 自动求解 Cloudflare Turnstile
            disableXvfb: true, // 外层 workflow 已用 xvfb-run，避免嵌套冲突
            connectOption: { defaultViewport: null, executablePath: '/usr/bin/google-chrome' },
            args,
        }));
    } catch (e) {
        log(`❌ 浏览器启动失败: ${e.message}`);
        await sendTelegram(`❌ [${region}] 浏览器启动失败: ${e.message}\n🖥️ 编号: ${num}`);
        return;
    }

    try {
        log('✅ 浏览器已启动！');
        await page.setViewport({ width: 1280, height: 1200 });

        // 出口 IP
        try {
            await page.goto('https://api.ipify.org?format=json', { waitUntil: 'domcontentloaded', timeout: 30000 });
            const ip = await page.evaluate(() => {
                try { return JSON.parse(document.body.innerText).ip; } catch (e) { return 'Unknown'; }
            });
            const p = String(ip).split('.');
            if (p.length === 4) log(`✅ 当前出口 IP: ${p[0]}.${p[1]}.***.${p[3]}`);
        } catch (e) { /* 忽略 */ }

        log(`📂 正在进入续期面板 [${region}] ...`);
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
        await humanWait(6, 9);

        if (page.url().toLowerCase().includes('login')) {
            throw new Error('登录状态失效或权限被拒绝。');
        }

        // 关闭各类 Cookie 同意弹窗
        try {
            await page.evaluate(() => {
                const btns = Array.from(document.querySelectorAll('button, span, a'));
                const b = btns.find((el) => {
                    const t = (el.textContent || '').trim().toLowerCase();
                    return t === 'consent' || t === 'accept' || t === 'i agree' || t.includes('recommended cookies');
                });
                if (b) b.click();
            });
        } catch (e) { /* 忽略 */ }

        const timeBefore = await getRemainingTime(page);
        log(`🕒 续期前剩余运行时间: ${timeBefore}`);

        await page.evaluate(() => window.scrollBy(0, 800));
        await humanWait(2, 4);

        // 先短路激励广告门槛，再点 VOTE
        await bypassRewardAd(page);

        log("🖱️ 正在点击 'VOTE + ADD 90 MIN'...");
        try {
            await page.waitForSelector('#sd-vote-btn', { visible: true, timeout: 10000 });
            await page.click('#sd-vote-btn');
        } catch (e) {
            throw new Error(`未找到打开模态框的按钮: ${e.message}`);
        }

        if (!(await waitForVoteModal(page, 25))) {
            // 兜底：ramp 覆盖可能晚于点击，再补一次并尝试直接打开
            await bypassRewardAd(page);
            try { await page.evaluate(() => { if (typeof openVoteModal === 'function') openVoteModal(); }); } catch (e) {}
            if (!(await waitForVoteModal(page, 15))) {
                throw new Error('投票模态框未能打开（激励广告门槛未通过）。');
            }
        }
        log('✅ 投票模态框已打开');

        // 等 puppeteer-real-browser 自动求解 Turnstile（fail-closed：不过就不提交）
        if (!(await waitTurnstileSolved(page, 60))) {
            const diag = await page.evaluate(() => {
                const b = document.querySelector('#vm-submit');
                const el = document.querySelector('[name="cf-turnstile-response"]');
                return {
                    modalOpen: !!document.querySelector('#vote-overlay.open'),
                    hasIframe: !!document.querySelector('iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"]'),
                    submitDisabled: b ? !!b.disabled : null,
                    tokenLen: el && el.value ? el.value.length : 0,
                };
            });
            log(`🩺 验证失败诊断: ${JSON.stringify(diag)}`);
            try { await page.screenshot({ path: `artifacts/captcha_fail_${num}.png` }); } catch (e) {}
            throw new Error('Cloudflare Turnstile 验证失败：submit 始终未解禁且无有效 token，已终止提交。');
        }

        await humanWait(2, 4);

        log("🖱️ 正在点击最终提交按钮 'VOTE — ADDS 90 MINUTES'...");
        try {
            await page.waitForFunction(() => {
                const b = document.querySelector('#vm-submit');
                return b && !b.disabled;
            }, { timeout: 15000 });
            await page.click('#vm-submit');
        } catch (e) {
            throw new Error('未能点击最终的确认提交按钮。');
        }
        await humanWait(6, 9);

        // 用页面自身结果提示 #vm-msg 精确判定（成功带 'ok' class，失败带 'err'）
        let voteResult = null;
        for (let i = 0; i < 10; i++) {
            voteResult = await page.evaluate(() => {
                const m = document.querySelector('#vm-msg');
                if (!m) return null;
                const cls = (m.className || '').toLowerCase();
                const txt = (m.textContent || '').trim();
                if (cls.includes('ok')) return { ok: true, text: txt };
                if (cls.includes('err') || cls.includes('error')) return { ok: false, text: txt };
                if (txt && !['submitting…', 'submitting...'].includes(txt.toLowerCase())) return { pending: true, text: txt };
                return null;
            });
            if (voteResult && (voteResult.ok === true || voteResult.ok === false)) break;
            await sleep(1500);
        }

        if (voteResult && voteResult.ok === false) {
            throw new Error(`服务器拒绝了投票请求: ${voteResult.text}`);
        }

        await sleep(6000);

        const timeAfter = await getRemainingTime(page);
        log(`🕒 续期后剩余运行时间: ${timeAfter}`);

        const secBefore = timeToSeconds(timeBefore);
        const secAfter = timeToSeconds(timeAfter);
        const pageSaidOk = !!(voteResult && voteResult.ok === true);
        const timeIncreased = secAfter > 0 && secBefore > 0 && secAfter > secBefore + 120;

        if (!pageSaidOk && !timeIncreased) {
            const detail = voteResult ? voteResult.text : '无页面提示';
            throw new Error(`时间未增加且未收到成功提示（${detail}）。人机验证或广告校验可能未通过。`);
        }
        if (pageSaidOk) log(`✅ 页面确认投票成功: ${voteResult.text}`);

        try { await page.screenshot({ path: `artifacts/final_success_${num}.png` }); } catch (e) {}

        await sendTelegram(
            `✅ [${region}] 续期成功\n🖥️ 编号: ${num}\n🕒 续期前剩余时间: ${timeBefore}\n🎉 续期后剩余时间: ${timeAfter}`
        );
    } catch (e) {
        log(`❌ 运行异常: ${e.message}`);
        try { await page.screenshot({ path: `artifacts/error_${num}.png` }); } catch (err) {}
        await sendTelegram(`❌ [${region}] 执行失败: ${e.message}\n🖥️ 编号: ${num}`);
    } finally {
        try { await browser.close(); } catch (e) {}
    }
}

async function main() {
    if (!SERVER_LIST.length) {
        log('❌ 未配置 SERVERS');
        return;
    }
    // 确保截图目录存在
    try { require('fs').mkdirSync('artifacts', { recursive: true }); } catch (e) {}

    for (const s of SERVER_LIST) {
        await runSingleServer(s.num, s.region);
    }
}

main();
