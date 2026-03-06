import sys
import time
import random
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict
import tkinter as tk
from tkinter import ttk, scrolledtext

# 兼容所有Playwright版本，仅保留核心功能
from playwright.sync_api import sync_playwright


# ===================== 全局状态管理 =====================
@dataclass
class BookingState:
    """预定状态管理类"""
    is_running: bool = False
    is_paused: bool = False
    hour_values: List[int] = field(default_factory=lambda: [0] * 24)
    remaining_values: Dict[int, int] = field(default_factory=dict)
    refresh_seconds: float = 3.0  # 刷新周期，默认3秒
    selected_date: str = ""  # 用户选择的日期，格式：YYYY-MM-DD


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

    def select_date(self, target_date: str) -> bool:
        """
        选择目标日期
        target_date格式: YYYY-MM-DD，例如 2026-03-06
        """
        try:
            current_page = self.get_current_page()

            # 解析目标日期
            target = datetime.strptime(target_date, "%Y-%m-%d")
            target_str = target.strftime("%a %d/%m")  # 例如 "Fri 06/03"

            # 查找日历中的日期元素
            date_elements = current_page.locator(".calendarbar-day")
            count = date_elements.count()

            for i in range(count):
                date_text = date_elements.nth(i).inner_text().strip()
                if target_str in date_text:
                    date_elements.nth(i).click()
                    print(f"✅ 选择日期: {target_str}")
                    time.sleep(2)  # 等待页面加载
                    return True

            print(f"⚠️ 未找到日期: {target_str}")
            return False

        except Exception as e:
            print(f"❌ 选择日期失败: {e}")
            return False

    def get_available_value(self, hour: int, date_str: str) -> int:
        """读取指定小时和日期的Available值"""
        try:
            current_page = self.get_current_page()

            # 根据小时确定在哪个面板（0-11左列，12-23右列）
            if hour < 12:
                # 左列表格
                table = current_page.locator("table.form_timezones table.table").first
            else:
                # 右列表格
                table = current_page.locator("table.form_timezones table.table").nth(1)

            # 找到对应小时的行
            row_index = hour if hour < 12 else hour - 12
            rows = table.locator("tbody tr")

            if row_index >= rows.count():
                return 0

            row = rows.nth(row_index)

            # Available值在第2个td (索引1)
            avail_td = row.locator("td").nth(1)
            avail_text = avail_td.inner_text().strip()

            return int(avail_text) if avail_text.isdigit() else 0

        except Exception as e:
            print(f"❌ 读取小时{hour} Available失败：{e}")
            return 0

    def select_and_book(self, hour: int, date_str: str, value: int) -> bool:
        """
        选择数量并点击Book按钮
        返回是否成功
        """
        try:
            current_page = self.get_current_page()

            # 1. 找到下拉框并选择数量
            select_id = f"DDL_{date_str}_{hour}"
            select_elem = current_page.locator(f"#{select_id}")

            if select_elem.count() == 0:
                print(f"小时{hour}: 未找到下拉框 {select_id}")
                return False

            # 获取最大可选值
            options = select_elem.locator("option")
            max_value = 0
            for i in range(options.count()):
                opt_val = options.nth(i).get_attribute("value")
                if opt_val and opt_val.isdigit():
                    max_value = max(max_value, int(opt_val))

            if value > max_value:
                print(f"小时{hour}: 请求数量{value}超过最大可选值{max_value}，将选择{max_value}")
                value = max_value

            if value <= 0:
                return False

            # 选择数量（这会触发Book按钮出现）
            select_elem.select_option(str(value))
            print(f"✅ 小时{hour}: 选择数量 {value}")
            time.sleep(1)  # 等待Book按钮出现

            # 2. 找到并点击对应的Book按钮
            # Book按钮在popup div中，需要根据hour定位
            pop_id = f"pop_{date_str}_{hour}"
            book_btn = current_page.locator(f"#{pop_id} input[value='Book']")

            if book_btn.count() == 0:
                # 尝试其他选择器
                book_btn = current_page.locator(f"#btnBook_{date_str}_{hour}")

            if book_btn.count() > 0 and book_btn.first.is_visible():
                book_btn.first.scroll_into_view_if_needed()
                book_btn.first.click()
                print(f"✅ 小时{hour}: 点击Book按钮")
                time.sleep(2)  # 等待提交完成
                return True
            else:
                print(f"⚠️ 小时{hour}: 未找到Book按钮")
                return False

        except Exception as e:
            print(f"❌ 小时{hour} 操作失败：{e}")
            return False

    def click_continue_button(self) -> bool:
        """
        更稳健的版本：使用显式等待
        """
        try:
            current_page = self.get_current_page()

            # 使用wait_for_selector等待按钮出现（最多等待5秒）
            continue_btn = current_page.wait_for_selector("#Continue", state="visible", timeout=5000)

            if continue_btn:
                continue_btn.scroll_into_view_if_needed()
                continue_btn.click()
                print("✅ 点击Continue按钮")
                time.sleep(1.5)
                return True

            print(f"❌ 点击Continue按钮失败：未找到Continue按钮")
            return False

        except Exception as e:
            print(f"❌ 点击Continue按钮失败：{e}")
            return False

    def click_refresh_button(self, date_str: str) -> bool:
        """
        点击Refresh按钮（每轮结束后点击）
        格式：refreshSlots_2026-03-09
        """
        try:
            current_page = self.get_current_page()

            # 构建Refresh按钮的ID
            refresh_id = f"refreshSlots_{date_str}"
            refresh_btn = current_page.locator(f"#{refresh_id}")

            if refresh_btn.count() > 0 and refresh_btn.first.is_visible():
                refresh_btn.first.click()
                print(f"✅ 点击Refresh按钮: {refresh_id}")
                time.sleep(global_state.refresh_seconds)  # 使用用户设置的刷新周期
                return True
            else:
                print(f"❌ 未找到Refresh按钮: {refresh_id}")
                return False

        except Exception as e:
            print(f"❌ 点击Refresh按钮失败：{e}")
            return False

    def is_on_target_page(self) -> bool:
        """检查是否在目标页面（包含预定表格的页面）"""
        try:
            current_page = self.get_current_page()
            # 检查是否存在日历和表格特征元素
            has_calendar = current_page.locator(".calendarbar").count() > 0
            has_table = current_page.locator("table.form_timezones").count() > 0
            return has_calendar and has_table
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


# ===================== 预定控制器（在主线程中运行）=====================
class BookingController:
    def __init__(self, page_ctrl, log_callback, status_callback):
        self.page_ctrl = page_ctrl
        self.log = log_callback
        self.update_status = status_callback
        self.current_hour = 0
        self.round_count = 1
        self.state = "IDLE"  # IDLE, RUNNING, PAUSED
        self.date_str = ""  # 当前操作的日期

    def start(self, date_str: str):
        """开始预定流程"""
        if self.state != "IDLE":
            return

        self.date_str = date_str
        self.log(f"📅 目标日期: {date_str}")

        # 先选择日期
        self.log("🔄 正在选择日期...")
        if not self.page_ctrl.select_date(date_str):
            self.log("❌ 日期选择失败，请检查日期格式或手动选择")
            return

        # 初始化剩余数量
        global_state.remaining_values = {h: v for h, v in enumerate(global_state.hour_values)}
        total_needed = sum(global_state.remaining_values.values())
        self.log(f"📊 需要预定总数量: {total_needed}")

        if total_needed == 0:
            self.log("⚠️ 没有需要预定的数量")
            return

        self.state = "RUNNING"
        self.current_hour = 0
        self.round_count = 1
        self.log(f"\n{'=' * 50}")
        self.log(f"第 {self.round_count} 轮预定开始")

        # 开始第一轮
        self.root.after(100, self._process_next)

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
        self.current_hour = 0
        self.round_count = 1
        global_state.remaining_values = {}
        self.log("🔄 已重置")
        self.update_status(False, False)

    def _process_next(self):
        """处理下一个步骤"""
        if self.state != "RUNNING":
            return

        # 检查是否在正确的页面
        if not self.page_ctrl.is_on_target_page():
            self.log("⚠️ 当前不在预定页面，等待跳转...")
            self.root.after(3000, self._process_next)
            return

        # 检查是否所有需求都已满足
        if sum(global_state.remaining_values.values()) == 0:
            self.log("\n🎉 所有预定完成！")
            self.state = "IDLE"
            self.update_status(False, False)
            return

        # 如果当前小时已经处理完所有小时，本轮结束，点击Refresh
        if self.current_hour >= 24:
            self._finish_round()
            return

        # 处理当前小时
        self._process_hour()

    def _process_hour(self):
        """处理单个小时"""
        hour = self.current_hour
        remaining = global_state.remaining_values.get(hour, 0)

        if remaining <= 0:
            self.current_hour += 1
            self.root.after(100, self._process_next)
            return

        try:
            available = self.page_ctrl.get_available_value(hour, self.date_str)

            if available <= 0:
                self.log(f"⏭️ 小时{hour:02d}: 可用数量为0，跳过")
                self.current_hour += 1
                self.root.after(500, self._process_next)
                return

            # 本轮需要填写的数量
            book_amount = min(remaining, available)  # 不能超过可用数量

            if book_amount > 0:
                self.log(f"小时{hour:02d}: 需要{remaining}，可用{available}，尝试预定{book_amount}")

                # 选择数量并点击Book
                success = self.page_ctrl.select_and_book(hour, self.date_str, book_amount)

                if success:
                    # 提交成功后，从remaining_values中减去
                    global_state.remaining_values[hour] -= book_amount
                    self.log(f"✅ 小时{hour:02d}: 成功预定{book_amount}，还剩{global_state.remaining_values[hour]}")

                    # 点击Continue按钮返回主页面
                    self.log("🔄 点击Continue返回...")
                    self.page_ctrl.click_continue_button()

                    time.sleep(1)  # 等待返回
                else:
                    self.log(f"❌ 小时{hour:02d}: 预定失败")

            self.current_hour += 1
            self.root.after(500, self._process_next)

        except Exception as e:
            self.log(f"⚠️ 小时{hour:02d} 操作失败: {str(e)[:50]}")
            self.current_hour += 1
            self.root.after(2000, self._process_next)

    def _finish_round(self):
        """完成本轮预定，点击Refresh按钮"""
        total_remaining = sum(global_state.remaining_values.values())
        self.log(f"\n📊 第 {self.round_count} 轮完成，剩余总数量: {total_remaining}")

        # 点击Refresh按钮刷新页面（使用日期参数）
        self.log(f"🔄 点击Refresh按钮刷新页面 (refreshSlots_{self.date_str})...")
        self.page_ctrl.click_refresh_button(self.date_str)
        self.log("✅ 页面刷新完成")

        # 重置小时计数器
        self.current_hour = 0
        self.round_count += 1

        if total_remaining > 0:
            self.log(f"\n{'=' * 50}")
            self.log(f"第 {self.round_count} 轮预定开始")
            self.root.after(1000, self._process_next)
        else:
            self.log("\n🎉 所有预定完成！")
            self.state = "IDLE"
            self.update_status(False, False)


# ===================== Tkinter GUI =====================
class BookingGUI:
    def __init__(self, root, page_ctrl):
        self.root = root
        self.page_ctrl = page_ctrl
        self.root.title("Patrick 预定工具")
        self.root.geometry("900x750")

        self.hour_vars = []
        self.controller = None
        self.init_ui()

    def init_ui(self):
        """初始化GUI控件"""
        title_frame = ttk.Frame(self.root)
        title_frame.pack(pady=5, fill="x")
        ttk.Label(title_frame, text="⚡ Patrick 预定工具 ⚡", font=("Arial", 14, "bold")).pack()

        # 状态显示
        status_frame = ttk.Frame(self.root)
        status_frame.pack(pady=2, fill="x", padx=20)
        self.page_status_var = tk.StringVar(value="页面状态: 检测中...")
        ttk.Label(status_frame, textvariable=self.page_status_var, foreground="blue").pack(side="left")

        # 设置区域
        settings_frame = ttk.LabelFrame(self.root, text="设置")
        settings_frame.pack(pady=8, padx=20, fill="x")

        # 日期选择
        date_row = ttk.Frame(settings_frame)
        date_row.pack(pady=5, fill="x")

        ttk.Label(date_row, text="目标日期：", width=10).pack(side="left", padx=5)

        # 获取当前日期作为默认值
        today = datetime.now().strftime("%Y-%m-%d")
        self.date_var = tk.StringVar(value=today)
        date_entry = ttk.Entry(date_row, textvariable=self.date_var, width=15)
        date_entry.pack(side="left", padx=5)

        ttk.Label(date_row, text="格式：YYYY-MM-DD", foreground="blue").pack(side="left", padx=5)

        # 刷新周期设置（用于Refresh按钮后的等待）
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

        # 24小时输入框
        hour_frame = ttk.LabelFrame(self.root, text="24小时预定数量设置")
        hour_frame.pack(pady=8, padx=20, fill="both", expand=1)

        inner_frame = ttk.Frame(hour_frame)
        inner_frame.pack(pady=10, padx=10)

        for row in range(4):
            for col in range(6):
                hour = row * 6 + col
                if hour >= 24:
                    break

                hour_cell = ttk.Frame(inner_frame)
                hour_cell.grid(row=row, column=col, padx=5, pady=5)

                ttk.Label(hour_cell, text=f"{hour:02d}:00", font=("Arial", 9, "bold")).pack()

                var = tk.IntVar(value=0)
                spin = ttk.Spinbox(hour_cell, from_=0, to=999, textvariable=var, width=6, font=("Arial", 10))
                spin.pack(pady=2)

                def validate_hour_value(*args, h=hour, v=var):
                    try:
                        value = v.get()
                        global_state.hour_values[h] = value
                    except:
                        global_state.hour_values[h] = 0
                        v.set(0)

                var.trace_add("write", validate_hour_value)
                self.hour_vars.append(var)

        # 控制按钮
        btn_frame = ttk.LabelFrame(self.root, text="控制面板")
        btn_frame.pack(pady=8, padx=20, fill="x")

        button_container = ttk.Frame(btn_frame)
        button_container.pack(pady=10)

        self.start_btn = ttk.Button(button_container, text="▶ 开始预定", command=self.start_booking, width=10)
        self.start_btn.pack(side="left", padx=5)

        self.pause_btn = ttk.Button(button_container, text="⏸️ 暂停", command=self.pause_booking, state="disabled",
                                    width=8)
        self.pause_btn.pack(side="left", padx=5)

        self.resume_btn = ttk.Button(button_container, text="▶ 继续", command=self.resume_booking, state="disabled",
                                     width=8)
        self.resume_btn.pack(side="left", padx=5)

        self.reset_btn = ttk.Button(button_container, text="🔄 重置", command=self.reset_booking, width=8)
        self.reset_btn.pack(side="left", padx=5)

        # 快速设置按钮
        quick_frame = ttk.Frame(btn_frame)
        quick_frame.pack(pady=5)

        ttk.Button(quick_frame, text="全部清空", command=lambda: [v.set(0) for v in self.hour_vars], width=10).pack(
            side="left", padx=5)
        ttk.Button(quick_frame, text="检查总计", command=self.show_total, width=10).pack(side="left", padx=5)
        ttk.Button(quick_frame, text="检查页面", command=self.check_page, width=10).pack(side="left", padx=5)

        # 日志面板
        log_frame = ttk.LabelFrame(self.root, text="运行日志")
        log_frame.pack(pady=8, padx=20, fill="both", expand=1)

        log_control_frame = ttk.Frame(log_frame)
        log_control_frame.pack(fill="x", padx=5, pady=2)

        ttk.Button(log_control_frame, text="清除日志", command=self.clear_log).pack(side="right")

        self.log_text = scrolledtext.ScrolledText(log_frame, state="disabled", height=12,
                                                  font=("Consolas", 9), wrap=tk.WORD)
        self.log_text.pack(fill="both", expand=1, padx=5, pady=5)

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
        """显示总计数量"""
        total = sum(v.get() for v in self.hour_vars)
        self.add_log(f"📊 当前设置总数量: {total}")

    def check_page(self):
        """检查页面状态"""
        if self.page_ctrl.is_on_target_page():
            self.page_status_var.set("页面状态: ✅ 在预定页面")
            self.add_log("✅ 当前在预定页面")
        else:
            self.page_status_var.set("页面状态: ❌ 不在预定页面")
            self.add_log("⚠️ 当前不在预定页面")

    def update_buttons(self, is_running, is_paused):
        """更新按钮状态"""
        if is_running and not is_paused:
            self.start_btn.config(state="disabled")
            self.pause_btn.config(state="normal")
            self.resume_btn.config(state="disabled")
            self.reset_btn.config(state="normal")
        elif is_running and is_paused:
            self.start_btn.config(state="disabled")
            self.pause_btn.config(state="disabled")
            self.resume_btn.config(state="normal")
            self.reset_btn.config(state="normal")
        else:
            self.start_btn.config(state="normal")
            self.pause_btn.config(state="disabled")
            self.resume_btn.config(state="disabled")
            self.reset_btn.config(state="normal")

    def start_booking(self):
        """开始预定"""
        if sum(v.get() for v in self.hour_vars) == 0:
            self.add_log("⚠️ 请先设置需要预定的数量")
            return

        # 验证日期格式
        date_str = self.date_var.get().strip()
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except:
            self.add_log("❌ 日期格式错误，应为 YYYY-MM-DD")
            return

        global_state.selected_date = date_str

        # 创建控制器
        self.controller = BookingController(
            self.page_ctrl,
            self.add_log,
            self.update_buttons
        )
        # 绑定root以便使用after
        self.controller.root = self.root

        global_state.is_running = True
        global_state.is_paused = False
        self.update_buttons(True, False)

        self.controller.start(date_str)
        self.add_log("🚀 启动预定流程")

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
    print("当回到预定页面后，设置日期和数量，点击'开始预定'即可开始")


    # 启动页面状态检查
    def update_page_status():
        if page_controller.is_on_target_page():
            app.page_status_var.set("页面状态: ✅ 在预定页面")
        else:
            app.page_status_var.set("页面状态: ❌ 不在预定页面")
        root.after(2000, update_page_status)


    root.after(2000, update_page_status)
    root.mainloop()