"""
Hutchinson Ports 自动预约系统 - 完整版 v7
- 并发查询 Available 值
- 每轮提交后立即校验，根据 Dashboard 状态判断成功数量
- Pending 状态每3秒刷新等待，超时停止任务
- 成功的小时自动扣除，失败的小时自动加入下一轮重试
- 控制台输出每轮信息，界面显示成功预约
"""

import asyncio
import re
import threading
import tkinter as tk
from tkinter import ttk
from datetime import datetime, timedelta
from typing import Dict, List
from dataclasses import dataclass, field

from playwright.async_api import async_playwright


@dataclass
class BookingState:
    is_running: bool = False
    is_paused: bool = False
    hour_values: List[int] = field(default_factory=lambda: [0] * 24)
    req_type: str = "IMPORT"
    remaining_values: Dict[int, int] = field(default_factory=dict)
    refresh_interval: float = 1.0


class ControlPanel:
    def __init__(self, controller):
        self.controller = controller
        self.root = tk.Tk()
        self.root.title("自动预约控制系统")
        self.root.geometry("520x850")
        self.root.attributes('-topmost', True)
        self.root.configure(bg='#1e1e2f')

        self._scheduled_time = None
        self._schedule_timer = None

        self.setup_ui()

    def setup_ui(self):
        title = tk.Label(self.root, text="🤖 自动预约系统", font=("微软雅黑", 14, "bold"),
                         bg='#1e1e2f', fg='white')
        title.pack(pady=10)

        self.status_var = tk.StringVar(value="⚪ 空闲")
        status_label = tk.Label(self.root, textvariable=self.status_var, font=("微软雅黑", 10),
                                bg='#1e1e2f', fg='#888')
        status_label.pack(pady=5)

        config_frame = tk.Frame(self.root, bg='#1e1e2f', bd=1, relief=tk.GROOVE)
        config_frame.pack(fill='x', padx=10, pady=5)

        tk.Label(config_frame, text="⚙️ 配置", font=("微软雅黑", 10, "bold"),
                 bg='#1e1e2f', fg='white').pack(anchor='w', padx=5, pady=2)

        row1 = tk.Frame(config_frame, bg='#1e1e2f')
        row1.pack(fill='x', padx=5, pady=2)

        tk.Label(row1, text="预约类型:", bg='#1e1e2f', fg='white', width=10).pack(side=tk.LEFT)
        self.req_type_var = tk.StringVar(value="IMPORT")
        type_menu = ttk.Combobox(row1, textvariable=self.req_type_var,
                                  values=["IMPORT", "EXPORT"], width=12)
        type_menu.pack(side=tk.LEFT, padx=5)

        tk.Label(row1, text="轮次间隔(秒):", bg='#1e1e2f', fg='white', width=12).pack(side=tk.LEFT, padx=(20, 0))
        self.interval_var = tk.StringVar(value="1.0")
        interval_entry = tk.Entry(row1, textvariable=self.interval_var, width=8,
                                   bg='#2d2d3f', fg='white')
        interval_entry.pack(side=tk.LEFT, padx=5)

        row2 = tk.Frame(config_frame, bg='#1e1e2f')
        row2.pack(fill='x', padx=5, pady=2)

        tk.Label(row2, text="定时启动:", bg='#1e1e2f', fg='white', width=10).pack(side=tk.LEFT)

        time_frame = tk.Frame(row2, bg='#1e1e2f')
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

        self.schedule_date_var = tk.StringVar(value="今天")
        date_menu = ttk.Combobox(time_frame, textvariable=self.schedule_date_var,
                                   values=["今天", "明天"], width=6)
        date_menu.pack(side=tk.LEFT, padx=5)

        self.schedule_btn = tk.Button(row2, text="设置定时", command=self.set_schedule,
                                       bg='#2196f3', fg='white', font=("微软雅黑", 9), width=8)
        self.schedule_btn.pack(side=tk.LEFT, padx=10)

        self.schedule_status = tk.Label(row2, text="", bg='#1e1e2f', fg='#ff9800', font=("微软雅黑", 8))
        self.schedule_status.pack(side=tk.LEFT, padx=5)

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
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        if int(self.log_text.index('end-1c').split('.')[0]) > 500:
            self.log_text.delete(1.0, 100.0)

    def log_system(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)

    def set_schedule(self):
        try:
            hour = int(self.schedule_hour.get())
            minute = int(self.schedule_minute.get())
            second = int(self.schedule_second.get())

            now = datetime.now()
            target_date = now.date()
            if self.schedule_date_var.get() == "明天":
                target_date += timedelta(days=1)

            target_time = datetime(target_date.year, target_date.month, target_date.day, hour, minute, second)

            if target_time <= now:
                target_time += timedelta(days=1)

            self._scheduled_time = target_time
            self.schedule_status.config(text=f"⏰ {target_time.strftime('%H:%M:%S')} 自动开始")
            self.log_system(f"✅ 已设置定时: {target_time.strftime('%Y-%m-%d %H:%M:%S')}")

            self._start_schedule_timer()
        except Exception as e:
            self.log_system(f"❌ 设置定时失败: {e}")

    def _start_schedule_timer(self):
        if self._schedule_timer:
            self.root.after_cancel(self._schedule_timer)

        now = datetime.now()
        if self._scheduled_time and now < self._scheduled_time:
            delay_ms = int((self._scheduled_time - now).total_seconds() * 1000)
            self._schedule_timer = self.root.after(delay_ms, self._on_schedule_timeout)
            self.log_system(f"⏰ 定时器已启动，将在 {delay_ms//1000} 秒后执行")

    def _on_schedule_timeout(self):
        self.log_system("⏰ 定时时间到，自动开始预约")
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

        return {
            'hour_values': values,
            'req_type': self.req_type_var.get(),
            'refresh_interval': float(self.interval_var.get() or 1.0)
        }

    def start_clicked(self):
        config = self.get_config()
        total = sum(config['hour_values'])
        if total == 0:
            self.log_system("⚠️ 没有需要预约的数量")
            return

        # 清除定时时间，避免影响立即开始
        self._scheduled_time = None
        if self._schedule_timer:
            self.root.after_cancel(self._schedule_timer)
            self._schedule_timer = None

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.schedule_btn.config(state=tk.DISABLED)
        self.update_status("🟢 运行中")

        asyncio.run_coroutine_threadsafe(
            self.controller.start_booking(config, self),
            self.controller.loop
        )

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
        # 清除定时
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
    def __init__(self):
        self.state = BookingState()
        self.total_needed = 0
        self.total_booked = 0
        self.page = None
        self.browser = None
        self.playwright = None
        self.loop = None
        self.panel = None
        self._stop_flag = False

    def log_console(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] {message}")

    def log_success_gui(self, message: str):
        if self.panel:
            self.panel.log_success(message)

    def log_system_gui(self, message: str):
        if self.panel:
            self.panel.log_system(message)

    async def start_booking(self, config: dict, panel):
        self.panel = panel
        self.state.hour_values = config['hour_values']
        self.state.req_type = config['req_type']
        self.state.refresh_interval = config['refresh_interval']
        self.total_needed = sum(self.state.hour_values)

        self.state.remaining_values = {h: v for h, v in enumerate(self.state.hour_values) if v > 0}
        self.total_booked = 0
        self.state.is_running = True
        self._stop_flag = False

        self.log_system_gui(f"📊 类型: {self.state.req_type}, 间隔: {self.state.refresh_interval}秒, 总需求: {self.total_needed}")
        self.log_console(f"📊 类型: {self.state.req_type}, 间隔: {self.state.refresh_interval}秒, 总需求: {self.total_needed}")

        await self._run_booking()

    async def stop(self):
        self._stop_flag = True
        self.state.is_running = False
        self.log_system_gui("⏸️ 已停止")
        self.log_console("⏸️ 已停止")

    async def reset(self):
        self._stop_flag = True
        self.state.is_running = False
        self.state.hour_values = [0] * 24
        self.state.remaining_values = {}
        self.total_needed = 0
        self.total_booked = 0
        self.log_system_gui("🔄 已重置")
        self.log_console("🔄 已重置")

    async def _is_page_ready(self) -> bool:
        try:
            left = await self.page.query_selector('.left-panel')
            return left is not None
        except:
            return False

    async def _get_available_value(self, hour: int) -> int:
        """读取 Available 值 - Import在第2列，Export在第5列"""
        try:
            row_index = hour % 12 + 1
            if self.state.req_type == "IMPORT":
                col_index = 3
            else:
                col_index = 6

            panel_class = "left-panel" if hour < 12 else "right-panel"
            selector = f".{panel_class} table tbody tr:nth-child({row_index}) td:nth-child({col_index})"

            element = await self.page.query_selector(selector)
            if element:
                text = await element.inner_text()
                text = text.strip()
                if text.isdigit():
                    return int(text)
            return 0
        except Exception as e:
            return 0

    async def _fill_request_value(self, hour: int, value: int) -> bool:
        try:
            formatted_type = "Import" if self.state.req_type == "IMPORT" else "Export"
            input_id = f"Summary_ZoneSummary_{hour}__{formatted_type}_Request"
            await self.page.fill(f"#{input_id}", str(value))
            return True
        except:
            return False

    async def _click_submit(self) -> bool:
        try:
            await self.page.click("#Book")
            await asyncio.sleep(0.05)
            yes_btn = await self.page.query_selector("button:has-text('Yes')")
            if yes_btn:
                await yes_btn.click()
            await asyncio.sleep(0.05)
            return True
        except:
            return False

    async def _refresh_page(self):
        try:
            await self.page.reload()
            await asyncio.sleep(0.05)
        except:
            pass

    async def _verify_round_submission(self, round_requests: Dict[int, int]) -> Dict[int, int]:
        """
        校验本轮提交，返回实际成功的小时和数量
        根据 Dashboard 表格的状态判断
        """
        await self.page.goto("https://hpaportal.com.au/HPAPB/TAS/Appointments/BookingDashboard")
        await asyncio.sleep(2)

        success_hours = {}

        for hour, requested in round_requests.items():
            # 等待该小时的状态不再是 Pending（最多等待60秒）
            max_wait_seconds = 60
            waited = 0
            status_text = ""

            while waited < max_wait_seconds:
                await self.page.reload()
                await asyncio.sleep(3)
                waited += 3

                rows = await self.page.query_selector_all('tbody tr')
                found = False

                for row in rows:
                    time_cell = await row.query_selector('td:nth-child(2)')
                    if time_cell:
                        time_text = await time_cell.inner_text()
                        match = re.search(r'(\d{2}):(\d{2})', time_text)
                        if match:
                            row_hour = int(match.group(1))
                            if row_hour == hour:
                                found = True
                                status_cell = await row.query_selector('td:nth-child(6) span')
                                if status_cell:
                                    status_text = await status_cell.inner_text()

                                    if "Pending" in status_text:
                                        self.log_console(f"⏳ 小时{hour:02d}: 状态为 Pending，等待3秒...")
                                        break
                                    else:
                                        req_cell = await row.query_selector('td:nth-child(3) span')
                                        book_cell = await row.query_selector('td:nth-child(4) span')

                                        req_val = int((await req_cell.inner_text()).strip() or 0) if req_cell else 0
                                        book_val = int((await book_cell.inner_text()).strip() or 0) if book_cell else 0

                                        if "Processed" in status_text:
                                            if req_val >= requested:
                                                success_hours[hour] = requested
                                                self.log_console(f"✅ 小时{hour:02d}: Processed - 成功预定{requested}个")
                                            elif req_val > 0:
                                                success_hours[hour] = req_val
                                                self.log_console(f"⚠️ 小时{hour:02d}: Processed - 部分成功，成功{req_val}/{requested}个")
                                            else:
                                                self.log_console(f"❌ 小时{hour:02d}: Processed - 全部失败")
                                        elif "Rejected" in status_text:
                                            if req_val >= requested:
                                                success_hours[hour] = requested
                                                self.log_console(f"✅ 小时{hour:02d}: Rejected - 但已成功{requested}个")
                                            elif req_val > 0:
                                                success_hours[hour] = req_val
                                                self.log_console(f"⚠️ 小时{hour:02d}: Rejected - 部分成功，成功{req_val}/{requested}个")
                                            else:
                                                self.log_console(f"❌ 小时{hour:02d}: Rejected - 全部失败")
                                        else:
                                            if req_val >= requested:
                                                success_hours[hour] = requested
                                                self.log_console(f"✅ 小时{hour:02d}: 成功预定{requested}个")
                                            elif req_val > 0:
                                                success_hours[hour] = req_val
                                                self.log_console(f"⚠️ 小时{hour:02d}: 部分成功，成功{req_val}/{requested}个")
                                            else:
                                                self.log_console(f"❌ 小时{hour:02d}: 预定失败")
                                        break

                if found and "Pending" not in status_text:
                    break
                elif not found:
                    self.log_console(f"⏳ 小时{hour:02d}: 未找到记录，等待3秒...")

            if waited >= max_wait_seconds:
                self.log_console(f"⚠️ 小时{hour:02d}: 等待超时，停止任务")
                self.state.is_running = False
                self._stop_flag = True
                self.log_system_gui("⏸️ 等待超时，任务已停止")
                self.log_console("⏸️ 等待超时，任务已停止")
                break

        return success_hours

    async def _run_booking(self):
        round_num = 0

        # 定时启动等待
        if hasattr(self.panel, '_scheduled_time') and self.panel._scheduled_time:
            now = datetime.now()
            if now < self.panel._scheduled_time:
                wait_seconds = (self.panel._scheduled_time - now).total_seconds()
                self.log_system_gui(f"⏰ 等待定时启动，还需 {wait_seconds:.0f} 秒")
                self.log_console(f"⏰ 等待定时启动，还需 {wait_seconds:.0f} 秒")
                await asyncio.sleep(wait_seconds)
                self.log_system_gui("⏰ 定时时间到，开始执行")
                self.log_console("⏰ 定时时间到，开始执行")

        while self.state.is_running and not self._stop_flag:
            remaining_total = sum(self.state.remaining_values.values())
            if remaining_total == 0:
                msg = f"🎉 全部完成 | 总需求: {self.total_needed} | 总预定: {self.total_booked}"
                self.log_system_gui(msg)
                self.log_console(msg)
                break

            round_num += 1
            before = self.state.remaining_values.copy()
            need_total = sum(before.values())

            # 先刷新页面获取最新数据
            await self._refresh_page()

            # 并发获取可用值
            hours_to_check = [h for h in before.keys() if before.get(h, 0) > 0]
            if not hours_to_check:
                await asyncio.sleep(self.state.refresh_interval)
                continue

            tasks = [self._get_available_value(hour) for hour in hours_to_check]
            available_results = await asyncio.gather(*tasks)

            # 填写有额度的小时
            round_requests = {}
            filled = 0
            for i, hour in enumerate(hours_to_check):
                need = before.get(hour, 0)
                available = available_results[i]
                if need > 0 and available > 0:
                    fill = min(need, available, 4)
                    if fill > 0 and await self._fill_request_value(hour, fill):
                        round_requests[hour] = fill
                        filled += fill

            booked_total = filled
            remain_total = need_total - booked_total

            self.log_console(f"第{round_num}轮 | 需要预定{need_total}个 | 实际预定{booked_total}个 | 剩余{remain_total}个")

            if filled > 0:
                if await self._click_submit():
                    self.log_console("📋 校验本轮提交结果...")

                    # 获取实际成功的小时
                    success_hours = await self._verify_round_submission(round_requests)

                    # 只扣除成功的小时
                    for h, amt in success_hours.items():
                        self.state.remaining_values[h] -= amt
                        self.total_booked += amt

                    remain_total = sum(self.state.remaining_values.values())
                    success_total = sum(success_hours.values())

                    if success_total > 0:
                        self.log_success_gui(f"✅ 第{round_num}轮 | 成功预定{success_total}个 | 剩余{remain_total}个")
                    else:
                        self.log_success_gui(f"❌ 第{round_num}轮 | 全部失败 | 剩余{remain_total}个")

                    # 返回预约页面，继续尝试所有剩余的小时
                    await self.page.goto("https://hpaportal.com.au/HPAPB/TAS/Appointments/Book")
                    await asyncio.sleep(0.5)
                else:
                    self.log_console(f"❌ 第{round_num}轮提交失败")
            else:
                # 无可用额度
                self.log_console(f"第{round_num}轮 | 无可用额度")

            # 等待间隔
            await asyncio.sleep(self.state.refresh_interval)

        self.state.is_running = False
        if self.panel:
            self.panel.on_booking_finished()


async def run_browser(controller):
    controller.playwright = await async_playwright().start()
    controller.browser = await controller.playwright.chromium.launch(headless=False)
    controller.context = await controller.browser.new_context()
    controller.page = await controller.context.new_page()

    controller.log_system_gui("🌐 浏览器已打开，请手动登录")
    controller.log_console("🌐 浏览器已打开，请手动登录")

    await controller.page.goto("https://hpaportal.com.au/HPAPB/TAS/Appointments/Book")

    try:
        await controller.page.wait_for_selector('.left-panel', timeout=300000)
        controller.log_system_gui("✅ 检测到预约页面")
        controller.log_console("✅ 检测到预约页面")
    except:
        controller.log_system_gui("❌ 等待超时")
        controller.log_console("❌ 等待超时")

    await asyncio.Event().wait()


def main():
    controller = BookingController()

    def run_async():
        controller.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(controller.loop)
        controller.loop.run_until_complete(run_browser(controller))

    browser_thread = threading.Thread(target=run_async, daemon=True)
    browser_thread.start()

    panel = ControlPanel(controller)
    controller.panel = panel
    panel.run()


if __name__ == "__main__":
    main()