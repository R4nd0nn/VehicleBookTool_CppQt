"""
Container Slot 预定工具 - 异步高性能版本
- 基于 async/await 异步架构
- 先并发检查Zone可用性，再批量执行
- 正确处理Confirm后的弹窗
- 校验预定结果（只确认Status为Confirmed的任务）
- GUI只显示关键信息
- 控制台输出每轮汇总信息
"""

import sys
import asyncio
import threading
import time
import tkinter as tk
from tkinter import ttk
from datetime import datetime, timedelta
from typing import List
from dataclasses import dataclass, field

from playwright.async_api import async_playwright

# 尝试打开控制台
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
            sys.stdout.flush()
    except:
        pass


@dataclass
class ContainerTask:
    container_id: str
    date: str
    zone: str
    task_type: str
    is_completed: bool = False


@dataclass
class BookingState:
    is_running: bool = False
    tasks: List[ContainerTask] = field(default_factory=list)
    refresh_interval: float = 3.0
    scheduled_time: datetime = None


class ControlPanel:
    def __init__(self, controller):
        self.controller = controller
        self.root = tk.Tk()
        self.root.title("Container Slot 预定系统")
        self.root.geometry("1000x850")
        self.root.configure(bg='#1e1e2f')

        self._scheduled_time = None
        self._schedule_timer = None
        self.task_frames = []

        self.setup_ui()

    def setup_ui(self):
        # 标题
        title = tk.Label(self.root, text="🚛 Container Slot 预定系统", font=("微软雅黑", 14, "bold"),
                         bg='#1e1e2f', fg='white')
        title.pack(pady=10)

        # 状态栏
        self.status_var = tk.StringVar(value="⚪ 空闲")
        status_label = tk.Label(self.root, textvariable=self.status_var, font=("微软雅黑", 10),
                                bg='#1e1e2f', fg='#888')
        status_label.pack(pady=5)

        # 页面状态
        self.page_status_var = tk.StringVar(value="🌐 等待浏览器...")
        page_status_label = tk.Label(self.root, textvariable=self.page_status_var, font=("微软雅黑", 9),
                                      bg='#1e1e2f', fg='#ff9800')
        page_status_label.pack(pady=2)

        # 配置区域
        config_frame = tk.Frame(self.root, bg='#1e1e2f', bd=1, relief=tk.GROOVE)
        config_frame.pack(fill='x', padx=10, pady=5)

        tk.Label(config_frame, text="⚙️ 配置", font=("微软雅黑", 10, "bold"),
                 bg='#1e1e2f', fg='white').pack(anchor='w', padx=5, pady=2)

        # 刷新周期
        refresh_row = tk.Frame(config_frame, bg='#1e1e2f')
        refresh_row.pack(fill='x', padx=5, pady=2)

        tk.Label(refresh_row, text="轮次间隔(秒):", bg='#1e1e2f', fg='white', width=12).pack(side=tk.LEFT)
        self.refresh_var = tk.StringVar(value="0.5")
        refresh_entry = tk.Entry(refresh_row, textvariable=self.refresh_var, width=8,
                                  bg='#2d2d3f', fg='white')
        refresh_entry.pack(side=tk.LEFT, padx=5)

        self.refresh_display = tk.Label(refresh_row, text="", bg='#1e1e2f', fg='#4caf50', font=("微软雅黑", 8))
        self.refresh_display.pack(side=tk.LEFT, padx=5)

        def on_refresh_change(*args):
            try:
                val = float(self.refresh_var.get())
                if val >= 0.1:
                    self.refresh_display.config(text=f"(当前: {val}秒)")
                else:
                    self.refresh_var.set("0.5")
                    self.refresh_display.config(text="(当前: 0.5秒)")
            except:
                pass

        self.refresh_var.trace_add("write", on_refresh_change)
        on_refresh_change()

        # 定时启动
        schedule_frame = tk.Frame(self.root, bg='#1e1e2f', bd=1, relief=tk.GROOVE)
        schedule_frame.pack(fill='x', padx=10, pady=5)

        tk.Label(schedule_frame, text="⏰ 定时启动", font=("微软雅黑", 10, "bold"),
                 bg='#1e1e2f', fg='white').pack(anchor='w', padx=5, pady=2)

        time_row = tk.Frame(schedule_frame, bg='#1e1e2f')
        time_row.pack(fill='x', padx=5, pady=2)

        tk.Label(time_row, text="开始时间:", bg='#1e1e2f', fg='white', width=10).pack(side=tk.LEFT)

        time_frame = tk.Frame(time_row, bg='#1e1e2f')
        time_frame.pack(side=tk.LEFT, padx=5)

        now = datetime.now()

        self.schedule_hour = tk.Spinbox(time_frame, from_=0, to=23, width=3,
                                         format="%02.0f", bg='#2d2d3f', fg='white')
        self.schedule_hour.pack(side=tk.LEFT)
        self.schedule_hour.delete(0, tk.END)
        self.schedule_hour.insert(0, f"{now.hour:02d}")

        tk.Label(time_frame, text=":", bg='#1e1e2f', fg='white').pack(side=tk.LEFT)

        self.schedule_minute = tk.Spinbox(time_frame, from_=0, to=59, width=3,
                                           format="%02.0f", bg='#2d2d3f', fg='white')
        self.schedule_minute.pack(side=tk.LEFT)
        self.schedule_minute.delete(0, tk.END)
        self.schedule_minute.insert(0, "00")

        tk.Label(time_frame, text=":", bg='#1e1e2f', fg='white').pack(side=tk.LEFT)

        self.schedule_second = tk.Spinbox(time_frame, from_=0, to=59, width=3,
                                           format="%02.0f", bg='#2d2d3f', fg='white')
        self.schedule_second.pack(side=tk.LEFT)
        self.schedule_second.delete(0, tk.END)
        self.schedule_second.insert(0, "00")

        self.schedule_btn = tk.Button(time_row, text="设置定时", command=self.set_schedule,
                                       bg='#2196f3', fg='white', font=("微软雅黑", 9), width=8)
        self.schedule_btn.pack(side=tk.LEFT, padx=10)

        self.schedule_status = tk.Label(time_row, text="", bg='#1e1e2f', fg='#ff9800', font=("微软雅黑", 8))
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

        # 任务列表区域
        tasks_label = tk.Label(self.root, text="📋 Container 任务列表", bg='#1e1e2f', fg='white', font=("微软雅黑", 10))
        tasks_label.pack(anchor='w', padx=10, pady=(10, 0))

        tasks_frame = tk.Frame(self.root, bg='#1e1e2f')
        tasks_frame.pack(fill='both', expand=True, padx=10, pady=5)

        canvas = tk.Canvas(tasks_frame, bg='#1e1e2f', highlightthickness=0)
        scrollbar = tk.Scrollbar(tasks_frame, orient="vertical", command=canvas.yview)
        self.scrollable_frame = tk.Frame(canvas, bg='#1e1e2f')

        self.scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 添加任务按钮
        add_btn_frame = tk.Frame(tasks_frame, bg='#1e1e2f')
        add_btn_frame.pack(pady=5)

        self.add_btn = tk.Button(add_btn_frame, text="➕ 添加任务", command=self.add_task,
                                  bg='#4caf50', fg='white', font=("微软雅黑", 9), width=10)
        self.add_btn.pack(side="left", padx=5)

        self.show_btn = tk.Button(add_btn_frame, text="📊 检查总计", command=self.show_total,
                                   bg='#ff9800', fg='white', font=("微软雅黑", 9), width=10)
        self.show_btn.pack(side="left", padx=5)

        # 添加第一个任务
        self.add_task()

        # 日志区域
        log_label = tk.Label(self.root, text="📋 预约记录", bg='#1e1e2f', fg='white', font=("微软雅黑", 9))
        log_label.pack(anchor='w', padx=10, pady=(10, 0))

        log_frame = tk.Frame(self.root, bg='#1e1e2f')
        log_frame.pack(fill='both', expand=True, padx=10, pady=5)

        self.log_text = tk.Text(log_frame, height=12, bg='#0d0d1a', fg='#0f0',
                                font=("Consolas", 9), wrap=tk.WORD)
        log_scroll = tk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.log_text.pack(side=tk.LEFT, fill='both', expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def log_success(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)

    def log_config(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)

    def add_task(self):
        task_frame = tk.Frame(self.scrollable_frame, bg='#2d2d3f', bd=1, relief=tk.GROOVE)
        task_frame.pack(fill="x", pady=2, padx=5)

        tk.Label(task_frame, text="Container:", bg='#2d2d3f', fg='white', width=10).pack(side="left", padx=5)
        container_var = tk.StringVar()
        container_entry = tk.Entry(task_frame, textvariable=container_var, width=16,
                                    bg='#1e1e2f', fg='white', insertbackground='white')
        container_entry.pack(side="left", padx=5)

        tk.Label(task_frame, text="日期:", bg='#2d2d3f', fg='white', width=5).pack(side="left", padx=5)
        date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        date_entry = tk.Entry(task_frame, textvariable=date_var, width=12,
                               bg='#1e1e2f', fg='white', insertbackground='white')
        date_entry.pack(side="left", padx=5)

        tk.Label(task_frame, text="Zone:", bg='#2d2d3f', fg='white', width=5).pack(side="left", padx=5)
        zone_var = tk.StringVar()
        zone_spin = tk.Spinbox(task_frame, from_=0, to=23, textvariable=zone_var, width=5,
                                bg='#1e1e2f', fg='white', buttonbackground='#2d2d3f')
        zone_spin.pack(side="left", padx=5)

        tk.Label(task_frame, text="Type:", bg='#2d2d3f', fg='white', width=5).pack(side="left", padx=5)
        type_var = tk.StringVar(value="Pick Up")
        type_combo = ttk.Combobox(task_frame, textvariable=type_var,
                                   values=["Pick Up", "Drop Off"], width=10, state="readonly")
        type_combo.pack(side="left", padx=5)

        del_btn = tk.Button(task_frame, text="✖", command=lambda: self.remove_task(task_frame),
                             bg='#f44336', fg='white', font=("微软雅黑", 8), width=2)
        del_btn.pack(side="left", padx=10)

        self.task_frames.append({
            'frame': task_frame,
            'container': container_var,
            'date': date_var,
            'zone': zone_var,
            'type': type_var
        })

    def remove_task(self, task_frame):
        task_frame.destroy()
        self.task_frames = [t for t in self.task_frames if t['frame'] != task_frame]

    def get_tasks(self) -> List[ContainerTask]:
        tasks = []
        for t in self.task_frames:
            container = t['container'].get().strip()
            date = t['date'].get().strip()
            zone = t['zone'].get().strip()
            task_type = t['type'].get().strip()
            if container and date and zone:
                tasks.append(ContainerTask(container, date, zone, task_type))
        return tasks

    def show_total(self):
        tasks = self.get_tasks()
        self.log_config(f"📊 当前共有 {len(tasks)} 个任务")

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
            self.log_config(f"✅ 已设置定时: {target_time.strftime('%Y-%m-%d %H:%M:%S')}")

            self._start_schedule_timer()
        except Exception as e:
            print(f"设置定时失败: {e}")

    def _start_schedule_timer(self):
        if self._schedule_timer:
            self.root.after_cancel(self._schedule_timer)

        now = datetime.now()
        if self._scheduled_time and now < self._scheduled_time:
            delay_ms = int((self._scheduled_time - now).total_seconds() * 1000)
            self._schedule_timer = self.root.after(delay_ms, self._on_schedule_timeout)

    def _on_schedule_timeout(self):
        self.log_config("⏰ 定时时间到，自动开始预约")
        self.start_clicked()

    def get_config(self):
        interval = float(self.refresh_var.get() or 0.5)
        if interval < 0.1:
            interval = 0.5
            self.refresh_var.set("0.5")
        return {
            'tasks': self.get_tasks(),
            'refresh_interval': interval,
            'scheduled_time': self._scheduled_time
        }

    def start_clicked(self):
        config = self.get_config()
        if len(config['tasks']) == 0:
            self.log_config("⚠️ 请至少添加一个任务")
            return

        self._scheduled_time = None
        if self._schedule_timer:
            self.root.after_cancel(self._schedule_timer)
            self._schedule_timer = None

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.schedule_btn.config(state=tk.DISABLED)
        self.add_btn.config(state=tk.DISABLED)
        self.show_btn.config(state=tk.DISABLED)
        self.update_status("🟢 运行中")

        self.log_config(f"📊 共 {len(config['tasks'])} 个任务, 间隔: {config['refresh_interval']}秒")

        if self.controller.loop is None:
            self.log_config("❌ 事件循环未启动")
            return

        asyncio.run_coroutine_threadsafe(
            self.controller.start_booking(config, self),
            self.controller.loop
        )

    def stop_clicked(self):
        if self.controller.loop:
            asyncio.run_coroutine_threadsafe(self.controller.stop(), self.controller.loop)
        self.stop_btn.config(state=tk.DISABLED)
        self.update_status("⚪ 已停止")

    def reset_clicked(self):
        if self.controller.loop:
            asyncio.run_coroutine_threadsafe(self.controller.reset(), self.controller.loop)
        for t in self.task_frames:
            t['frame'].destroy()
        self.task_frames.clear()
        self.add_task()
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.schedule_btn.config(state=tk.NORMAL)
        self.add_btn.config(state=tk.NORMAL)
        self.show_btn.config(state=tk.NORMAL)
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
        self.add_btn.config(state=tk.NORMAL)
        self.show_btn.config(state=tk.NORMAL)
        self.update_status("⚪ 空闲")

    def run(self):
        self.root.mainloop()


class BookingController:
    def __init__(self):
        self.state = BookingState()
        self.page = None
        self.browser = None
        self.context = None
        self.playwright = None
        self.loop = None
        self.panel = None
        self._stop_flag = False
        self.TARGET_URL = "https://vbs.1-stop.biz/SignIn.aspx"
        self._browser_ready = asyncio.Event()

    def log_console(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] {message}")
        sys.stdout.flush()

    def log_success_gui(self, message: str):
        if self.panel:
            self.panel.log_success(message)

    async def start_booking(self, config: dict, panel):
        self.panel = panel
        self.state.tasks = config['tasks']
        self.state.refresh_interval = config['refresh_interval']
        self.state.scheduled_time = config.get('scheduled_time')

        for task in self.state.tasks:
            task.is_completed = False

        self.state.is_running = True
        self._stop_flag = False

        self.log_console(f"配置加载: 共{len(self.state.tasks)}个任务, 间隔={self.state.refresh_interval}秒")

        # 等待浏览器就绪
        self.log_console("等待浏览器就绪...")
        try:
            await asyncio.wait_for(self._browser_ready.wait(), timeout=60)
        except asyncio.TimeoutError:
            self.log_console("❌ 等待浏览器超时")
            self.state.is_running = False
            return

        self.log_console("浏览器已就绪")
        await self._run_booking()

    async def stop(self):
        self._stop_flag = True
        self.state.is_running = False
        self.log_console("已停止")
        if self.page:
            try:
                await self.page.evaluate("() => window.stop()")
            except:
                pass

    async def reset(self):
        self._stop_flag = True
        self.state.is_running = False
        self.state.tasks = []

    async def _wait_for_target_page(self, timeout: int = 300):
        """等待目标页面加载"""
        self.log_console("等待目标页面加载...")
        self.log_console("请手动登录并导航到预约页面")

        if self.panel:
            self.panel.update_status("🌐 请登录并导航到预约页面")

        start_time = datetime.now()
        while (datetime.now() - start_time).seconds < timeout:
            if self._stop_flag:
                return False
            try:
                if await self._is_on_target_page():
                    self.log_console("✅ 检测到目标页面")
                    if self.panel:
                        self.panel.update_status("✅ 已在目标页面")
                    return True
            except:
                pass
            await asyncio.sleep(2)

        self.log_console("❌ 等待目标页面超时")
        return False

    async def _is_on_target_page(self) -> bool:
        try:
            has_containers = await self.page.locator("#tableContainers_IMPORT").count() > 0
            has_zones = await self.page.locator("#tableZoneSlotAvailability").count() > 0
            return has_containers and has_zones
        except:
            return False

    async def _select_date(self, target_date: str) -> bool:
        """选择日期"""
        try:
            target = datetime.strptime(target_date, "%Y-%m-%d")
            target_display = target.strftime("%d/%m/%Y")

            date_elements = await self.page.locator(".calendarbar-day").all()
            for elem in date_elements:
                date_text = await elem.inner_text()
                if target_display in date_text:
                    await elem.click()
                    await asyncio.sleep(0.3)
                    self.log_console(f"选择日期: {target_display}")
                    return True

            self.log_console(f"未找到日期: {target_display}")
            return False
        except Exception as e:
            self.log_console(f"选择日期失败: {e}")
            return False

    async def _select_container(self, container_id: str, task_type: str) -> bool:
        """选择Container"""
        try:
            if task_type == "Pick Up":
                row_id = f"BCSCntrRow_{container_id}_IMPORT"
            else:
                row_id = f"BCSCntrRow_{container_id}_EXPORT"

            container_row = self.page.locator(f"#{row_id}")
            if await container_row.count() == 0:
                self.log_console(f"未找到Container: {container_id}")
                return False

            await container_row.first.scroll_into_view_if_needed()
            await container_row.first.click()
            await asyncio.sleep(0.3)
            self.log_console(f"选择Container: {container_id}")
            return True
        except Exception as e:
            self.log_console(f"选择Container失败: {e}")
            return False

    async def _check_zone_availability(self, zone: str, task_type: str) -> bool:
        """检查Zone是否有可用Slot（检查是否有数字）"""
        try:
            await asyncio.sleep(0.1)

            row = self.page.locator(f"#tr_zone_{zone}")
            if await row.count() == 0:
                return False

            if task_type == "Pick Up":
                slots_cell = row.locator("td").nth(1)
            else:
                slots_cell = row.locator("td").nth(2)

            # 检查是否有 available_slots 类（表示有可用Slot，显示数字）
            available_slots = slots_cell.locator(".available_slots")
            if await available_slots.count() > 0:
                slots_text = await available_slots.first.inner_text()
                slots_count = int(slots_text.strip()) if slots_text.strip().isdigit() else 0
                self.log_console(f"Zone {zone} {task_type}: 有可用Slot，数量={slots_count}")
                return True

            self.log_console(f"Zone {zone} {task_type}: 无可用Slot")
            return False
        except Exception as e:
            self.log_console(f"检查Zone失败: {e}")
            return False

    async def _select_zone_slot(self, zone: str, task_type: str) -> bool:
        """点击Zone的Slot（点击有数字的格子）"""
        try:
            row = self.page.locator(f"#tr_zone_{zone}")
            if await row.count() == 0:
                return False

            if task_type == "Pick Up":
                slots_cell = row.locator("td").nth(1)
            else:
                slots_cell = row.locator("td").nth(2)

            # 点击有 available_slots 的格子
            slot_div = slots_cell.locator(".available_slots")
            if await slot_div.count() > 0:
                await slot_div.first.scroll_into_view_if_needed()
                await slot_div.first.click()
                await asyncio.sleep(0.5)
                self.log_console(f"点击Zone {zone} {task_type} 的Slot")
                return True
            return False
        except Exception as e:
            self.log_console(f"点击Slot失败: {e}")
            return False

    async def _click_confirm(self) -> bool:
        """点击Confirm按钮提交"""
        try:
            confirm_btn = self.page.locator("#Confirm")
            if await confirm_btn.count() > 0:
                await confirm_btn.first.scroll_into_view_if_needed()
                await confirm_btn.first.click()
                self.log_console("点击Confirm按钮")
                return True
            return False
        except Exception as e:
            self.log_console(f"点击Confirm失败: {e}")
            return False

    async def _verify_booking_results(self, expected_containers: List[str]) -> List[str]:
        """
        校验预定结果，返回真正成功的Container列表
        通过解析Summary弹窗中的状态来判断
        """
        try:
            # 等待弹窗中的表格加载
            await asyncio.sleep(1)

            # 查找确认表格
            table = self.page.locator("#BCS_CONFIRM_SUMMARY_LIST")
            if await table.count() == 0:
                self.log_console("未找到确认表格，无法校验结果")
                return []

            successful_containers = []

            # 遍历表格行
            rows = table.locator("tbody tr")
            row_count = await rows.count()

            for i in range(row_count):
                row = rows.nth(i)

                # 获取Container列（第7列，索引6）
                container_cell = row.locator("td").nth(6)
                container_id = await container_cell.inner_text()
                container_id = container_id.strip()

                # 获取Status列（第12列，索引11）
                status_cell = row.locator("td").nth(11)
                status = await status_cell.inner_text()
                status = status.strip()

                self.log_console(f"Container {container_id} 状态: {status}")

                # 只有Confirmed才算成功
                if status == "Confirmed" and container_id in expected_containers:
                    successful_containers.append(container_id)

            return successful_containers
        except Exception as e:
            self.log_console(f"校验预定结果失败: {e}")
            return []

    async def _handle_confirm_popup(self) -> bool:
        """处理Confirm后的弹窗，点击Continue Booking继续"""
        try:
            # 等待弹窗出现
            await asyncio.sleep(0.5)

            # 检查是否出现了Summary弹窗
            summary_dialog = self.page.locator("#BCSBookingSummary")
            if await summary_dialog.count() > 0:
                self.log_console("检测到Booking Summary弹窗")

                # 点击 Continue Booking 按钮
                continue_btn = self.page.locator("#CONTINUE_BOOKING")
                if await continue_btn.count() > 0:
                    await continue_btn.first.click()
                    self.log_console("点击 Continue Booking 按钮，继续预定")
                    await asyncio.sleep(1)
                    return True
                else:
                    self.log_console("未找到 Continue Booking 按钮")
                    close_btn = self.page.locator(".blockUI-close")
                    if await close_btn.count() > 0:
                        await close_btn.first.click()
                        self.log_console("点击关闭按钮")
                    return False
            return True
        except Exception as e:
            self.log_console(f"处理弹窗失败: {e}")
            return False

    async def _click_refresh(self) -> bool:
        """快速刷新页面"""
        try:
            refresh_btn = self.page.locator("#SlotsRefresh")
            if await refresh_btn.count() > 0:
                await refresh_btn.first.evaluate("element => element.click()")
                await asyncio.sleep(self.state.refresh_interval)
                return True
            else:
                await self.page.reload()
                await asyncio.sleep(self.state.refresh_interval)
                return True
        except Exception as e:
            self.log_console(f"刷新失败: {e}")
            await asyncio.sleep(self.state.refresh_interval)
            return False

    async def _run_booking(self):
        """主预约循环 - 正确顺序：先检查Zone → 有Slot再点Container → 点Select → 统一Confirm"""

        # 等待目标页面
        if not await self._wait_for_target_page():
            self.state.is_running = False
            return

        round_num = 0

        while self.state.is_running and not self._stop_flag:
            all_completed = all(t.is_completed for t in self.state.tasks)
            if all_completed:
                self.log_success_gui("🎉 所有Container预定完成！")
                break

            round_num += 1

            # 获取未完成的任务
            pending_tasks = [(idx, t) for idx, t in enumerate(self.state.tasks) if not t.is_completed]
            need_total = len(pending_tasks)

            # 记录本轮成功Select的任务
            selected_tasks = []

            # 先选择日期（只需一次）
            if pending_tasks:
                first_task = pending_tasks[0][1]
                if not await self._select_date(first_task.date):
                    self.log_console("日期选择失败")
                    break

            for idx, task in pending_tasks:
                if not self.state.is_running or self._stop_flag:
                    break

                self.log_console(f"处理任务: {task.container_id} | Zone {task.zone} | {task.task_type}")

                # 1. 先检查Zone是否有可用Slot（不点Container）
                if not await self._check_zone_availability(task.zone, task.task_type):
                    self.log_console(f"Zone {task.zone} 无可用Slot，跳过本轮")
                    continue

                self.log_console(f"Zone {task.zone} 有可用Slot，开始选择...")

                # 2. 选择Container
                if not await self._select_container(task.container_id, task.task_type):
                    self.log_console(f"选择Container失败，跳过本轮")
                    continue

                # 3. 点击Select按钮
                if await self._select_zone_slot(task.zone, task.task_type):
                    selected_tasks.append((idx, task))
                    self.log_console(f"✅ 已选中: {task.container_id}")
                else:
                    self.log_console(f"❌ 点击Select失败: {task.container_id}")

            # 4. 统一提交所有选中的任务
            if selected_tasks:
                self.log_console(f"点击Confirm提交 {len(selected_tasks)} 个任务...")
                if await self._click_confirm():
                    # 校验真正成功的Container
                    selected_containers = [task.container_id for _, task in selected_tasks]
                    verified_successful = await self._verify_booking_results(selected_containers)

                    # 处理弹窗
                    await self._handle_confirm_popup()

                    # 标记成功的任务
                    for idx, task in selected_tasks:
                        if task.container_id in verified_successful:
                            task.is_completed = True
                            self.log_success_gui(
                                f"✅ {task.container_id} | Zone {task.zone} | {task.task_type} 预定成功")
                else:
                    self.log_console("提交失败")

            # 计算剩余任务
            remaining_tasks = [t for t in self.state.tasks if not t.is_completed]
            remaining_total = len(remaining_tasks)

            # 输出本轮汇总
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            actual_success_count = need_total - remaining_total
            if actual_success_count > 0:
                successful_list = [t.container_id for t in self.state.tasks if t.is_completed]
                successful_containers_str = ", ".join(successful_list[-actual_success_count:])
                print(
                    f"[{timestamp}] 第{round_num}轮，需要预定{need_total}个，实际预定成功{actual_success_count}个，还需要预定{remaining_total}个。预定成功的container: {successful_containers_str}")
            else:
                print(
                    f"[{timestamp}] 第{round_num}轮，需要预定{need_total}个，实际预定成功0个，还需要预定{remaining_total}个。")
            sys.stdout.flush()

            # 刷新页面，准备下一轮
            if remaining_total > 0:
                await self._click_refresh()

        self.state.is_running = False
        if self.panel:
            self.panel.on_booking_finished()


async def run_browser(controller):
    """启动浏览器"""
    try:
        print("正在启动浏览器...")
        controller.playwright = await async_playwright().start()
        controller.browser = await controller.playwright.chromium.launch(headless=False)
        controller.context = await controller.browser.new_context()
        controller.page = await controller.context.new_page()

        await controller.page.goto(controller.TARGET_URL)

        print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 🌐 浏览器已启动")
        print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 📍 打开: {controller.TARGET_URL}")
        print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 🔐 请手动登录并导航到预约页面")
        print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 📍 目标页面特征: 有 #tableContainers_IMPORT 和 #tableZoneSlotAvailability")
        sys.stdout.flush()

        controller._browser_ready.set()

        while True:
            await asyncio.sleep(1)
    except Exception as e:
        print(f"浏览器启动失败: {e}")
        import traceback
        traceback.print_exc()
        controller._browser_ready.set()


def main():
    controller = BookingController()

    def run_async():
        try:
            controller.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(controller.loop)
            print("事件循环已启动")
            sys.stdout.flush()
            controller.loop.run_until_complete(run_browser(controller))
        except Exception as e:
            print(f"事件循环错误: {e}")
            import traceback
            traceback.print_exc()

    browser_thread = threading.Thread(target=run_async, daemon=True)
    browser_thread.start()

    time.sleep(2)

    panel = ControlPanel(controller)
    controller.panel = panel
    print("GUI已启动")
    sys.stdout.flush()
    panel.run()


if __name__ == "__main__":
    main()