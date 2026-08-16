#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大麦网抢票工具 - Web版
======================

【运行方式】
    pip install -r requirements.txt
    python app.py
    浏览器打开 http://localhost:8787

【重要声明】
仅限个人学习研究使用，不用于任何盈利活动。
使用自动化工具可能违反大麦网《用户服务协议》，风险自担。
"""

import os
import sys
import threading
import logging

from flask import Flask, render_template, request, jsonify

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from damai_ticket_study import TicketConfig, DamaiTicketBot, logger as core_logger

app = Flask(__name__)

# ============================================================
# 全局状态
# ============================================================
_state_lock = threading.Lock()
_logs = []            # [{'id':int, 'time':str, 'level':str, 'msg':str}]
_log_seq = 0

bot = None
bot_thread = None
running = False
waiting_login = False
login_event = threading.Event()
success_flag = {"hit": False}


def append_log(msg: str, level: str = "INFO"):
    """线程安全地追加日志（供Web界面轮询）"""
    global _log_seq
    import datetime
    with _state_lock:
        _log_seq += 1
        _logs.append({
            "id": _log_seq,
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "msg": msg,
        })
        # 只保留最近500条，防止内存膨胀
        if len(_logs) > 500:
            del _logs[:len(_logs) - 500]


class WebLogHandler(logging.Handler):
    """把核心模块的logging日志转发到Web界面"""
    def __init__(self):
        super().__init__()
        self.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))

    def emit(self, record):
        try:
            append_log(self.format(record), record.levelname)
        except Exception:
            pass


# 挂载Web日志Handler
core_logger.addHandler(WebLogHandler())


# ============================================================
# 机器人生命周期
# ============================================================
def _run_bot():
    """后台线程：运行抢票机器人"""
    global running
    try:
        bot.run()
    except Exception as e:
        append_log(f"运行异常: {e}", "ERROR")
    finally:
        with _state_lock:
            running = False
        append_log("===== 任务结束 =====")


def _web_login_wait():
    """登录回调：标记等待登录状态，等前端确认"""
    global waiting_login
    with _state_lock:
        waiting_login = True
    append_log("=" * 46, "WARNING")
    append_log("请在弹出的浏览器窗口中完成登录（扫码/验证码）", "WARNING")
    append_log("登录完成后，点击网页上的「✓ 我已登录完成」按钮", "WARNING")
    append_log("=" * 46, "WARNING")
    login_event.wait(timeout=600)  # 最长等10分钟
    with _state_lock:
        waiting_login = False
    append_log("登录确认完成，继续执行...")


def _web_success():
    """成功回调：已进入付款页"""
    with _state_lock:
        success_flag["hit"] = True
    append_log("🎉 已进入付款界面！请立即在浏览器中完成支付！", "SUCCESS")


# ============================================================
# 路由
# ============================================================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    with _state_lock:
        return jsonify({
            "running": running,
            "waiting_login": waiting_login,
            "success": success_flag["hit"],
        })


@app.route("/api/logs")
def api_logs():
    """增量拉取日志：前端传 after=<上次最大id>"""
    try:
        after = int(request.args.get("after", 0))
    except ValueError:
        after = 0
    with _state_lock:
        new_logs = [l for l in _logs if l["id"] > after]
        return jsonify({
            "logs": new_logs,
            "running": running,
            "waiting_login": waiting_login,
            "success": success_flag["hit"],
        })


@app.route("/api/start", methods=["POST"])
def api_start():
    global bot, bot_thread, running, success_flag

    if running:
        return jsonify({"ok": False, "error": "任务已在运行中，请先停止"}), 409

    data = request.get_json(silent=True) or {}

    # 参数校验
    item_id = str(data.get("item_id", "")).strip()
    ticket_kw = str(data.get("ticket_keyword", "")).strip()
    if not item_id:
        return jsonify({"ok": False, "error": "请填写演出ID（详情页URL item.htm?id= 后面的数字）"}), 400
    if not ticket_kw:
        return jsonify({"ok": False, "error": "请填写票档关键词（如 88元 / 前区互动）"}), 400

    try:
        quantity = int(data.get("quantity", 1) or 1)
        max_retry = int(data.get("max_retry", 50) or 50)
        request_interval = float(data.get("request_interval", 0.5) or 0.5)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "数量/重试次数/间隔格式不正确"}), 400

    quantity = max(1, min(quantity, 6))
    start_time = str(data.get("start_time", "")).strip() or None
    if start_time:
        # 校验时间格式
        import datetime
        try:
            datetime.datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return jsonify({"ok": False, "error": "开售时间格式应为 2026-08-20 12:00:00"}), 400

    config = TicketConfig(
        item_id=item_id,
        session_keyword=str(data.get("session_keyword", "")).strip(),
        ticket_keyword=ticket_kw,
        quantity=quantity,
        start_time=start_time,
        fast_mode=bool(data.get("fast_mode", True)),
        show_browser=not bool(data.get("headless", False)),
        max_retry=max_retry,
        request_interval=request_interval,
        warmup_seconds=60,
        fast_poll_interval=0.05,
    )

    # 初始化机器人 + Web回调
    bot = DamaiTicketBot(config)
    bot.login_callback = _web_login_wait
    bot.on_success_callback = _web_success

    login_event.clear()
    with _state_lock:
        running = True
        success_flag["hit"] = False

    bot_thread = threading.Thread(target=_run_bot, daemon=True)
    bot_thread.start()

    mode = "极速" if config.fast_mode else "普通"
    append_log(f"===== 启动抢票（{mode}模式）=====")
    append_log(f"演出ID: {config.item_id} | 场次: {config.session_keyword or '自动'} | "
               f"票档: {config.ticket_keyword} | 数量: {config.quantity}")
    if config.start_time:
        append_log(f"开售时间: {config.start_time}")

    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    if bot:
        bot.stop()
    login_event.set()  # 解除登录等待
    append_log("已发送停止指令...", "WARNING")
    return jsonify({"ok": True})


@app.route("/api/login_done", methods=["POST"])
def api_login_done():
    global waiting_login
    login_event.set()
    with _state_lock:
        waiting_login = False
    append_log("用户确认登录完成，继续执行...")
    return jsonify({"ok": True})


@app.route("/api/clear_logs", methods=["POST"])
def api_clear_logs():
    global _logs
    with _state_lock:
        _logs = []
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("=" * 50)
    print("  大麦网抢票工具 Web版（仅个人学习用途）")
    print("  浏览器打开: http://localhost:8787")
    print("=" * 50)
    app.run(host="0.0.0.0", port=8787, debug=False, threaded=True)
