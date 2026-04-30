"""
高性能异步Patrick预约系统 - 修复版
- 修复事件循环问题
- GUI只显示关键信息
- 控制台输出调试信息
"""

import sys
import asyncio
import re
import threading
import time
import tkinter as tk
from tkinter import ttk
from datetime import datetime, timedelta
from typing import Dict, List
from dataclasses import dataclass, field

from playwright.async_api import async_playwright

# 尝试打开控制台（仅Windows）
if sys.platform == "win32":
    try:
        import ctypes
        if not ctypes.windll.kernel32.GetConsoleWindow():
            ctypes.windll.kernel32.AllocConsole()
            sys.stdout = open('CONOUT$', 'w', encoding='utf8')
            sys.stderr = open('CONOUT$', 'w', encoding='utf8')
            print("=" * 50)
            print("控制台已打开 - 调试信息")
            print("=" * 50)
    except:
        pass


@dataclass
class BookingState:
    """预定状态管理类"""
    is_running: bool = False
    is_paused: bool = False
    hour_values: List[int] = field(default_factory=lambda: [0] * 24)
    remaining_values: Dict[int, int] = field(default_factory=dict)
    refresh_interval: float = 3.0
    target_date: str = ""
    scheduled_time: datetime = None


class ControlPanel:
    """控制面板GUI - 精简日志版本"""

    def __init__(self, controller):
        self.controller = controller
        self.root = tk.Tk()
        self.root.title("⚡ 自动预约系统")
        self.root.geometry("520x850")
        self.root.attributes('-topmost', True)
        self.root.configure(bg='#1e1e2f')

        self._scheduled_time = None
        self._schedule_timer = None

        self.setup_ui()

    def setup_ui(self):
        # 标题
        title = tk.Label(self.root, text="⚡ 自动预约系统", font=("微软雅黑", 14, "bold"),
                         bg='#1e1e2f', fg='white')
        title.pack(pady=10)

        # 状态栏
        self.status_var = tk.StringVar(value="⚪ 空闲")
        status_label = tk.Label(self.root, textvariable=self.status_var, font=("微软雅黑", 10),
                                bg='#1e1e2f', fg='#888')
        status_label.pack(pady=5)

        # 页面状态
        self.page_status_var = tk.StringVar(value="🌐 等待登录...")
        page_status_label = tk.Label(self.root, textvariable=self.page_status_var, font=("微软雅黑", 9),
                                      bg='#1e1e2f', fg='#ff9800')
        page_status_label.pack(pady=2)

        # 配置区域
        config_frame = tk.Frame(self.root, bg='#1e1e2f', bd=1, relief=tk.GROOVE)
        config_frame.pack(fill='x', padx=10, pady=5)

        tk.Label(config_frame, text="⚙️ 配置", font=("微软雅黑", 10, "bold"),
                 bg='#1e1e2f', fg='white').pack(anchor='w', padx=5, pady=2)

        # 目标日期
        row1 = tk.Frame(config_frame, bg='#1e1e2f')
        row1.pack(fill='x', padx=5, pady=2)

        tk.Label(row1, text="目标日期:", bg='#1e1e2f', fg='white', width=10).pack(side=tk.LEFT)

        today = datetime.now().strftime("%Y-%m-%d")
        self.target_date_var = tk.StringVar(value=today)
        date_entry = tk.Entry(row1, textvariable=self.target_date_var, width=12,
                               bg='#2d2d3f', fg='white', insertbackground='white')
        date_entry.pack(side=tk.LEFT, padx=5)

        tk.Label(row1, text="格式: YYYY-MM-DD", bg='#1e1e2f', fg='#888', font=("微软雅黑", 8)).pack(side=tk.LEFT)

        # 刷新间隔
        row2 = tk.Frame(config_frame, bg='#1e1e2f')
        row2.pack(fill='x', padx=5, pady=2)

        tk.Label(row2, text="轮次间隔(秒):", bg='#1e1e2f', fg='white', width=12).pack(side=tk.LEFT)
        self.interval_var = tk.StringVar(value="3.0")
        interval_entry = tk.Entry(row2, textvariable=self.interval_var, width=8,
                                   bg='#2d2d3f', fg='white')
        interval_entry.pack(side=tk.LEFT, padx=5)

        self.interval_display = tk.Label(row2, text="", bg='#1e1e2f', fg='#4caf50', font=("微软雅黑", 8))
        self.interval_display.pack(side=tk.LEFT, padx=5)

        def on_interval_change(*args):
            try:
                val = float(self.interval_var.get())
                if val >= 0.5:
                    self.interval_display.config(text=f"(当前: {val}秒)")
                else:
                    self.interval_var.set("3.0")
                    self.interval_display.config(text="(当前: 3.0秒)")
            except:
                pass

        self.interval_var.trace_add("write", on_interval_change)
        on_interval_change()

        # 定时启动
        row3 = tk.Frame(config_frame, bg='#1e1e2f')
        row3.pack(fill='x', padx=5, pady=2)

        tk.Label(row3, text="定时启动:", bg='#1e1e2f', fg='white', width=10).pack(side=tk.LEFT)

        time_frame = tk.Frame(row3, bg='#1e1e2f')
        time_frame.pack(side=tk.LEFT, padx=5)

        self.schedule_hour = tk.Spinbox(time_frame, from_=0, to=23, width=3,
                                         format="%02.0f", bg='#2d2d3f', fg='white')
        self.schedule_hour.pack(side=tk.LEFT)
        tk.Label(time_frame, text=":", bg='#1e1e2f', fg='white').pack(side=tk.LEFT)
        self.schedule_minute = tk.Spinbox(time_frame, from_=0, to=59, width=3,
                                           format="%02.0f", bg='#2d2d3f', fg='white')
        self.schedule_minute.pack(side=tk.LEFT)
        tk.Label(time_frame, text=":", bg='#1e1e2f', fg='white').pack(side=tk.LEFT)
        self.schedule_second = tk.Spinbox(time_frame, from_=0, to=59, width=3,
                                           format="%02.0f", bg='#2d2d3f', fg='white')
        self.schedule_second.pack(side=tk.LEFT)

        self.schedule_btn = tk.Button(row3, text="设置定时", command=self.set_schedule,
                                       bg='#2196f3', fg='white', font=("微软雅黑", 9), width=8)
        self.schedule_btn.pack(side=tk.LEFT, padx=10)

        self.schedule_status = tk.Label(row3, text="", bg='#1e1e2f', fg='#ff9800', font=("微软雅黑", 8))
        self.schedule_status.pack(side=tk.LEFT, padx=5)

        # 控制按钮
        btn_frame = tk.Frame(self.root, bg='#1e1e2f')
        btn_frame.pack(pady=10)

        self.start_btn = tk.Button(btn_frame, text="立即开始", command=self.start_clicked,
                                   bg='#4caf50', fg='white', font=("微软雅黑", 10), width=10)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = tk.Button(btn_frame, text="停止", command=self.stop_clicked,
                                   bg='#f44336', fg='white', font=("微软雅黑", 10), width=10, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.reset_btn = tk.Button(btn_frame, text="重置", command=self.reset_clicked,
                                   bg='#ff9800', fg='white', font=("微软雅黑", 10), width=10)
        self.reset_btn.pack(side=tk.LEFT, padx=5)

        # 24小时输入区域
        hours_label = tk.Label(self.root, text="📅 各时段预约数量", bg='#1e1e2f', fg='white', font=("微软雅黑", 10))
        hours_label.pack(anchor='w', padx=10, pady=(10, 0))

        canvas = tk.Canvas(self.root, bg='#1e1e2f', highlightthickness=0)
        scrollbar = tk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='#1e1e2f')

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=5)
        scrollbar.pack(side="right", fill="y")

        self.hour_entries = {}
        for i in range(24):
            frame = tk.Frame(scrollable_frame, bg='#1e1e2f')
            frame.pack(fill='x', pady=2)
            label = tk.Label(frame, text=f"{i:02d}:00", width=6, bg='#1e1e2f', fg='white', font=("Consolas", 9))
            label.pack(side=tk.LEFT, padx=5)
            entry = tk.Entry(frame, width=10, bg='#2d2d3f', fg='white', insertbackground='white', font=("Consolas", 9))
            entry.insert(0, "0")
            entry.pack(side=tk.LEFT, padx=5)
            self.hour_entries[i] = entry

        # 日志区域 - 只显示关键信息
        log_label = tk.Label(self.root, text="📋 预约记录", bg='#1e1e2f', fg='white', font=("微软雅黑", 9))
        log_label.pack(anchor='w', padx=10, pady=(10, 0))

        log_frame = tk.Frame(self.root, bg='#1e1e2f')
        log_frame.pack(fill='both', expand=True, padx=10, pady=5)

        self.log_text = tk.Text(log_frame, height=16, bg='#0d0d1a', fg='#0f0',
                                font=("Consolas", 9), wrap=tk.WORD, width=65)
        log_scroll = tk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.log_text.pack(side=tk.LEFT, fill='both', expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def log_success(self, message: str):
        """GUI只显示预约成功/失败记录"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)

    def log_config(self, message: str):
        """GUI显示配置信息"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)

    def set_schedule(self):
        try:
            hour = int(self.schedule_hour.get())
            minute = int(self.schedule_minute.get())
            second = int(self.schedule_second.get())

            now = datetime.now()
            target_time = datetime(now.year, now.month, now.day, hour, minute, second)

            if target_time <= now:
                target_time += timedelta(days=1)

            self._scheduled_time = target_time
            self.schedule_status.config(text=f"⏰ {target_time.strftime('%H:%M:%S')} 自动开始")
            print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ✅ 已设置定时")

            self._start_schedule_timer()
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ❌ 设置定时失败: {e}")

    def _start_schedule_timer(self):
        if self._schedule_timer:
            self.root.after_cancel(self._schedule_timer)

        now = datetime.now()
        if self._scheduled_time and now < self._scheduled_time:
            delay_ms = int((self._scheduled_time - now).total_seconds() * 1000)
            self._schedule_timer = self.root.after(delay_ms, self._on_schedule_timeout)

    def _on_schedule_timeout(self):
        print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ⏰ 定时时间到，自动开始预约")
        self.start_clicked()

    def get_config(self):
        values = []
        for i in range(24):
            try:
                val = int(self.hour_entries[i].get())
                if val < 0:
                    val = 0
            except:
                val = 0
            values.append(val)

        interval = float(self.interval_var.get() or 3.0)
        if interval < 0.5:
            interval = 3.0
            self.interval_var.set("3.0")

        return {
            'hour_values': values,
            'target_date': self.target_date_var.get().strip(),
            'refresh_interval': interval
        }

    def start_clicked(self):
        config = self.get_config()
        total = sum(config['hour_values'])
        if total == 0:
            self.log_config("⚠️ 没有需要预约的数量")
            return

        self._scheduled_time = None
        if self._schedule_timer:
            self.root.after_cancel(self._schedule_timer)
            self._schedule_timer = None

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.schedule_btn.config(state=tk.DISABLED)
        self.update_status("🟢 运行中")

        # 显示配置信息到GUI
        self.log_config(f"📊 目标日期: {config['target_date']}, 间隔: {config['refresh_interval']}秒, 总需求: {total}")

        print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 准备启动预约...")

        # 检查事件循环
        if self.controller.loop is None:
            print("错误: controller.loop 为 None")
            return
        if self.controller.loop.is_closed():
            print("错误: 事件循环已关闭")
            return

        # 提交异步任务
        future = asyncio.run_coroutine_threadsafe(
            self.controller.start_booking(config, self),
            self.controller.loop
        )

        def handle_done(f):
            try:
                f.result()
            except Exception as e:
                print(f"异步任务失败: {e}")
                import traceback
                traceback.print_exc()

        future.add_done_callback(handle_done)
        print("异步任务已提交")

    def stop_clicked(self):
        asyncio.run_coroutine_threadsafe(self.controller.stop(), self.controller.loop)
        self.stop_btn.config(state=tk.DISABLED)
        self.update_status("⚪ 已停止")

    def reset_clicked(self):
        asyncio.run_coroutine_threadsafe(self.controller.reset(), self.controller.loop)
        for i in range(24):
            self.hour_entries[i].delete(0, tk.END)
            self.hour_entries[i].insert(0, "0")
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.schedule_btn.config(state=tk.NORMAL)
        self.update_status("⚪ 空闲")
        self.schedule_status.config(text="")
        self._scheduled_time = None
        if self._schedule_timer:
            self.root.after_cancel(self._schedule_timer)
            self._schedule_timer = None

    def update_status(self, status: str):
        self.status_var.set(status)

    def on_booking_finished(self):
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.schedule_btn.config(state=tk.NORMAL)
        self.update_status("⚪ 空闲")

    def run(self):
        self.root.mainloop()


class BookingController:
    """异步预约控制器 - 精简日志版本"""

    def __init__(self):
        self.state = BookingState()
        self.total_needed = 0
        self.total_booked = 0
        self.page = None
        self.browser = None
        self.context = None
        self.playwright = None
        self.loop = None
        self.panel = None
        self._stop_flag = False
        self.SEARCH_URL = "https://aslpb.vbs.1-stop.biz/SearchBookSlots.aspx?mnitm=154142190"

    def log_console(self, message: str):
        """所有调试信息输出到控制台"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] {message}")

    def log_success_gui(self, message: str):
        """预约成功/失败记录显示在GUI"""
        if self.panel:
            self.panel.log_success(message)

    async def start_booking(self, config: dict, panel):
        self.panel = panel
        self.state.hour_values = config['hour_values']
        self.state.target_date = config['target_date']
        self.state.refresh_interval = config['refresh_interval']
        self.total_needed = sum(self.state.hour_values)

        self.state.remaining_values = {h: v for h, v in enumerate(self.state.hour_values) if v > 0}
        self.total_booked = 0
        self.state.is_running = True
        self._stop_flag = False

        self.log_console(f"配置加载: 目标日期={self.state.target_date}, 间隔={self.state.refresh_interval}秒, 总需求={self.total_needed}")

        await self._run_booking()

    async def stop(self):
        self._stop_flag = True
        self.state.is_running = False
        self.log_console("已停止")

    async def reset(self):
        self._stop_flag = True
        self.state.is_running = False
        self.state.hour_values = [0] * 24
        self.state.remaining_values = {}
        self.total_needed = 0
        self.total_booked = 0

    async def _wait_for_login(self):
        """等待用户登录并保持在Search页面"""
        self.log_console("=" * 50)
        self.log_console("等待用户登录...")
        self.log_console(f"当前URL: {self.page.url}")
        self.log_console("请确保在Search页面: https://aslpb.vbs.1-stop.biz/SearchBookSlots.aspx")
        self.log_console("=" * 50)

        await asyncio.sleep(3)

        max_wait = 300
        waited = 0

        while self.state.is_running and not self._stop_flag and waited < max_wait:
            try:
                current_url = self.page.url

                if "SearchBookSlots" in current_url:
                    self.log_console("✅ 检测到Search页面，准备就绪")
                    return True

                search_btn = await self.page.locator("#Search").count()
                if search_btn > 0:
                    self.log_console("✅ 检测到Search按钮，准备就绪")
                    return True

                if "SignIn" in current_url or "Login" in current_url:
                    self.log_console("⚠️ 仍在登录页面，请先登录")
                elif "BookSlots" in current_url:
                    self.log_console("⚠️ 已在预约页面，但需要Search页面，请返回Search页面")

            except Exception as e:
                self.log_console(f"检测异常: {e}")

            await asyncio.sleep(3)
            waited += 3

            if waited % 30 == 0:
                self.log_console(f"⏳ 等待中... ({waited}秒)")

        self.log_console("❌ 等待Search页面超时")
        return False

    async def _click_search(self) -> bool:
        """点击Search按钮"""
        try:
            result = await self.page.evaluate("""
                () => {
                    const btn = document.getElementById('Search');
                    if(btn) {
                        btn.click();
                        return true;
                    }
                    const btn2 = document.querySelector("input[value='Search']");
                    if(btn2) {
                        btn2.click();
                        return true;
                    }
                    return false;
                }
            """)

            if result:
                self.log_console("点击Search按钮成功")
                await asyncio.sleep(2)
                return True
            return False
        except Exception as e:
            self.log_console(f"点击Search失败: {e}")
            return False

    async def _select_date(self, target_date: str) -> bool:
        """选择目标日期"""
        try:
            target = datetime.strptime(target_date, "%Y-%m-%d")
            target_str = target.strftime("%a %d/%m")

            await self.page.wait_for_selector(".calendarbar-day:visible", timeout=10000)
            date_elements = await self.page.locator(".calendarbar-day").all()

            for elem in date_elements:
                date_text = await elem.inner_text()
                if target_str in date_text:
                    await elem.click()
                    await asyncio.sleep(1)
                    self.log_console(f"选择日期成功: {target_str}")
                    return True

            self.log_console(f"未找到日期: {target_str}")
            return False
        except Exception as e:
            self.log_console(f"选择日期失败: {e}")
            return False

    async def _get_available_value(self, hour: int) -> int:
        """读取Available值"""
        try:
            if hour < 12:
                table = self.page.locator("table.form_timezones table.table").first
                row_index = hour + 1
            else:
                table = self.page.locator("table.form_timezones table.table").nth(1)
                row_index = hour - 11

            avail_td = table.locator(f"tbody tr:nth-child({row_index}) td:nth-child(2)")
            avail_text = await avail_td.inner_text()
            return int(avail_text.strip()) if avail_text.strip().isdigit() else 0
        except:
            return 0

    async def _select_and_book(self, hour: int, value: int) -> int:
        """选择数量并点击Book"""
        try:
            date_str = self.state.target_date
            select_id = f"DDL_{date_str}_{hour}"
            select_elem = self.page.locator(f"#{select_id}")

            if await select_elem.count() == 0:
                return 0

            options = await select_elem.locator("option").all()
            max_value = 0
            for opt in options:
                opt_val = await opt.get_attribute("value")
                if opt_val and opt_val.isdigit():
                    max_value = max(max_value, int(opt_val))

            book_value = min(value, max_value)
            if book_value <= 0:
                return 0

            await select_elem.select_option(str(book_value))
            await asyncio.sleep(0.2)

            book_btn = self.page.locator(f"#btnBook_{date_str}_{hour}")
            if await book_btn.count() == 0:
                book_btn = self.page.locator(f"#{select_id.replace('DDL', 'pop')} input[value='Book']")

            if await book_btn.count() > 0:
                await book_btn.first.evaluate("element => element.click()")
                await asyncio.sleep(1)

                success = await self._check_booking_result()
                return success if success > 0 else 0
            return 0
        except Exception as e:
            self.log_console(f"小时{hour}操作失败: {e}")
            return 0

    async def _check_booking_result(self) -> int:
        """检查预定结果弹窗"""
        try:
            await asyncio.sleep(0.5)

            dialog = self.page.locator(".ui-dialog:visible")
            if await dialog.count() > 0:
                dialog_text = await dialog.inner_text()
                match = re.search(r'Booked\s+(\d+)\s+Slots?', dialog_text)
                if match:
                    success_count = int(match.group(1))
                    close_btn = dialog.locator("button:has-text('OK'), .dialog-close")
                    if await close_btn.count() > 0:
                        await close_btn.click()
                    return success_count
            return 0
        except:
            return 0

    async def _click_refresh(self) -> bool:
        """点击Refresh按钮"""
        try:
            refresh_id = f"refreshSlots_{self.state.target_date}"
            refresh_btn = self.page.locator(f"#{refresh_id}")
            if await refresh_btn.count() > 0:
                await refresh_btn.click()
                current_interval = self.state.refresh_interval
                self.log_console(f"刷新后等待 {current_interval} 秒")
                await asyncio.sleep(current_interval)
                return True
            return False
        except Exception as e:
            self.log_console(f"点击Refresh失败: {e}")
            return False

    async def _click_continue(self) -> bool:
        """点击Continue按钮返回主页面"""
        try:
            continue_btn = self.page.locator("#Continue")
            if await continue_btn.count() > 0:
                await continue_btn.click()
                await asyncio.sleep(0.5)
                return True
            return False
        except:
            return False

    async def _is_on_booking_page(self) -> bool:
        """检查是否在预约页面"""
        try:
            has_calendar = await self.page.locator(".calendarbar").count() > 0
            has_table = await self.page.locator("table.form_timezones").count() > 0
            return has_calendar and has_table
        except:
            return False

    async def _run_booking(self):
        """主预约循环"""
        round_num = 0

        if not await self._wait_for_login():
            self.state.is_running = False
            return

        if hasattr(self.panel, '_scheduled_time') and self.panel._scheduled_time:
            now = datetime.now()
            if now < self.panel._scheduled_time:
                wait_seconds = (self.panel._scheduled_time - now).total_seconds()
                self.log_console(f"等待定时启动，还需 {wait_seconds:.0f} 秒")
                await asyncio.sleep(wait_seconds)

        self.log_console("点击Search按钮...")
        if not await self._click_search():
            self.log_console("点击Search失败")
            self.state.is_running = False
            return

        await asyncio.sleep(2)

        if not await self._is_on_booking_page():
            self.log_console("未能进入预约页面")
            self.state.is_running = False
            return

        self.log_console("选择目标日期...")
        if not await self._select_date(self.state.target_date):
            self.log_console("日期选择失败")
            self.state.is_running = False
            return

        while self.state.is_running and not self._stop_flag:
            remaining_total = sum(self.state.remaining_values.values())
            if remaining_total == 0:
                self.log_success_gui(f"🎉 全部完成 | 总预定: {self.total_booked}")
                self.log_console("预约全部完成")
                break

            round_num += 1
            before = self.state.remaining_values.copy()

            hours_needed = [h for h, v in before.items() if v > 0]

            if hours_needed:
                tasks = [self._get_available_value(hour) for hour in hours_needed]
                available_results = await asyncio.gather(*tasks)

                book_tasks = []
                book_hours = []

                for i, hour in enumerate(hours_needed):
                    remaining = before.get(hour, 0)
                    available = available_results[i]
                    if remaining > 0 and available > 0:
                        book_amount = min(remaining, available)
                        book_tasks.append(self._select_and_book(hour, book_amount))
                        book_hours.append(hour)
                        self.log_console(f"小时{hour:02d}: 需要{remaining}，可用{available}，尝试预定{book_amount}")
                    else:
                        self.log_console(f"小时{hour:02d}: 可用数量为0")

                if book_tasks:
                    for hour, task in zip(book_hours, book_tasks):
                        if not self.state.is_running or self._stop_flag:
                            break
                        success = await task
                        if success > 0:
                            self.state.remaining_values[hour] -= success
                            self.total_booked += success
                            self.log_success_gui(f"✅ 小时{hour:02d}: 成功{success}个，还剩{self.state.remaining_values[hour]}")
                            self.log_console(f"小时{hour:02d}: 成功{success}个")
                        else:
                            self.log_success_gui(f"❌ 小时{hour:02d}: 预定失败")
                            self.log_console(f"小时{hour:02d}: 预定失败")

                        await self._click_continue()

            await self._click_refresh()

        self.state.is_running = False
        if self.panel:
            self.panel.on_booking_finished()


async def run_browser(controller):
    """启动浏览器"""
    controller.playwright = await async_playwright().start()
    controller.browser = await controller.playwright.chromium.launch(headless=False)
    controller.context = await controller.browser.new_context()
    controller.page = await controller.context.new_page()

    search_url = "https://aslpb.vbs.1-stop.biz/SearchBookSlots.aspx?mnitm=154142190"
    await controller.page.goto(search_url)

    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 🌐 浏览器已启动")
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 📍 打开: {search_url}")
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 🔐 请手动登录并保持在Search页面")

    # 保持事件循环运行
    while True:
        await asyncio.sleep(1)


def main():
    controller = BookingController()

    def run_async():
        controller.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(controller.loop)
        print("事件循环已启动")
        controller.loop.run_until_complete(run_browser(controller))

    browser_thread = threading.Thread(target=run_async, daemon=True)
    browser_thread.start()

    # 等待事件循环初始化
    time.sleep(1)
    print(f"controller.loop 状态: {controller.loop}")

    panel = ControlPanel(controller)
    controller.panel = panel
    panel.run()


if __name__ == "__main__":
    main()