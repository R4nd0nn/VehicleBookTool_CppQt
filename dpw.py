import sys
import time
import random
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import tkinter as tk
from tkinter import ttk, scrolledtext
import threading

# 兼容所有Playwright版本，仅保留核心功能
from playwright.sync_api import sync_playwright


# ===================== 数据模型 =====================
@dataclass
class ContainerTask:
    """单个Container的预定任务"""
    container_id: str  # 集装箱ID，如 "CIPU5141185"
    date: str  # 日期，格式 YYYY-MM-DD
    zone: str  # Zone（小时），如 "3"
    task_type: str  # "Pick Up" 或 "Drop Off"
    is_completed: bool = False  # 是否已完成预定


@dataclass
class BookingState:
    """预定状态管理类"""
    is_running: bool = False
    is_paused: bool = False
    tasks: List[ContainerTask] = field(default_factory=list)  # 所有任务
    refresh_seconds: float = 3.0  # 刷新周期，默认3秒
    scheduled_time: datetime = None  # 任务开始时间


# 初始化全局状态
global_state = BookingState()


# ===================== 页面控制器 =====================
class PageController:
    def __init__(self, url: str):
        self.url = url
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._init_browser()

    def _init_browser(self):
        """初始化浏览器"""
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=False)
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.goto(self.url)
        print("✅ 浏览器已启动")

    def get_current_page(self):
        """获取当前活动页面"""
        try:
            pages = self.context.pages
            if pages:
                self.page = pages[-1]
            return self.page
        except:
            return self.page

    def select_container(self, container_id: str, task_type: str) -> bool:
        """
        选择Container
        根据type决定在Pick Up还是Drop Off区域查找
        """
        try:
            current_page = self.get_current_page()

            # 根据type确定要点击的行
            if task_type == "Pick Up":
                # 在Pick Up区域查找
                row_id = f"BCSCntrRow_{container_id}_IMPORT"
            else:  # Drop Off
                row_id = f"BCSCntrRow_{container_id}_EXPORT"

            container_row = current_page.locator(f"#{row_id}")

            if container_row.count() == 0:
                print(f"未找到Container: {container_id} (type: {task_type})")
                return False

            if container_row.first.is_visible():
                container_row.first.scroll_into_view_if_needed()
                container_row.first.click()
                print(f"✅ 选择Container: {container_id}")
                time.sleep(1)  # 等待选中效果
                return True
            else:
                print(f"Container不可见: {container_id}")
                return False

        except Exception as e:
            print(f"❌ 选择Container失败: {e}")
            return False

    def select_date(self, target_date: str) -> bool:
        """
        选择目标日期
        输入格式: YYYY-MM-DD，例如 2026-03-07
        页面显示格式: DD/MM/YYYY，例如 07/03/2026
        """
        try:
            current_page = self.get_current_page()

            # 转换日期格式
            target = datetime.strptime(target_date, "%Y-%m-%d")
            target_display = target.strftime("%d/%m/%Y")  # 转换为 DD/MM/YYYY

            # 查找日历中的日期元素
            date_elements = current_page.locator(".calendarbar-day")
            count = date_elements.count()

            for i in range(count):
                date_text = date_elements.nth(i).inner_text().strip()
                if target_display in date_text:
                    date_elements.nth(i).click()
                    print(f"✅ 选择日期: {target_display}")
                    time.sleep(1.5)  # 等待页面加载
                    return True

            print(f"⚠️ 未找到日期: {target_display}")
            return False

        except Exception as e:
            print(f"❌ 选择日期失败: {e}")
            return False

    def check_zone_availability(self, zone: str, task_type: str) -> bool:
        """
        检查指定Zone的指定类型是否有可用Slot
        返回True表示有可用Slot（显示Select按钮）
        """
        try:
            current_page = self.get_current_page()

            # 找到Zone对应的行
            row = current_page.locator(f"#tr_zone_{zone}")
            if row.count() == 0:
                print(f"未找到Zone: {zone}")
                return False

            # 根据type确定要检查的列
            if task_type == "Pick Up":
                # Pick Up slots在第2列
                slots_cell = row.locator("td").nth(1)
            else:  # Drop Off
                # Drop Off slots在第3列
                slots_cell = row.locator("td").nth(2)

            # 检查是否有slots_highlighted类（表示有Select按钮）
            has_select = slots_cell.locator(".slots_highlighted").count() > 0

            if has_select:
                print(f"Zone {zone} {task_type}: 有可用Slot")
                return True
            else:
                print(f"Zone {zone} {task_type}: 无可用Slot")
                return False

        except Exception as e:
            print(f"❌ 检查Zone可用性失败: {e}")
            return False

    def select_zone_slot(self, zone: str, task_type: str) -> bool:
        """
        点击Zone的Select按钮
        """
        try:
            current_page = self.get_current_page()

            # 找到Zone对应的行
            row = current_page.locator(f"#tr_zone_{zone}")
            if row.count() == 0:
                return False

            # 根据type确定要点击的列
            if task_type == "Pick Up":
                slots_cell = row.locator("td").nth(1)
            else:
                slots_cell = row.locator("td").nth(2)

            # 找到Select按钮并点击
            select_btn = slots_cell.locator(".slots_highlighted")
            if select_btn.count() > 0 and select_btn.first.is_visible():
                select_btn.first.scroll_into_view_if_needed()
                select_btn.first.click()
                print(f"✅ 点击Zone {zone} {task_type} 的Select按钮")
                time.sleep(1)
                return True
            else:
                print(f"Zone {zone} {task_type}: 未找到Select按钮")
                return False

        except Exception as e:
            print(f"❌ 点击Select按钮失败: {e}")
            return False

    def click_click_button(self) -> bool:
        """点击id为Click的按钮"""
        try:
            current_page = self.get_current_page()

            click_btn = current_page.locator("#Confirm")
            if click_btn.count() > 0 and click_btn.first.is_visible():
                click_btn.first.scroll_into_view_if_needed()
                click_btn.first.click()
                print("✅ 点击Confirm按钮")
                time.sleep(2)  # 等待提交完成
                return True
            else:
                print("❌ 未找到Confirm按钮")
                return False

        except Exception as e:
            print(f"❌ 点击Confirm按钮失败: {e}")
            return False

    def click_refresh_button(self) -> bool:
        """点击SlotsRefresh刷新按钮"""
        try:
            current_page = self.get_current_page()

            refresh_btn = current_page.locator("#SlotsRefresh")
            if refresh_btn.count() > 0 and refresh_btn.first.is_visible():
                refresh_btn.first.click()
                print("✅ 点击SlotsRefresh按钮")
                time.sleep(global_state.refresh_seconds)  # 使用用户设置的刷新周期
                return True
            else:
                print("❌ 未找到SlotsRefresh按钮")
                return False

        except Exception as e:
            print(f"❌ 点击刷新按钮失败：{e}")
            return False

    def is_on_target_page(self) -> bool:
        """检查是否在目标页面"""
        try:
            current_page = self.get_current_page()
            # 检查是否存在Container表格和Zone表格
            has_containers = current_page.locator("#tableContainers_IMPORT").count() > 0
            has_zones = current_page.locator("#tableZoneSlotAvailability").count() > 0
            return has_containers and has_zones
        except:
            return False

    def close_browser(self):
        """关闭浏览器"""
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
            print("✅ 浏览器已关闭")
        except Exception as e:
            print(f"❌ 关闭浏览器时出错：{e}")


# ===================== 预定控制器 =====================
class BookingController:
    def __init__(self, page_ctrl, log_callback, status_callback):
        self.page_ctrl = page_ctrl
        self.log = log_callback
        self.update_status = status_callback
        self.current_task_index = 0
        self.round_completed_tasks = []  # 本轮已成功Select的task索引
        self.round_count = 1
        self.state = "IDLE"  # IDLE, RUNNING, PAUSED, WAITING_SCHEDULE
        self.scheduled_time = None
        self.root = None

    def start_with_schedule(self, scheduled_time: datetime):
        """设置定时启动"""
        self.scheduled_time = scheduled_time
        self.state = "WAITING_SCHEDULE"

        # 计算等待时间
        now = datetime.now()
        if scheduled_time > now:
            wait_seconds = (scheduled_time - now).total_seconds()
            wait_minutes = int(wait_seconds // 60)
            wait_seconds_remain = int(wait_seconds % 60)
            self.log(f"⏰ 任务开始时间: {scheduled_time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.log(f"⏳ 距离开始还有: {wait_minutes}分{wait_seconds_remain}秒")

            # 启动定时器线程
            timer_thread = threading.Thread(target=self._schedule_wait, args=(wait_seconds,))
            timer_thread.daemon = True
            timer_thread.start()
        else:
            self.log("⚠️ 任务开始时间已过，立即开始")
            self.root.after(100, self._start_booking)

    def _schedule_wait(self, wait_seconds):
        """等待定时时间"""
        time.sleep(wait_seconds)
        if self.state == "WAITING_SCHEDULE":
            self.log("⏰ 任务开始时间到，开始执行预定任务")
            self.root.after(0, self._start_booking)

    def _start_booking(self):
        """开始预定流程的内部方法"""
        # 检查是否有任务
        if len(global_state.tasks) == 0:
            self.log("⚠️ 没有需要预定的Container任务")
            self.state = "IDLE"
            self.update_status(False, False)
            return

        self.log(f"📋 共有 {len(global_state.tasks)} 个Container任务")

        self.state = "RUNNING"
        self.current_task_index = 0
        self.round_completed_tasks = []
        self.round_count = 1
        self.log(f"\n{'=' * 50}")
        self.log(f"第 {self.round_count} 轮预定开始")

        # 开始第一轮
        self.root.after(100, self._process_next)

    def start(self):
        """立即开始预定流程"""
        if self.state != "IDLE":
            return

        self._start_booking()

    def pause(self):
        """暂停"""
        self.state = "PAUSED"
        self.log("⏸️ 已暂停")

    def resume(self):
        """继续"""
        if self.state == "PAUSED":
            self.state = "RUNNING"
            self.log("▶️ 继续运行")
            self.root.after(100, self._process_next)

    def reset(self):
        """重置"""
        self.state = "IDLE"
        self.current_task_index = 0
        self.round_completed_tasks = []
        self.round_count = 1
        self.scheduled_time = None
        self.log("🔄 已重置")
        self.update_status(False, False)

    def _process_next(self):
        """处理下一个步骤"""
        if self.state != "RUNNING":
            return

        # 检查是否在正确的页面
        if not self.page_ctrl.is_on_target_page():
            self.log("⚠️ 当前不在目标页面，等待跳转...")
            self.root.after(3000, self._process_next)
            return

        # 检查是否所有任务都已完成
        all_completed = all(task.is_completed for task in global_state.tasks)
        if all_completed:
            self.log("\n🎉 所有Container预定完成！")
            self.state = "IDLE"
            self.update_status(False, False)
            return

        # 如果当前任务索引超出范围，说明本轮所有任务处理完毕
        if self.current_task_index >= len(global_state.tasks):
            self._finish_round()
            return

        # 处理当前任务
        self._process_task()

    def _process_task(self):
        """处理单个任务"""
        task = global_state.tasks[self.current_task_index]

        # 如果任务已完成，跳过
        if task.is_completed:
            self.current_task_index += 1
            self._process_next()  # 直接递归，减少延迟
            return

        self.log(f"\n--- 处理任务 {self.current_task_index + 1}/{len(global_state.tasks)} ---")
        self.log(f"Container: {task.container_id}, Date: {task.date}, Zone: {task.zone}, Type: {task.task_type}")

        try:
            # 1. 选择Container
            self.log("🔄 选择Container...")
            if not self.page_ctrl.select_container(task.container_id, task.task_type):
                self.log(f"❌ 选择Container失败，跳过本轮")
                self.current_task_index += 1
                self._process_next()  # 直接递归
                return

            # 2. 选择日期
            self.log("🔄 选择日期...")
            if not self.page_ctrl.select_date(task.date):
                self.log(f"❌ 选择日期失败，跳过本轮")
                self.current_task_index += 1
                self._process_next()  # 直接递归
                return

            # 3. 检查Zone是否有可用Slot
            self.log("🔄 检查Zone可用性...")
            if not self.page_ctrl.check_zone_availability(task.zone, task.task_type):
                self.log(f"⏭️ Zone {task.zone} 当前无可用Slot，等待下一轮")
                self.current_task_index += 1
                self._process_next()  # 直接递归
                return

            # 4. 点击Select按钮
            self.log("🔄 点击Select按钮...")
            if self.page_ctrl.select_zone_slot(task.zone, task.task_type):
                self.log(f"✅ 任务成功: {task.container_id} 已选择Slot")
                # 记录本轮成功的任务
                self.round_completed_tasks.append(self.current_task_index)
            else:
                self.log(f"❌ 点击Select失败")

            self.current_task_index += 1
            self._process_next()  # 直接递归

        except Exception as e:
            self.log(f"⚠️ 任务处理异常: {str(e)[:50]}")
            self.current_task_index += 1
            # 异常情况保留一点延迟
            self.root.after(1000, self._process_next)

    def _finish_round(self):
        """完成本轮预定"""
        # 本轮有成功任务吗？
        if len(self.round_completed_tasks) > 0:
            self.log(f"\n📤 本轮有 {len(self.round_completed_tasks)} 个任务成功，点击Confirm按钮提交...")

            # 点击Confirm按钮
            if self.page_ctrl.click_click_button():
                self.log("✅ 提交成功")

                # 标记本轮成功的任务为已完成
                for idx in self.round_completed_tasks:
                    global_state.tasks[idx].is_completed = True
                    self.log(f"📝 任务完成: {global_state.tasks[idx].container_id}")
            else:
                self.log("⚠️ 点击Confirm失败，本轮任务可能未生效")
        else:
            self.log("⚠️ 本轮没有成功的任务")

        # 计算剩余任务
        remaining = sum(1 for t in global_state.tasks if not t.is_completed)
        self.log(f"📊 本轮完成，剩余 {remaining} 个任务")

        # 点击Refresh按钮刷新
        self.log("🔄 点击SlotsRefresh刷新页面...")
        self.page_ctrl.click_refresh_button()
        self.log("✅ 页面刷新完成")

        # 重置本轮计数器
        self.current_task_index = 0
        self.round_completed_tasks = []
        self.round_count += 1

        if remaining > 0:
            self.log(f"\n{'=' * 50}")
            self.log(f"第 {self.round_count} 轮预定开始")
            self.root.after(1000, self._process_next)
        else:
            self.log("\n🎉 所有任务完成！")
            self.state = "IDLE"
            self.update_status(False, False)


# ===================== Tkinter GUI =====================
class BookingGUI:
    def __init__(self, root, page_ctrl):
        self.root = root
        self.page_ctrl = page_ctrl
        self.root.title("Container Slot 预定工具")
        self.root.geometry("1000x850")

        self.task_frames = []  # 存储每个任务的Frame和变量
        self.controller = None
        self.init_ui()

    def init_ui(self):
        """初始化GUI控件"""
        title_frame = ttk.Frame(self.root)
        title_frame.pack(pady=5, fill="x")
        ttk.Label(title_frame, text="⚡ Container Slot 预定系统 ⚡", font=("Arial", 14, "bold")).pack()

        # 状态显示
        status_frame = ttk.Frame(self.root)
        status_frame.pack(pady=2, fill="x", padx=20)
        self.page_status_var = tk.StringVar(value="页面状态: 检测中...")
        ttk.Label(status_frame, textvariable=self.page_status_var, foreground="blue").pack(side="left")

        # 定时状态显示
        self.schedule_status_var = tk.StringVar(value="")
        ttk.Label(status_frame, textvariable=self.schedule_status_var, foreground="green").pack(side="right", padx=10)

        # 设置区域
        settings_frame = ttk.LabelFrame(self.root, text="全局设置")
        settings_frame.pack(pady=8, padx=20, fill="x")

        # 刷新周期设置
        refresh_row = ttk.Frame(settings_frame)
        refresh_row.pack(pady=5, fill="x")

        ttk.Label(refresh_row, text="刷新周期：", width=10).pack(side="left", padx=5)

        self.refresh_var = tk.StringVar(value="3.0")
        refresh_spinbox = ttk.Spinbox(
            refresh_row,
            from_=0.5,
            to=30.0,
            increment=0.5,
            textvariable=self.refresh_var,
            width=10
        )
        refresh_spinbox.pack(side="left", padx=5)

        ttk.Label(refresh_row, text="秒", foreground="blue").pack(side="left")

        # 验证刷新周期输入
        def validate_refresh(*args):
            try:
                value = float(self.refresh_var.get())
                if value >= 0.5:
                    global_state.refresh_seconds = value
                else:
                    self.refresh_var.set("3.0")
                    global_state.refresh_seconds = 3.0
            except:
                self.refresh_var.set("3.0")
                global_state.refresh_seconds = 3.0

        self.refresh_var.trace_add("write", validate_refresh)

        # 新增：任务开始时间设置
        schedule_frame = ttk.LabelFrame(self.root, text="任务开始时间设置")
        schedule_frame.pack(pady=8, padx=20, fill="x")

        # 任务开始日期
        start_date_row = ttk.Frame(schedule_frame)
        start_date_row.pack(pady=5, fill="x")

        ttk.Label(start_date_row, text="开始日期：", width=10).pack(side="left", padx=5)

        # 获取当前日期作为默认值
        today = datetime.now().strftime("%Y-%m-%d")
        self.start_date_var = tk.StringVar(value=today)
        start_date_entry = ttk.Entry(start_date_row, textvariable=self.start_date_var, width=15)
        start_date_entry.pack(side="left", padx=5)

        ttk.Label(start_date_row, text="格式：YYYY-MM-DD", foreground="blue").pack(side="left", padx=5)

        # 任务开始时间
        start_time_row = ttk.Frame(schedule_frame)
        start_time_row.pack(pady=5, fill="x")

        ttk.Label(start_time_row, text="开始时间：", width=10).pack(side="left", padx=5)

        # 获取当前时间
        now = datetime.now()

        # 小时选择
        self.hour_var = tk.StringVar(value=f"{now.hour:02d}")
        hour_spin = ttk.Spinbox(start_time_row, from_=0, to=23, textvariable=self.hour_var, width=4, format="%02.0f")
        hour_spin.pack(side="left", padx=2)
        ttk.Label(start_time_row, text="时").pack(side="left")

        # 分钟选择
        self.minute_var = tk.StringVar(value="00")
        minute_spin = ttk.Spinbox(start_time_row, from_=0, to=59, textvariable=self.minute_var, width=4,
                                  format="%02.0f")
        minute_spin.pack(side="left", padx=2)
        ttk.Label(start_time_row, text="分").pack(side="left")

        # 秒选择
        self.second_var = tk.StringVar(value="00")
        second_spin = ttk.Spinbox(start_time_row, from_=0, to=59, textvariable=self.second_var, width=4,
                                  format="%02.0f")
        second_spin.pack(side="left", padx=2)
        ttk.Label(start_time_row, text="秒").pack(side="left")

        # 快速设置按钮
        quick_time_frame = ttk.Frame(schedule_frame)
        quick_time_frame.pack(pady=5)

        ttk.Button(quick_time_frame, text="现在时间", command=self.set_current_time, width=10).pack(side="left", padx=5)
        ttk.Button(quick_time_frame, text="5分钟后", command=self.set_5min_later, width=10).pack(side="left", padx=5)
        ttk.Button(quick_time_frame, text="10分钟后", command=self.set_10min_later, width=10).pack(side="left", padx=5)
        ttk.Button(quick_time_frame, text="30分钟后", command=self.set_30min_later, width=10).pack(side="left", padx=5)

        # 任务列表区域
        tasks_frame = ttk.LabelFrame(self.root, text="Container任务列表")
        tasks_frame.pack(pady=8, padx=20, fill="both", expand=1)

        # 滚动画布
        canvas = tk.Canvas(tasks_frame)
        scrollbar = ttk.Scrollbar(tasks_frame, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 添加任务按钮
        add_btn_frame = ttk.Frame(tasks_frame)
        add_btn_frame.pack(pady=5)

        ttk.Button(add_btn_frame, text="➕ 添加任务", command=self.add_task).pack(side="left", padx=5)
        ttk.Button(add_btn_frame, text="检查总计", command=self.show_total).pack(side="left", padx=5)

        # 添加第一个任务
        self.add_task()

        # 控制按钮
        btn_frame = ttk.LabelFrame(self.root, text="控制面板")
        btn_frame.pack(pady=8, padx=20, fill="x")

        button_container = ttk.Frame(btn_frame)
        button_container.pack(pady=10)

        self.schedule_btn = ttk.Button(button_container, text="⏰ 定时启动", command=self.schedule_booking, width=10)
        self.schedule_btn.pack(side="left", padx=5)

        self.immediate_btn = ttk.Button(button_container, text="⚡ 立即开始", command=self.start_booking, width=8)
        self.immediate_btn.pack(side="left", padx=5)

        self.pause_btn = ttk.Button(button_container, text="⏸️ 暂停", command=self.pause_booking, state="disabled",
                                    width=8)
        self.pause_btn.pack(side="left", padx=5)

        self.resume_btn = ttk.Button(button_container, text="▶ 继续", command=self.resume_booking, state="disabled",
                                     width=8)
        self.resume_btn.pack(side="left", padx=5)

        self.reset_btn = ttk.Button(button_container, text="🔄 重置", command=self.reset_booking, width=8)
        self.reset_btn.pack(side="left", padx=5)

        # 日志面板
        log_frame = ttk.LabelFrame(self.root, text="运行日志")
        log_frame.pack(pady=8, padx=20, fill="both", expand=1)

        log_control_frame = ttk.Frame(log_frame)
        log_control_frame.pack(fill="x", padx=5, pady=2)

        ttk.Button(log_control_frame, text="清除日志", command=self.clear_log).pack(side="right")

        self.log_text = scrolledtext.ScrolledText(log_frame, state="disabled", height=10,
                                                  font=("Consolas", 9), wrap=tk.WORD)
        self.log_text.pack(fill="both", expand=1, padx=5, pady=5)

    def set_current_time(self):
        """设置为当前时间"""
        now = datetime.now()
        self.start_date_var.set(now.strftime("%Y-%m-%d"))
        self.hour_var.set(f"{now.hour:02d}")
        self.minute_var.set(f"{now.minute:02d}")
        self.second_var.set(f"{now.second:02d}")

    def set_5min_later(self):
        """设置为5分钟后"""
        later = datetime.now() + timedelta(minutes=5)
        self.start_date_var.set(later.strftime("%Y-%m-%d"))
        self.hour_var.set(f"{later.hour:02d}")
        self.minute_var.set(f"{later.minute:02d}")
        self.second_var.set(f"{later.second:02d}")

    def set_10min_later(self):
        """设置为10分钟后"""
        later = datetime.now() + timedelta(minutes=10)
        self.start_date_var.set(later.strftime("%Y-%m-%d"))
        self.hour_var.set(f"{later.hour:02d}")
        self.minute_var.set(f"{later.minute:02d}")
        self.second_var.set(f"{later.second:02d}")

    def set_30min_later(self):
        """设置为30分钟后"""
        later = datetime.now() + timedelta(minutes=30)
        self.start_date_var.set(later.strftime("%Y-%m-%d"))
        self.hour_var.set(f"{later.hour:02d}")
        self.minute_var.set(f"{later.minute:02d}")
        self.second_var.set(f"{later.second:02d}")

    def get_scheduled_datetime(self):
        """获取设置的定时开始时间"""
        try:
            # 使用任务开始日期
            date_str = self.start_date_var.get().strip()
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")

            # 获取时间
            hour = int(self.hour_var.get())
            minute = int(self.minute_var.get())
            second = int(self.second_var.get())

            # 组合成完整的datetime
            return datetime(date_obj.year, date_obj.month, date_obj.day, hour, minute, second)
        except ValueError as e:
            self.add_log(f"❌ 任务开始时间格式错误: {e}")
            return None

    def add_task(self):
        """添加一个新的任务输入行"""
        task_frame = ttk.Frame(self.scrollable_frame)
        task_frame.pack(fill="x", pady=2, padx=5)

        # Container ID
        ttk.Label(task_frame, text="Container:", width=10).pack(side="left", padx=2)
        container_var = tk.StringVar()
        container_entry = ttk.Entry(task_frame, textvariable=container_var, width=15)
        container_entry.pack(side="left", padx=2)

        # Date
        ttk.Label(task_frame, text="日期:", width=4).pack(side="left", padx=2)
        date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        date_entry = ttk.Entry(task_frame, textvariable=date_var, width=12)
        date_entry.pack(side="left", padx=2)

        # Zone
        ttk.Label(task_frame, text="Zone:", width=4).pack(side="left", padx=2)
        zone_var = tk.StringVar()
        zone_spin = ttk.Spinbox(task_frame, from_=0, to=23, textvariable=zone_var, width=5)
        zone_spin.pack(side="left", padx=2)

        # Type
        ttk.Label(task_frame, text="Type:", width=4).pack(side="left", padx=2)
        type_var = tk.StringVar(value="Pick Up")
        type_combo = ttk.Combobox(task_frame, textvariable=type_var,
                                  values=["Pick Up", "Drop Off"], width=10, state="readonly")
        type_combo.pack(side="left", padx=2)

        # 删除按钮
        ttk.Button(task_frame, text="✖", command=lambda f=task_frame: self.remove_task(f), width=2).pack(side="left",
                                                                                                         padx=5)

        # 保存变量
        self.task_frames.append({
            'frame': task_frame,
            'container': container_var,
            'date': date_var,
            'zone': zone_var,
            'type': type_var
        })

    def remove_task(self, task_frame):
        """删除任务"""
        task_frame.destroy()
        # 从列表中移除
        for i, task_dict in enumerate(self.task_frames):
            if task_dict['frame'] == task_frame:
                self.task_frames.pop(i)
                break

    def get_tasks_from_gui(self) -> List[ContainerTask]:
        """从GUI获取任务列表"""
        tasks = []
        for task_vars in self.task_frames:
            container = task_vars['container'].get().strip()
            date = task_vars['date'].get().strip()
            zone = task_vars['zone'].get().strip()
            task_type = task_vars['type'].get().strip()

            if container and date and zone:
                tasks.append(ContainerTask(
                    container_id=container,
                    date=date,
                    zone=zone,
                    task_type=task_type
                ))
        return tasks

    def add_log(self, msg):
        """追加日志"""
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        self.root.update()

    def clear_log(self):
        """清除日志"""
        self.log_text.config(state="normal")
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state="disabled")
        self.add_log("📋 日志已清除")

    def show_total(self):
        """显示总计任务数"""
        tasks = self.get_tasks_from_gui()
        self.add_log(f"📊 当前共有 {len(tasks)} 个任务")

    def check_page(self):
        """检查页面状态"""
        if self.page_ctrl.is_on_target_page():
            self.page_status_var.set("页面状态: ✅ 在目标页面")
            self.add_log("✅ 当前在目标页面")
        else:
            self.page_status_var.set("页面状态: ❌ 不在目标页面")
            self.add_log("⚠️ 当前不在目标页面")

    def update_buttons(self, is_running, is_paused):
        """更新按钮状态"""
        if is_running and not is_paused:
            self.schedule_btn.config(state="disabled")
            self.immediate_btn.config(state="disabled")
            self.pause_btn.config(state="normal")
            self.resume_btn.config(state="disabled")
            self.reset_btn.config(state="normal")
        elif is_running and is_paused:
            self.schedule_btn.config(state="disabled")
            self.immediate_btn.config(state="disabled")
            self.pause_btn.config(state="disabled")
            self.resume_btn.config(state="normal")
            self.reset_btn.config(state="normal")
        else:
            self.schedule_btn.config(state="normal")
            self.immediate_btn.config(state="normal")
            self.pause_btn.config(state="disabled")
            self.resume_btn.config(state="disabled")
            self.reset_btn.config(state="normal")
            self.schedule_status_var.set("")

    def schedule_booking(self):
        """定时启动预定"""
        tasks = self.get_tasks_from_gui()
        if len(tasks) == 0:
            self.add_log("⚠️ 请至少添加一个任务")
            return

        # 验证日期格式
        for task in tasks:
            try:
                datetime.strptime(task.date, "%Y-%m-%d")
            except:
                self.add_log(f"❌ 日期格式错误: {task.date}，应为 YYYY-MM-DD")
                return

        # 获取任务开始时间
        scheduled_time = self.get_scheduled_datetime()
        if not scheduled_time:
            return

        global_state.tasks = tasks

        # 创建控制器
        self.controller = BookingController(
            self.page_ctrl,
            self.add_log,
            self.update_buttons
        )
        self.controller.root = self.root

        global_state.is_running = True
        global_state.is_paused = False
        self.update_buttons(True, False)

        # 更新定时状态显示
        self.schedule_status_var.set(f"⏰ 任务开始: {scheduled_time.strftime('%Y-%m-%d %H:%M:%S')}")

        self.controller.start_with_schedule(scheduled_time)
        self.add_log("🚀 定时任务已设置")
        self.add_log(f"📋 共有 {len(tasks)} 个任务")
        self.add_log(f"⏰ 任务开始时间: {scheduled_time.strftime('%Y-%m-%d %H:%M:%S')}")

    def start_booking(self):
        """立即开始预定"""
        tasks = self.get_tasks_from_gui()
        if len(tasks) == 0:
            self.add_log("⚠️ 请至少添加一个任务")
            return

        # 验证日期格式
        for task in tasks:
            try:
                datetime.strptime(task.date, "%Y-%m-%d")
            except:
                self.add_log(f"❌ 日期格式错误: {task.date}，应为 YYYY-MM-DD")
                return

        global_state.tasks = tasks

        # 创建控制器
        self.controller = BookingController(
            self.page_ctrl,
            self.add_log,
            self.update_buttons
        )
        self.controller.root = self.root

        global_state.is_running = True
        global_state.is_paused = False
        self.update_buttons(True, False)

        self.controller.start()
        self.add_log("🚀 立即启动预定流程")
        self.add_log(f"📋 共有 {len(tasks)} 个任务")

    def pause_booking(self):
        """暂停预定"""
        if self.controller:
            self.controller.pause()
            global_state.is_paused = True
            self.update_buttons(True, True)

    def resume_booking(self):
        """继续预定"""
        if self.controller:
            self.controller.resume()
            global_state.is_paused = False
            self.update_buttons(True, False)

    def reset_booking(self):
        """重置预定"""
        if self.controller:
            self.controller.reset()
        global_state.is_running = False
        global_state.is_paused = False
        self.update_buttons(False, False)


# ===================== 主程序 =====================
if __name__ == "__main__":
    TARGET_URL = "https://vbs.1-stop.biz/SignIn.aspx"  # 替换为实际URL

    try:
        print("正在启动浏览器...")
        page_controller = PageController(TARGET_URL)
    except Exception as e:
        print(f"❌ 浏览器启动失败：{e}")
        sys.exit(1)

    root = tk.Tk()
    app = BookingGUI(root, page_controller)


    def on_close():
        print("\n正在关闭程序...")
        if app.controller:
            app.controller.reset()
        page_controller.close_browser()
        root.destroy()


    root.protocol("WM_DELETE_WINDOW", on_close)

    print("✅ GUI已启动，您现在可以手动进行页面跳转")
    print("当回到目标页面后，添加任务并点击'定时启动'或'立即开始'")


    # 启动页面状态检查
    def update_page_status():
        if page_controller.is_on_target_page():
            app.page_status_var.set("页面状态: ✅ 在目标页面")
        else:
            app.page_status_var.set("页面状态: ❌ 不在目标页面")
        root.after(2000, update_page_status)


    root.after(2000, update_page_status)
    root.mainloop()