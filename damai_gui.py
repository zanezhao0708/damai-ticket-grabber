#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大麦网抢票工具 - GUI版本
========================

【重要声明】
1. 本工具仅用于个人技术学习和研究目的，不用于任何盈利活动
2. 使用自动化工具可能违反大麦网《用户服务协议》，风险自担
3. 请尊重公平购票秩序，理性消费

【运行方式】
    python damai_gui.py

【依赖】
    pip install selenium webdriver-manager

【功能】
    - 图形界面配置演出ID/场次/票档/数量/开售时间
    - 一键启动/停止
    - 极速模式：开售前预热页面+预选项，开售瞬间JS注入点击（比手速快）
    - 实时日志显示
    - 配置保存/加载（damai_config.json）
    - 手动登录引导（扫码/验证码后点"登录完成"）
"""

import json
import os
import sys
import threading
import logging
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

# 确保能导入同目录的核心模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from damai_ticket_study import TicketConfig, DamaiTicketBot, logger as core_logger

CONFIG_FILE = "damai_config.json"


# ============================================================
# GUI日志Handler：把核心模块的日志转发到界面
# ============================================================
class GUILogHandler(logging.Handler):
    def __init__(self, gui):
        super().__init__()
        self.gui = gui
        self.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))

    def emit(self, record):
        try:
            msg = self.format(record)
            self.gui.append_log(msg)
        except Exception:
            pass


class DamaiGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("大麦网抢票工具（个人学习用途）")
        self.root.geometry("880x720")
        self.root.minsize(760, 620)

        self.bot = None
        self.bot_thread = None
        self.login_event = threading.Event()  # 手动登录确认事件
        self.running = False

        self._build_style()
        self._build_ui()
        self._load_config()

        # 挂载GUI日志Handler
        gui_handler = GUILogHandler(self)
        gui_handler.setLevel(logging.INFO)
        core_logger.addHandler(gui_handler)
        # 同时去掉核心模块里的基础StreamHandler，避免终端重复输出（可选保留）
        # core_logger.handlers = [h for h in core_logger.handlers if not isinstance(h, logging.StreamHandler)]

        self.append_log("欢迎使用大麦网抢票工具（仅个人学习用途）")
        self.append_log("提示：首次运行需要手动登录，Cookie会自动保存")

    # --------------------------------------------------------
    # 界面构建
    # --------------------------------------------------------
    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass
        style.configure("TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", font=("Microsoft YaHei UI", 10))
        style.configure("Start.TButton", font=("Microsoft YaHei UI", 12, "bold"), foreground="#0a7d32")
        style.configure("Stop.TButton", font=("Microsoft YaHei UI", 12, "bold"), foreground="#c62828")

    def _build_ui(self):
        # ============ 顶部：参数配置区 ============
        param_frame = ttk.LabelFrame(self.root, text="抢票参数配置", padding=10)
        param_frame.pack(fill=tk.X, padx=12, pady=(12, 6))

        # 第一行：演出ID + 场次关键词
        row1 = ttk.Frame(param_frame)
        row1.pack(fill=tk.X, pady=3)
        ttk.Label(row1, text="演出ID:", width=12, anchor="e").pack(side=tk.LEFT)
        self.item_id_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.item_id_var, width=24).pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(row1, text="场次关键词:", width=12, anchor="e").pack(side=tk.LEFT)
        self.session_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.session_var, width=24).pack(side=tk.LEFT, padx=4)

        # 第二行：票档关键词 + 数量
        row2 = ttk.Frame(param_frame)
        row2.pack(fill=tk.X, pady=3)
        ttk.Label(row2, text="票档关键词:", width=12, anchor="e").pack(side=tk.LEFT)
        self.ticket_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.ticket_var, width=24).pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(row2, text="数量:", width=12, anchor="e").pack(side=tk.LEFT)
        self.qty_var = tk.StringVar(value="1")
        ttk.Spinbox(row2, from_=1, to=6, textvariable=self.qty_var, width=6).pack(side=tk.LEFT, padx=4)

        # 第三行：开售时间 + 模式
        row3 = ttk.Frame(param_frame)
        row3.pack(fill=tk.X, pady=3)
        ttk.Label(row3, text="开售时间:", width=12, anchor="e").pack(side=tk.LEFT)
        self.start_time_var = tk.StringVar()
        ttk.Entry(row3, textvariable=self.start_time_var, width=24).pack(side=tk.LEFT, padx=4)
        ttk.Label(row3, text="(格式 2026-08-20 12:00:00，留空立即开始)", foreground="#666").pack(side=tk.LEFT, padx=(0, 12))

        # 第四行：模式选项
        row4 = ttk.Frame(param_frame)
        row4.pack(fill=tk.X, pady=3)
        self.fast_mode_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row4, text="⚡极速模式（开售前预热+瞬间点击，比手速快）", variable=self.fast_mode_var).pack(side=tk.LEFT, padx=(86, 12))
        self.headless_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row4, text="无头模式（隐藏浏览器）", variable=self.headless_var).pack(side=tk.LEFT)

        # 第五行：重试与间隔
        row5 = ttk.Frame(param_frame)
        row5.pack(fill=tk.X, pady=3)
        ttk.Label(row5, text="最大重试:", width=12, anchor="e").pack(side=tk.LEFT)
        self.retry_var = tk.StringVar(value="50")
        ttk.Spinbox(row5, from_=1, to=999, textvariable=self.retry_var, width=6).pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(row5, text="重试间隔(秒):", width=12, anchor="e").pack(side=tk.LEFT)
        self.interval_var = tk.StringVar(value="0.5")
        ttk.Entry(row5, textvariable=self.interval_var, width=8).pack(side=tk.LEFT, padx=4)

        # 提示文字
        ttk.Label(param_frame,
                  text="提示：演出ID在大麦网详情页URL中（item.htm?id=后面的数字）；场次/票档关键词支持模糊匹配，如“13:30”“88元”",
                  foreground="#666", wraplength=800, justify=tk.LEFT).pack(anchor="w", pady=(6, 0))

        # ============ 中部：控制按钮区 ============
        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(fill=tk.X, padx=12, pady=6)

        self.start_btn = ttk.Button(ctrl_frame, text="▶ 开始抢票", style="Start.TButton", command=self.on_start)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.stop_btn = ttk.Button(ctrl_frame, text="■ 停止", style="Stop.TButton", command=self.on_stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.login_btn = ttk.Button(ctrl_frame, text="✓ 我已登录完成", command=self.on_login_done, state=tk.DISABLED)
        self.login_btn.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(ctrl_frame, text="保存配置", command=self.save_config).pack(side=tk.RIGHT, padx=4)
        ttk.Button(ctrl_frame, text="导入配置", command=self.load_config_dialog).pack(side=tk.RIGHT, padx=4)

        # 状态栏
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=12, pady=(0, 4))
        ttk.Label(status_frame, text="状态:").pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="就绪")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, font=("Microsoft YaHei UI", 10, "bold"))
        self.status_label.pack(side=tk.LEFT, padx=6)

        # ============ 底部：日志区 ============
        log_frame = ttk.LabelFrame(self.root, text="运行日志", padding=6)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 12))

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, font=("Consolas", 9), state=tk.DISABLED, height=18)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # 日志颜色标签
        self.log_text.tag_configure("info", foreground="#333")
        self.log_text.tag_configure("warning", foreground="#c78f00")
        self.log_text.tag_configure("error", foreground="#c62828")
        self.log_text.tag_configure("success", foreground="#0a7d32")

        # 关闭窗口处理
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # --------------------------------------------------------
    # 日志显示（线程安全）
    # --------------------------------------------------------
    def append_log(self, message: str, level: str = "info"):
        def _append():
            self.log_text.configure(state=tk.NORMAL)
            tag = level if level in ("info", "warning", "error", "success") else "info"
            if "成功" in message or "🎉" in message or "✅" in message:
                tag = "success"
            elif "失败" in message or "异常" in message or "错误" in message:
                tag = "error"
            elif "警告" in message or "重试" in message or "未成功" in message:
                tag = "warning"
            self.log_text.insert(tk.END, message + "\n", tag)
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)
        self.root.after(0, _append)

    def set_status(self, text: str, color: str = "#333"):
        def _set():
            self.status_var.set(text)
            self.status_label.configure(foreground=color)
        self.root.after(0, _set)

    # --------------------------------------------------------
    # 配置保存/加载
    # --------------------------------------------------------
    def _collect_config_dict(self) -> dict:
        return {
            "item_id": self.item_id_var.get().strip(),
            "session_keyword": self.session_var.get().strip(),
            "ticket_keyword": self.ticket_var.get().strip(),
            "quantity": int(self.qty_var.get() or "1"),
            "start_time": self.start_time_var.get().strip() or None,
            "fast_mode": self.fast_mode_var.get(),
            "show_browser": not self.headless_var.get(),
            "max_retry": int(self.retry_var.get() or "50"),
            "request_interval": float(self.interval_var.get() or "0.5"),
        }

    def _apply_config_dict(self, cfg: dict):
        self.item_id_var.set(cfg.get("item_id", ""))
        self.session_var.set(cfg.get("session_keyword", ""))
        self.ticket_var.set(cfg.get("ticket_keyword", ""))
        self.qty_var.set(str(cfg.get("quantity", 1)))
        self.start_time_var.set(cfg.get("start_time") or "")
        self.fast_mode_var.set(cfg.get("fast_mode", True))
        self.headless_var.set(not cfg.get("show_browser", True))
        self.retry_var.set(str(cfg.get("max_retry", 50)))
        self.interval_var.set(str(cfg.get("request_interval", 0.5)))

    def save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._collect_config_dict(), f, ensure_ascii=False, indent=2)
            self.append_log(f"配置已保存到 {CONFIG_FILE}")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self._apply_config_dict(json.load(f))
            except Exception:
                pass

    def load_config_dialog(self):
        path = filedialog.askopenfilename(filetypes=[("JSON配置", "*.json")])
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._apply_config_dict(json.load(f))
                self.append_log(f"已导入配置: {path}")
            except Exception as e:
                messagebox.showerror("导入失败", str(e))

    # --------------------------------------------------------
    # 控制逻辑
    # --------------------------------------------------------
    def on_start(self):
        # 参数校验
        item_id = self.item_id_var.get().strip()
        if not item_id:
            messagebox.showwarning("缺少参数", "请填写演出ID（详情页URL中 item.htm?id= 后面的数字）")
            return
        if not item_id.isdigit():
            if messagebox.askyesno("演出ID格式", "演出ID通常是纯数字，确认使用当前值继续吗？"):
                pass
            else:
                return
        if not self.ticket_var.get().strip():
            messagebox.showwarning("缺少参数", "请填写票档关键词（如“88元”“前区互动”）")
            return

        # 构建配置
        cfg = self._collect_config_dict()
        config = TicketConfig(
            item_id=cfg["item_id"],
            session_keyword=cfg["session_keyword"],
            ticket_keyword=cfg["ticket_keyword"],
            quantity=cfg["quantity"],
            start_time=cfg["start_time"],
            fast_mode=cfg["fast_mode"],
            show_browser=cfg["show_browser"],
            max_retry=cfg["max_retry"],
            request_interval=cfg["request_interval"],
            warmup_seconds=60,
            fast_poll_interval=0.05,
        )

        # 初始化机器人 + 回调
        self.bot = DamaiTicketBot(config)
        self.bot.log_callback = lambda msg: self.append_log(msg)
        self.bot.login_callback = self._wait_login_gui
        self.bot.on_success_callback = self._on_success

        # 启动线程
        self.login_event.clear()
        self.running = True
        self.bot_thread = threading.Thread(target=self._run_bot, daemon=True)
        self.bot_thread.start()

        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        mode = "极速" if config.fast_mode else "普通"
        self.set_status(f"运行中（{mode}模式）", "#0a7d32")
        self.append_log(f"===== 启动抢票（{mode}模式）=====")
        self.append_log(f"演出ID: {config.item_id} | 场次: {config.session_keyword or '自动'} | "
                        f"票档: {config.ticket_keyword} | 数量: {config.quantity}")
        if config.start_time:
            self.append_log(f"开售时间: {config.start_time}")

    def _run_bot(self):
        try:
            self.bot.run()
        except Exception as e:
            self.append_log(f"运行异常: {e}", "error")
        finally:
            self.running = False
            self.root.after(0, self._reset_buttons)

    def _reset_buttons(self):
        self.start_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)
        self.login_btn.configure(state=tk.DISABLED)
        self.set_status("已停止", "#c62828")

    def on_stop(self):
        if self.bot:
            self.bot.stop()
        self.login_event.set()  # 解除登录等待（如有）
        self.append_log("已发送停止指令...")
        self.set_status("正在停止...", "#c78f00")

    def on_login_done(self):
        self.login_event.set()
        self.append_log("用户确认登录完成，继续执行...")
        self.login_btn.configure(state=tk.DISABLED)

    def _wait_login_gui(self):
        """登录回调：在GUI上提示用户手动登录，等待用户点击确认"""
        self.append_log("=" * 46)
        self.append_log("请在弹出的浏览器窗口中完成登录（扫码/验证码）")
        self.append_log("登录完成后，点击界面上的“✓ 我已登录完成”按钮")
        self.append_log("=" * 46)
        self.root.after(0, lambda: self.login_btn.configure(state=tk.NORMAL))
        self.set_status("等待手动登录...", "#c78f00")
        self.login_event.wait(timeout=600)  # 最长等10分钟
        self.set_status("登录完成，继续执行", "#0a7d32")

    def _on_success(self):
        self.append_log("🎉🎉🎉 已进入付款界面！请在浏览器中尽快完成支付 🎉🎉🎉", "success")
        self.set_status("已进入付款页，请支付！", "#0a7d32")
        messagebox.showinfo("抢票成功", "已进入付款界面！\n请立即在浏览器中完成支付！")

    def on_close(self):
        if self.running:
            if not messagebox.askyesno("确认退出", "抢票任务正在运行，确定退出吗？"):
                return
            if self.bot:
                self.bot.stop()
            self.login_event.set()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = DamaiGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
