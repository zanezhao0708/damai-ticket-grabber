#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真实环境测试脚本（受限沙箱，非用户日常使用）
测试大麦网实际抢票流程能走多远 + 计时找瓶颈
"""
import os
import time
import logging

os.environ["DAMAI_CHROME_BINARY"] = "/opt/chrome-headless/chrome-headless-shell"
os.environ["DAMAI_CHROMEDRIVER_PATH"] = "/usr/local/bin/chromedriver"

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')

from damai_ticket_study import TicketConfig, DamaiTicketBot

# 真实在售演出（从之前分析的页面来，儿童亲子剧，有"不，立即购票"入口）
ITEM_ID = "1068684284719"

config = TicketConfig(
    item_id=ITEM_ID,
    session_keyword="",          # 自动选第一场
    ticket_keyword="元",         # 任意票档（关键词"元"能匹配到价格文本）
    quantity=1,
    start_time=None,             # 不等待，立即执行
    fast_mode=True,
    show_browser=False,          # 沙箱无显示，强制无头
    max_retry=3,
)

bot = DamaiTicketBot(config)
# 登录回调设为立即返回（沙箱无法真人登录，验证不挂起即可）
bot.login_callback = lambda: print("[测试] 登录墙回调触发（沙箱无人登录，立即返回）")

# 记录关键阶段耗时
t0 = time.time()
phases = {}

def mark(name):
    phases[name] = round(time.time() - t0, 2)
    print(f"[TIMER] {name}: {phases[name]}s")

try:
    bot._init_driver()
    mark("浏览器启动")

    bot.go_to_item_page()
    mark("打开详情页")

    # 检查页面真实状态
    url = bot.driver.current_url
    title = bot.driver.title
    print(f"[真实页面] URL: {url}")
    print(f"[真实页面] 标题: {title}")

    # 检查关键元素是否存在（逐个计时）
    from selenium.webdriver.common.by import By

    for name, sel in [
        ("日期元素", bot.SELECTORS.get("date_available", ".wh_item_date")),
        ("场次列表", ".perform__order__select__performs .select_right_list_item"),
        ("票档区域", ".perform__order__box"),
        ("APP引导弹层", ".scan-buy"),
        ("网页购票入口", ".buy-link"),
    ]:
        try:
            els = bot.driver.find_elements(By.CSS_SELECTOR, sel)
            print(f"[元素检查] {name} ({sel}): {len(els)} 个")
        except Exception as e:
            print(f"[元素检查] {name}: 异常 {e}")

    # 尝试预热预选
    bot._preselect_options()
    mark("预热预选")

    # 尝试极速点击（真实执行，看能走到哪一步）
    result = bot._fast_wait_and_buy()
    mark("极速点击流程")
    print(f"[结果] _fast_wait_and_buy 返回: {result}")
    print(f"[结果] 最终URL: {bot.driver.current_url}")

    # 截图留证
    try:
        bot.driver.save_screenshot("/tmp/damai_final.png")
        print("[截图] 已保存 /tmp/damai_final.png")
    except Exception as e:
        print(f"[截图] 失败: {e}")

except Exception as e:
    print(f"[异常] {type(e).__name__}: {str(e)[:500]}")
    import traceback
    traceback.print_exc()
finally:
    try:
        bot.driver.quit()
    except Exception:
        pass

print()
print("========== 各阶段耗时 ==========")
for k, v in phases.items():
    print(f"  {k}: {v}s")
