"""
大麦网抢票逻辑分析 - 教育性研究示例
=====================================

【重要声明】
1. 本代码仅用于技术学习和研究目的
2. 使用自动化工具抢票可能违反大麦网《用户服务协议》
3. 使用本代码产生的一切后果由使用者自行承担
4. 请尊重公平购票秩序，理性消费

【大麦网购票完整流程分析】
基于实际页面DOM结构分析，大麦网的购票流程如下：

阶段1：进入演出详情页
  URL格式: https://detail.damai.cn/item.htm?id=演出ID
  关键元素:
    - 演出主容器: .perform
    - 订单选择区: .perform__order__box

阶段2：选择演出日期（如有）
  选择器: .wh_item_date
  注意:
    - 可点击日期带有 cursor-pointer 类
    - 不可售日期有 wh_other_dayhide 或 disabled 类
    - 需要选择有效的可售日期

阶段3：选择场次
  选择器: .perform__order__select__performs .select_right_list_item
  注意:
    - 场场次元素通常包含日期+时间，如 "2026-08-22 周六 13:30"
    - 当前选中的场次带有 active 类
    - 需遍历查找目标场次并点击

阶段4：选择票档（价格档位）
  选择器: .select_right_list_item.sku_item .skuname
  常见票档格式:
    - "婴儿票（不占座）29.9"
    - "后区观剧单人88元"
    - "前区互动双人468元"
    - "中区体验三人488元"
  注意: 需要精确匹配票档文本

阶段5：选择购票数量
  减少按钮: .cafe-c-input-number-handler-down
  增加按钮: .cafe-c-input-number-handler-up
  输入框: .cafe-c-input-number-input
  注意:
    - 默认数量通常为1
    - 每笔订单有限购张数（如限购6张）

阶段6：点击立即购票
  【关键】大麦网通常会优先引导使用APP扫码:
    - 提示区域: .scan-buy
    - "手机扫码购买更便捷" 提示
    - 绕过按钮: .buy-link (文本: "不，立即购票")
  
  点击后会进入:
    a. 登录流程（如未登录）
    b. 实名认证/观演人选择
    c. 订单确认页
    d. 支付页（目标：到达付款界面）

【大麦网的反爬/防抢票机制】
1. 登录验证（需账号登录，支持手机验证码/密码）
2. 滑块验证码（行为验证）
3. 实名认证（需身份证信息）
4. 观演人信息（实名购票，一证一票）
5. 频率限制（过快的请求会被限制）
6. 设备指纹检测（浏览器特征、Cookie等）
7. 热门演出的"缺货登记"或"立即预订"状态切换

作者: 技术研究示例
"""

import time
import random
import logging
from dataclasses import dataclass, field
from typing import Optional, List

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


@dataclass
class TicketConfig:
    """抢票配置类 - 用户需要填写的信息"""
    # 目标演出ID (从详情页URL获取，如 item.htm?id=xxxxx)
    item_id: str = ""
    
    # 目标场次关键词（匹配场次文本，如 "2026-08-22" 或 "周六 13:30"）
    session_keyword: str = ""
    
    # 目标票档关键词（匹配票档文本，如 "中区体验双人" 或 "88元"）
    ticket_keyword: str = ""
    
    # 购票数量
    quantity: int = 1
    
    # 大麦网账号（需要提前注册并实名认证）
    username: str = ""
    password: str = ""
    
    # 观演人姓名和身份证号（实名制购票需要）
    viewers: List[dict] = field(default_factory=list)
    # 示例: viewers = [{"name": "张三", "id_card": "110101xxxxxx"}]
    
    # 抢票开始时间（格式: "2026-08-20 12:00:00"，None表示立即开始）
    start_time: Optional[str] = None
    
    # 最大重试次数
    max_retry: int = 50

    # 请求间隔（秒）- 太快容易被封
    request_interval: float = 0.5

    # 是否显示浏览器界面（调试时True，无人值守时False）
    show_browser: bool = True

    # ===== 极速模式（比手速快的关键） =====
    # 极速模式：开售前预热页面+预选项，开售瞬间JS注入直接点击
    fast_mode: bool = True
    # 开售前多少秒开始预热页面（提前打开并选好场次票档）
    warmup_seconds: int = 60
    # 极速模式下的轮询间隔（秒），比人手速快得多
    fast_poll_interval: float = 0.05


class DamaiTicketBot:
    """
    大麦网抢票机器人 - 教育性研究示例
    
    核心思路:
    1. 使用Selenium模拟真实用户操作（而非纯HTTP请求，避免被检测）
    2. 提前登录，保存Cookie，避免重复登录
    3. 准点监控开票状态，一旦可售立即执行选座/购票流程
    4. 快速完成日期→场次→票档→数量→购票的完整流程
    """
    
    def __init__(self, config: TicketConfig):
        self.config = config
        self.driver = None  # Selenium WebDriver实例
        self.base_url = "https://detail.damai.cn/item.htm"

        # GUI集成支持
        self.stop_requested = False       # 停止信号（GUI点击停止时设为True）
        self.log_callback = None          # 日志回调函数（GUI用于显示日志）
        self.login_callback = None        # 登录回调（GUI用于处理手动登录等待）
        self.on_success_callback = None   # 成功回调（GUI通知用户）
        
        # CSS选择器常量（基于实际DOM分析）
        self.SELECTORS = {
            # 日期选择
            "date_item": ".wh_item_date",
            "date_available": ".wh_item_date.cursor-pointer:not(.wh_other_dayhide)",
            
            # 场次选择
            "session_list": ".perform__order__select__performs",
            "session_item": ".select_right_list_item",
            "session_active": ".select_right_list_item.active",
            
            # 票档选择
            "sku_list": ".perform__order__select__tickets",
            "sku_item": ".select_right_list_item.sku_item",
            "sku_name": ".skuname",
            "sku_active": ".sku_item.active",
            
            # 数量控制
            "qty_input": ".cafe-c-input-number-input",
            "qty_minus": ".cafe-c-input-number-handler-down",
            "qty_plus": ".cafe-c-input-number-handler-up",
            
            # 立即购票按钮
            "scan_buy_prompt": ".scan-buy",
            "bypass_app_buy": ".buy-link",  # "不，立即购票"
            
            # 登录相关
            "login_btn": ".login-btn, [class*='login']",
            "login_tab_pwd": ".password-login-tab",
            
            # 观演人选择
            "viewer_list": ".viewer-list, [class*='audience']",
            "viewer_item": ".viewer-item, [class*='audience-item']",
            "viewer_confirm": ".confirm-viewer, [class*='confirm']",
            
            # 订单确认/提交
            "order_confirm": ".order-confirm, .confirm-order, .submit-order",
            "checkout_btn": ".checkout, .pay-btn, [class*='payment']",
        }
    
    def _init_driver(self):
        """初始化Selenium浏览器驱动"""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
        except ImportError:
            logger.error("请先安装依赖: pip install selenium webdriver-manager")
            raise
        
        options = Options()

        # ============ 极速加载配置 ============
        # eager: DOM就绪即返回，不等图片/广告等资源加载完（抢票时快数百毫秒~数秒）
        options.page_load_strategy = 'eager'

        # ============ 反检测配置 ============
        # 禁用自动化标识
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # 设置真实User-Agent
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        # 禁用一些可能被检测的特性
        options.add_argument('--disable-blink-features=AutomationControlled')
        
        if not self.config.show_browser:
            options.add_argument('--headless')  # 无头模式
        
        options.add_argument('--window-size=1440,900')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        
        # 使用webdriver-manager自动管理驱动
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
        except Exception:
            # 回退到系统已有驱动
            self.driver = webdriver.Chrome(options=options)
        
        # 执行JS移除webdriver标识
        self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.navigator.chrome = {
                    runtime: {},
                    loadTimes: function() {},
                    csi: function() {},
                    app: {}
                };
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['zh-CN', 'zh', 'en']
                });
            '''
        })
        
        # 设置页面加载超时
        self.driver.set_page_load_timeout(30)
        self.driver.implicitly_wait(5)
        logger.info("浏览器驱动初始化完成")
    
    def _random_sleep(self, min_sec=0.3, max_sec=1.0):
        """随机等待，模拟人类操作间隔"""
        time.sleep(random.uniform(min_sec, max_sec))
    
    def _safe_click(self, css_selector: str, timeout: int = 10) -> bool:
        """安全点击元素，带重试"""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException
        
        for attempt in range(3):
            try:
                element = WebDriverWait(self.driver, timeout).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, css_selector))
                )
                # 滚动到可视区域
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                self._random_sleep(0.2, 0.5)
                element.click()
                return True
            except (TimeoutException, ElementClickInterceptedException) as e:
                logger.warning(f"点击 {css_selector} 失败，第{attempt+1}次重试: {e}")
                self._random_sleep(0.5, 1.0)
            except Exception as e:
                logger.error(f"点击 {css_selector} 异常: {e}")
                break
        return False
    
    def _safe_find_text_click(self, parent_css: str, keyword: str, timeout: int = 10) -> bool:
        """在父元素下查找包含关键词的子元素并点击"""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, parent_css))
            )
            parent = self.driver.find_element(By.CSS_SELECTOR, parent_css)
            items = parent.find_elements(By.CSS_SELECTOR, self.SELECTORS["session_item"] if "performs" in parent_css else self.SELECTORS["sku_item"])
            
            for item in items:
                text = item.text.strip()
                if keyword and keyword in text:
                    logger.info(f"匹配到目标: {text[:50]}")
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", item)
                    self._random_sleep(0.2, 0.4)
                    item.click()
                    return True
            
            # 如果没找到关键词，选第一个可用的（非disabled）
            for item in items:
                try:
                    if "disabled" not in item.get_attribute("class"):
                        text = item.text.strip()
                        logger.info(f"关键词未匹配，选择首个可用: {text[:50]}")
                        item.click()
                        return True
                except:
                    continue
                    
            logger.warning(f"未找到可用的选项 (关键词: {keyword})")
            return False
        except Exception as e:
            logger.error(f"查找并点击失败: {e}")
            return False
    
    def _set_quantity(self, target_qty: int):
        """设置购票数量"""
        from selenium.webdriver.common.by import By
        
        try:
            input_el = self.driver.find_element(By.CSS_SELECTOR, self.SELECTORS["qty_input"])
            current_qty = int(input_el.get_attribute("value") or "1")
            diff = target_qty - current_qty
            
            if diff > 0:
                for _ in range(diff):
                    self._safe_click(self.SELECTORS["qty_plus"])
                    self._random_sleep(0.1, 0.2)
            elif diff < 0:
                for _ in range(-diff):
                    self._safe_click(self.SELECTORS["qty_minus"])
                    self._random_sleep(0.1, 0.2)
            
            logger.info(f"数量设置完成: {target_qty}张")
            return True
        except Exception as e:
            logger.error(f"设置数量失败: {e}")
            return False
    
    def _wait_until_start_time(self):
        """等待到开票时间（如果配置了的话）"""
        if not self.config.start_time:
            return
        
        import datetime
        target_time = datetime.datetime.strptime(self.config.start_time, "%Y-%m-%d %H:%M:%S")
        
        logger.info(f"等待开票时间: {self.config.start_time}")
        while True:
            now = datetime.datetime.now()
            remaining = (target_time - now).total_seconds()
            
            if remaining <= 0:
                logger.info("开票时间已到，开始抢票！")
                break
            
            # 最后30秒每秒刷新，提前1秒准备
            if remaining > 30:
                logger.info(f"距开票还有 {remaining:.0f} 秒")
                time.sleep(min(remaining - 5, 10))  # 每10秒或更短检查一次
            elif remaining > 1:
                time.sleep(0.5)  # 最后阶段快速刷新
            else:
                time.sleep(0.1)  # 最后0.x秒
    
    def stop(self):
        """请求停止机器人（由GUI调用）"""
        self.stop_requested = True
        logger.info("收到停止信号，正在安全停止...")

    # ============================================================
    # 极速模式核心（比手速快的关键实现）
    # 原理：
    #   1. 开售前提前打开详情页（页面已渲染、CSS/JS已缓存、连接已建立）
    #   2. 提前选好日期/场次/票档/数量（开售时页面结构不变，选项依然有效）
    #   3. 开售瞬间用JS注入 element.click() 直接触发点击事件
    #      —— 比Selenium原生click()快（跳过鼠标移动合成、可点击性检查）
    #      —— 比人手速快（无寻找元素/移动鼠标/犹豫的耗时）
    # ============================================================

    def _js_click(self, element):
        """用JS直接触发点击事件（最快，跳过Selenium动作链）"""
        try:
            self.driver.execute_script("arguments[0].click();", element)
            return True
        except Exception as e:
            logger.debug(f"JS点击失败: {e}")
            return False

    def _preselect_options(self) -> bool:
        """
        预热阶段：提前选好日期/场次/票档/数量
        开售前这些选项通常已可交互（或选完保留），开售后无需再选
        """
        logger.info("[预热] 提前选择日期/场次/票档/数量...")
        ok = True

        # 日期（如有日历）
        try:
            from selenium.webdriver.common.by import By
            dates = self.driver.find_elements(By.CSS_SELECTOR, self.SELECTORS["date_available"])
            for d in dates:
                if d.text.strip():
                    self._js_click(d)
                    time.sleep(0.2)
                    logger.info(f"[预热] 已选日期: {d.text.strip()}")
                    break
        except Exception:
            pass

        # 场次
        if not self._safe_find_text_click(self.SELECTORS["session_list"], self.config.session_keyword):
            logger.warning("[预热] 场次预选失败")
            ok = False

        # 票档
        if not self._safe_find_text_click(".perform__order__box", self.config.ticket_keyword):
            logger.warning("[预热] 票档预选失败")
            ok = False

        # 数量
        self._set_quantity(self.config.quantity)
        logger.info("[预热] 预选完成，等待开售...")
        return ok

    def _fast_wait_and_buy(self):
        """
        极速模式：高频轮询购票按钮，一旦可点立即JS点击
        这是"比正常人快"的核心——50ms级轮询+瞬时JS点击
        """
        from selenium.webdriver.common.by import By
        import datetime

        # 等待开售
        if self.config.start_time:
            target = datetime.datetime.strptime(self.config.start_time, "%Y-%m-%d %H:%M:%S")
            while not self.stop_requested:
                remaining = (target - datetime.datetime.now()).total_seconds()
                if remaining <= 0:
                    break
                if remaining > 10:
                    logger.info(f"距开售 {remaining:.0f} 秒")
                    time.sleep(min(remaining - 5, 10))
                else:
                    time.sleep(0.05)  # 最后10秒高精度等待

        if self.stop_requested:
            return False

        logger.info("开售！开始极速点击购票...")

        buy_js = """
            // 在页面上下文中直接查找并点击购票按钮（毫秒级）
            const candidates = [
                ...document.querySelectorAll('.buy-link'),           // "不，立即购票"
                ...document.querySelectorAll('[class*="buy"]'),
                ...document.querySelectorAll('[class*="submit"]'),
                ...document.querySelectorAll('[class*="confirm"]')
            ];
            for (const el of candidates) {
                const t = (el.textContent || '').trim();
                if (/立即购票|立即预订|提交|确定/.test(t)) {
                    el.click();
                    return t;
                }
            }
            return null;
        """

        clicked = False
        attempt = 0
        while not clicked and not self.stop_requested and attempt < self.config.max_retry:
            attempt += 1
            try:
                result = self.driver.execute_script(buy_js)
                if result:
                    logger.info(f"[极速] 已点击: {result}")
                    clicked = True
                    break
                # 按钮还没出现（未开售），高频轮询
                time.sleep(self.config.fast_poll_interval)
                # 每隔一段时间刷新页面（防止页面状态过期）
                if attempt % 200 == 0:
                    logger.info("[极速] 按钮未出现，刷新页面重试...")
                    self.driver.refresh()
                    time.sleep(1)
                    # 刷新后需要重新预选
                    self._preselect_options()
            except Exception as e:
                logger.debug(f"[极速] 轮询异常: {e}")
                time.sleep(self.config.fast_poll_interval)

        if not clicked:
            return False

        # 点击成功后处理后续（观演人/订单确认）
        time.sleep(1)
        self._select_viewers_if_needed()

        confirm_js = """
            const btns = document.querySelectorAll('[class*="confirm"], [class*="submit"], button');
            for (const b of btns) {
                const t = (b.textContent || '').trim();
                if (/提交订单|确认订单|同意以上规则/.test(t)) {
                    b.click();
                    return t;
                }
            }
            return null;
        """
        try:
            r = self.driver.execute_script(confirm_js)
            if r:
                logger.info(f"[极速] 已确认订单: {r}")
        except Exception:
            pass

        # 检测是否到达支付页
        time.sleep(2)
        url = self.driver.current_url.lower()
        if any(k in url for k in ["pay", "checkout", "trade", "order"]):
            logger.info("=" * 50)
            logger.info("✅ 极速模式：已进入付款页面！")
            logger.info("=" * 50)
            if self.on_success_callback:
                self.on_success_callback()
            return True
        return None

    def login(self):
        """
        登录大麦网
        【说明】实际登录需要：
        1. 手动扫码登录（推荐，最稳定）
        2. 手机验证码登录
        3. 账号密码登录（可能需验证码）
        这里采用【用户手动登录+保存Cookie】的方案
        """
        logger.info("请在浏览器中手动登录大麦网...")
        self.driver.get("https://www.damai.cn/")
        self._random_sleep(2, 3)

        # 尝试点击登录按钮
        login_selectors = [".login", "[class*='login']", "#login"]
        for sel in login_selectors:
            try:
                self._safe_click(sel, timeout=3)
                break
            except:
                continue

        # 等待用户完成登录
        logger.info("=" * 50)
        logger.info("请在浏览器中完成登录操作（扫码/验证码/密码登录）")
        logger.info("=" * 50)

        # GUI模式下使用回调等待，命令行模式下使用input
        if self.login_callback:
            self.login_callback()  # GUI会阻塞此调用直到用户确认登录完成
        else:
            input("登录完成后，按回车键继续...")

        # 保存Cookie（下次可免登录）
        import json
        cookies = self.driver.get_cookies()
        with open("damai_cookies.json", "w") as f:
            json.dump(cookies, f)
        logger.info("登录成功，Cookie已保存到 damai_cookies.json")
    
    def load_cookies(self):
        """加载已保存的Cookie"""
        import json
        import os
        
        cookie_file = "damai_cookies.json"
        if not os.path.exists(cookie_file):
            return False
        
        try:
            self.driver.get("https://www.damai.cn/")
            with open(cookie_file, "r") as f:
                cookies = json.load(f)
            for cookie in cookies:
                # 过滤掉不合法的cookie属性
                if "sameSite" in cookie:
                    del cookie["sameSite"]
                try:
                    self.driver.add_cookie(cookie)
                except:
                    pass
            logger.info("Cookie加载成功")
            return True
        except Exception as e:
            logger.warning(f"加载Cookie失败: {e}")
            return False
    
    def go_to_item_page(self):
        """跳转到目标演出详情页"""
        url = f"{self.base_url}?id={self.config.item_id}"
        logger.info(f"打开演出详情页: {url}")
        self.driver.get(url)
        self._random_sleep(2, 4)
    
    def _bypass_app_prompt(self):
        """绕过APP扫码提示，点击'不，立即购票'"""
        try:
            # 检测是否出现引导使用APP的提示
            buy_link = self.SELECTORS["bypass_app_buy"]
            from selenium.webdriver.common.by import By
            elements = self.driver.find_elements(By.CSS_SELECTOR, buy_link)
            if elements and elements[0].is_displayed():
                logger.info("检测到APP引导提示，点击'不，立即购票'")
                self._safe_click(buy_link, timeout=5)
                self._random_sleep(1, 2)
                return True
        except Exception as e:
            logger.debug(f"无需绕过APP提示: {e}")
        return False
    
    def run_ticket_flow(self) -> bool:
        """
        执行完整的抢票流程（核心逻辑）
        返回: 是否成功进入付款页面
        """
        logger.info("=" * 50)
        logger.info("开始执行抢票流程")
        logger.info("=" * 50)
        
        # 步骤1: 选择日期（如果有日期选择器）
        logger.info("[步骤1] 检查日期选择...")
        try:
            from selenium.webdriver.common.by import By
            date_items = self.driver.find_elements(By.CSS_SELECTOR, self.SELECTORS["date_available"])
            if date_items:
                # 选择第一个可售日期，或匹配特定日期
                clicked = False
                for date_el in date_items:
                    try:
                        date_el.click()
                        self._random_sleep(0.5, 1)
                        clicked = True
                        logger.info(f"已选择日期: {date_el.text.strip()}")
                        break
                    except:
                        continue
                if not clicked:
                    logger.warning("日期选择失败，继续下一步")
            else:
                logger.info("无需选择日期，或日期已默认选中")
        except Exception as e:
            logger.warning(f"日期选择异常: {e}")
        
        # 步骤2: 选择场次
        logger.info("[步骤2] 选择场次...")
        ok = self._safe_find_text_click(
            self.SELECTORS["session_list"],
            self.config.session_keyword
        )
        if not ok:
            logger.warning("场次选择可能失败，继续尝试")
        self._random_sleep(0.5, 1)
        
        # 步骤3: 选择票档
        logger.info("[步骤3] 选择票档...")
        ok = self._safe_find_text_click(
            self.SELECTORS["sku_list"] if False else ".perform__order__box",
            self.config.ticket_keyword
        )
        if not ok:
            logger.error("票档选择失败！")
            return False
        self._random_sleep(0.5, 1)
        
        # 步骤4: 设置数量
        logger.info("[步骤4] 设置购票数量...")
        self._set_quantity(self.config.quantity)
        self._random_sleep(0.3, 0.6)
        
        # 步骤5: 绕过APP提示 + 点击立即购票
        logger.info("[步骤5] 点击立即购票...")
        self._bypass_app_prompt()
        
        # 尝试多种"立即购票"按钮选择器
        buy_selectors = [
            self.SELECTORS["bypass_app_buy"],
            ".buy-btn",
            ".buy-now",
            "[class*='buy']:not(.buy-link)",
            "#buyNow",
            ".perform__order__buy",
            ".order__buy",
            "button.btn-buy",
        ]
        
        buy_clicked = False
        for sel in buy_selectors:
            if self._safe_click(sel, timeout=3):
                logger.info(f"点击购票按钮成功: {sel}")
                buy_clicked = True
                break
        
        if not buy_clicked:
            logger.error("未找到可点击的购票按钮！")
            return False
        
        # 等待页面跳转（登录/观演人/订单确认）
        self._random_sleep(2, 4)
        logger.info("等待页面跳转...")
        
        # 步骤6: 选择观演人（如果出现）
        logger.info("[步骤6] 检查观演人选择...")
        self._select_viewers_if_needed()
        self._random_sleep(1, 2)
        
        # 步骤7: 确认订单
        logger.info("[步骤7] 确认订单...")
        confirm_selectors = [
            self.SELECTORS["order_confirm"],
            ".submit-order-btn",
            ".btn-submit-order",
            "#submitOrder",
            "[class*='order'] [class*='confirm']",
            "[class*='order'] [class*='submit']",
        ]
        
        for sel in confirm_selectors:
            try:
                self._safe_click(sel, timeout=3)
                logger.info(f"尝试确认订单: {sel}")
                self._random_sleep(1, 2)
            except:
                continue
        
        # 检查是否到达支付页面
        current_url = self.driver.current_url
        logger.info(f"当前页面URL: {current_url}")
        
        # 检查URL或页面标题是否包含支付相关关键词
        if any(key in current_url.lower() for key in ["pay", "payment", "checkout", "order/confirm", "trade"]):
            logger.info("=" * 50)
            logger.info("✅ 成功进入付款页面！")
            logger.info("=" * 50)
            return True
        else:
            # 检查页面是否有支付按钮
            try:
                from selenium.webdriver.common.by import By
                pay_btns = self.driver.find_elements(By.CSS_SELECTOR, ".pay-btn, [class*='alipay'], [class*='wechat']")
                if pay_btns:
                    logger.info("✅ 检测到支付选项，已进入付款流程！")
                    return True
            except:
                pass
            
            logger.warning("当前页面可能未到达付款页，请手动检查")
            return None  # 不确定状态
    
    def _select_viewers_if_needed(self):
        """选择观演人（如果页面出现观演人选择）"""
        from selenium.webdriver.common.by import By
        
        viewer_selectors = [
            self.SELECTORS["viewer_list"],
            "[class*='audience']",
            "[class*='realname']",
            "[class*='viewer']",
        ]
        
        list_found = None
        for sel in viewer_selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, sel)
                if elements:
                    list_found = elements[0]
                    break
            except:
                continue
        
        if not list_found:
            logger.info("未出现观演人选择，跳过")
            return
        
        logger.info("检测到观演人选择界面...")
        
        # 尝试点击已有的观演人选项（需要提前在账号中添加好）
        try:
            viewer_items = list_found.find_elements(By.CSS_SELECTOR, self.SELECTORS["viewer_item"])
            if not viewer_items:
                viewer_items = list_found.find_elements(By.CSS_SELECTOR, "li, .item, [class*='item']")
            
            selected_count = 0
            target_count = self.config.quantity
            
            for item in viewer_items:
                if selected_count >= target_count:
                    break
                try:
                    if "disabled" not in item.get_attribute("class"):
                        item.click()
                        selected_count += 1
                        self._random_sleep(0.2, 0.4)
                except:
                    continue
            
            logger.info(f"已选择 {selected_count} 个观演人")
            
            # 点击确认按钮
            for sel in [self.SELECTORS["viewer_confirm"], ".btn-confirm", ".confirm", "button.confirm"]:
                if self._safe_click(sel, timeout=3):
                    break
        except Exception as e:
            logger.warning(f"观演人选择异常（可能需要手动处理）: {e}")
    
    def run(self):
        """机器人主入口（根据fast_mode自动选择极速/普通模式）"""
        try:
            # 1. 初始化浏览器
            self._init_driver()

            # 2. 加载Cookie或登录
            if not self.load_cookies():
                self.login()

            if self.stop_requested:
                logger.info("已在登录阶段停止")
                return

            # ===== 极速模式：预热 + 瞬时点击 =====
            if self.config.fast_mode:
                logger.info(f"⚡ 极速模式启动（开售前{self.config.warmup_seconds}秒预热页面）")
                import datetime
                # 计算预热时间（开售前N秒）
                if self.config.start_time:
                    target = datetime.datetime.strptime(self.config.start_time, "%Y-%m-%d %H:%M:%S")
                    warmup_at = target - datetime.timedelta(seconds=self.config.warmup_seconds)
                    while not self.stop_requested:
                        now = datetime.datetime.now()
                        if now >= warmup_at:
                            break
                        remaining = (warmup_at - now).total_seconds()
                        logger.info(f"等待预热时间，还有 {remaining:.0f} 秒")
                        time.sleep(min(remaining, 10))

                if self.stop_requested:
                    return

                # 预热：提前打开页面并预选项
                self.go_to_item_page()
                self._preselect_options()

                # 极速等待开售并点击
                result = self._fast_wait_and_buy()
                if result is True:
                    logger.info("\\n🎉 极速抢票成功！已进入付款界面，请尽快完成支付。")
                elif result is None:
                    logger.info("已到达订单相关页面，请在浏览器中确认并手动支付")
                else:
                    logger.warning("极速模式未能进入付款页")
                return

            # ===== 普通模式（逐次重试完整流程） =====
            # 3. 等待开票时间
            self._wait_until_start_time()

            if self.stop_requested:
                logger.info("已在等待阶段停止")
                return

            # 4. 打开目标页面并重试
            success = False
            for attempt in range(1, self.config.max_retry + 1):
                if self.stop_requested:
                    logger.info("用户已请求停止，退出重试循环")
                    break

                logger.info(f"\\n----- 第 {attempt}/{self.config.max_retry} 次尝试 -----")

                try:
                    self.go_to_item_page()
                    result = self.run_ticket_flow()

                    if result is True:
                        success = True
                        logger.info("\\n🎉 抢票成功！已进入付款界面，请尽快完成支付。")
                        logger.info(f"当前页面URL: {self.driver.current_url}")
                        if self.on_success_callback:
                            self.on_success_callback()
                        break
                    elif result is None:
                        # 不确定状态，让用户判断
                        logger.info("已到达订单相关页面，请在浏览器中检查并手动操作")
                        break
                    else:
                        logger.info("本次尝试未成功，刷新重试...")

                except Exception as e:
                    logger.error(f"第{attempt}次尝试异常: {e}")

                # 重试间隔（前几次快，后几次慢）
                interval = self.config.request_interval
                if attempt > 20:
                    interval *= 2  # 后期减速，防止被封
                time.sleep(interval)

            if not success and not self.stop_requested:
                logger.warning(f"已达最大重试次数 ({self.config.max_retry})，本次抢票结束")

        except KeyboardInterrupt:
            logger.info("用户中断")
        except Exception as e:
            logger.exception(f"运行异常: {e}")
        finally:
            if self.driver and self.stop_requested:
                logger.info("关闭浏览器...")
                try:
                    self.driver.quit()
                except:
                    pass


# ============================================================
# 使用示例
# ============================================================
def main():
    """
    使用步骤：
    1. 安装依赖: pip install selenium webdriver-manager
    2. 填写下方的配置信息
    3. 首次运行会提示手动登录，登录后Cookie会保存
    4. 后续运行可自动加载Cookie
    """
    
    config = TicketConfig(
        # ===== 必填项 =====
        item_id="1068684284719",        # 演出ID（从URL item.htm?id=xxx 获取）
        session_keyword="13:30",        # 场次关键词（模糊匹配，如"周六 13:30"）
        ticket_keyword="88元",          # 票档关键词（模糊匹配，如"后区观剧单人88元"）
        quantity=1,                     # 购票数量
        
        # ===== 定时抢票（可选）=====
        # start_time="2026-08-20 12:00:00",  # 开票时间，None表示立即开始
        start_time=None,
        
        # ===== 调优参数 =====
        max_retry=30,                    # 最大重试次数
        request_interval=0.5,            # 每次重试间隔秒数
        show_browser=True,               # 是否显示浏览器窗口
    )
    
    # 启动机器人
    bot = DamaiTicketBot(config)
    bot.run()


if __name__ == "__main__":
    main()
