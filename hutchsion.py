import sys
import time
import os
import random
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
    req_type: str = "IMPORT"
    remaining_values: Dict[int, int] = field(default_factory=dict)
    refresh_seconds: float = 3.0  # 刷新周期，默认3秒


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
        """初始化浏览器，适配打包环境"""
        # 重要：设置浏览器路径环境变量，确保能找到打包进去的浏览器
        if getattr(sys, 'frozen', False):
            # 如果是打包后的 exe 运行
            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'  # 使用打包的浏览器
            print("✅ 运行在打包环境中")

        self.playwright = sync_playwright().start()

        # 最简启动
        self.browser = self.playwright.chromium.launch(
            headless=False
        )

        # 创建上下文
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

    def get_available_value(self, hour: int, req_type: str) -> int:
        """读取指定小时的Available值"""
        try:
            current_page = self.get_current_page()
            panel_class = "left-panel" if hour < 12 else "right-panel"
            zone_input = current_page.locator(f".{panel_class} input[id='Summary_ZoneSummary_{hour}__ZoneId']")

            if zone_input.count() == 0:
                return 0

            row = zone_input.locator("xpath=ancestor::tr[1]")
            col_idx = 1 if req_type == "IMPORT" else 4
            avail_td = row.locator(f"td:nth-child({col_idx + 2})")

            if avail_td.count() == 0:
                return 0

            avail_text = avail_td.first.inner_text().strip()
            return int(avail_text) if avail_text.isdigit() else 0

        except Exception as e:
            print(f"❌ 读取小时{hour} Available失败：{e}")
            return 0

    def fill_request_value(self, hour: int, req_type: str, value: int) -> bool:
        """填充指定小时的Request输入框"""
        try:
            current_page = self.get_current_page()
            formatted_type = "Import" if req_type.upper() == "IMPORT" else "Export"
            input_id = f"Summary_ZoneSummary_{hour}__{formatted_type}_Request"
            input_elem = current_page.locator(f"#{input_id}")

            if input_elem.count() == 0:
                return False

            input_elem = input_elem.first
            if input_elem.is_visible():
                input_elem.scroll_into_view_if_needed()
                input_elem.fill(str(value))
                print(f"✅ 小时{hour} {req_type} 填写: {value}")
                return True
            return False

        except Exception as e:
            print(f"❌ 填充小时{hour} Request失败：{e}")
            return False

    def click_submit_button(self) -> bool:
        """点击提交按钮并确认"""
        try:
            current_page = self.get_current_page()
            time.sleep(1)

            submit_btn = current_page.locator("#Book")
            if submit_btn.count() == 0 or not submit_btn.first.is_visible():
                return False

            submit_btn.first.click()
            print("✅ 点击提交按钮")
            time.sleep(2)

            # 点击Yes确认
            yes_selectors = [
                "button:has-text('Yes')",
                ".ui-dialog-buttonset button:has-text('Yes')",
                "div.ui-dialog-buttonset button:has-text('Yes')"
            ]

            for selector in yes_selectors:
                yes_btn = current_page.locator(selector)
                if yes_btn.count() > 0 and yes_btn.first.is_visible():
                    yes_btn.first.click()
                    print("✅ 点击确认对话框的 Yes 按钮")
                    time.sleep(2)
                    break

            # 跳转回预定页面
            self.page.goto("https://hpaportal.com.au/HPAPB/TAS/Appointments/Book")
            time.sleep(1)
            return True

        except Exception as e:
            print(f"❌ 点击提交按钮失败：{e}")
            return False

    def is_on_target_page(self) -> bool:
        """检查是否在目标页面"""
        try:
            current_page = self.get_current_page()
            return current_page.locator("input[id^='Summary_ZoneSummary_']").count() > 0
        except:
            return False

    def reload_page(self, refresh_seconds: float):
        """刷新页面，使用指定的刷新周期"""
        try:
            current_page = self.get_current_page()
            current_page.reload()
            time.sleep(refresh_seconds)
        except Exception as e:
            print(f"❌ 刷新页面失败：{e}")

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
        self.round_requests = {}  # 记录本轮每个小时填写的数量
        self.round_filled = 0
        self.round_count = 1
        self.state = "IDLE"  # IDLE, RUNNING, PAUSED

    def start(self):
        """开始预定流程"""
        if self.state != "IDLE":
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
        self.round_requests = {}
        self.round_filled = 0
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
        self.round_requests = {}
        self.round_filled = 0
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

        # 如果当前小时已经处理完所有小时，提交本轮
        if self.current_hour >= 24:
            self._submit_round()
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
            available = self.page_ctrl.get_available_value(hour, global_state.req_type)

            if available <= 0:
                self.log(f"⏭️ 小时{hour:02d}: 可用数量为0，跳过")
                self.current_hour += 1
                self.root.after(500, self._process_next)
                return

            fill_amount = min(remaining, available, 4)

            if fill_amount > 0:
                success = self.page_ctrl.fill_request_value(hour, global_state.req_type, fill_amount)

                if success:
                    # 记录本轮填写的数量，但不从remaining_values中减去
                    self.round_requests[hour] = fill_amount
                    self.round_filled += fill_amount

                    self.log(
                        f"✅ 小时{hour:02d}: 需要{remaining}，可用{available}，填写{fill_amount}（待提交）")

                    self.current_hour += 1
                    self.root.after(1000, self._process_next)
                else:
                    self.log(f"❌ 小时{hour:02d}: 填写失败")
                    self.current_hour += 1
                    self.root.after(500, self._process_next)
            else:
                self.current_hour += 1
                self.root.after(100, self._process_next)

        except Exception as e:
            self.log(f"⚠️ 小时{hour:02d} 操作失败: {str(e)[:50]}")
            self.current_hour += 1
            self.root.after(2000, self._process_next)

    def _submit_round(self):
        """提交本轮预定"""
        if self.round_filled > 0:
            self.log(f"\n📤 本轮填写总数: {self.round_filled}，点击提交按钮...")
            try:
                if self.page_ctrl.click_submit_button():
                    self.log("✅ 提交成功")

                    # 提交成功后，才从remaining_values中减去本轮填写的数量
                    for hour, amount in self.round_requests.items():
                        global_state.remaining_values[hour] -= amount
                        self.log(f"📝 小时{hour:02d}: 已扣除{amount}，剩余{global_state.remaining_values[hour]}")

                    self.log("🔄 正在刷新页面...")
                    # 使用用户设置的刷新周期
                    self.page_ctrl.reload_page(global_state.refresh_seconds)
                    self.log("✅ 页面刷新完成")
                else:
                    self.log("⚠️ 提交可能失败，本轮填写可能未生效")
                    # 提交失败，不清除round_requests，下一轮可以重试
                    self.root.after(3000, self._prepare_next_round)
                    return
            except Exception as e:
                self.log(f"⚠️ 提交出错: {str(e)[:50]}")
                self.root.after(3000, self._prepare_next_round)
                return
        else:
            self.log("⚠️ 本轮没有可预定的数量，刷新页面后重试...")
            self.log("🔄 正在刷新页面...")
            # 使用用户设置的刷新周期
            self.page_ctrl.reload_page(global_state.refresh_seconds)
            self.log("✅ 页面刷新完成")

        # 准备下一轮
        self._prepare_next_round()

    def _prepare_next_round(self):
        """准备下一轮"""
        total_remaining = sum(global_state.remaining_values.values())
        self.log(f"📊 本轮完成，剩余总数量: {total_remaining}")

        # 重置本轮记录
        self.current_hour = 0
        self.round_requests = {}
        self.round_filled = 0
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
        self.root.title("Hutchsion订票工具")
        self.root.geometry("900x750")

        self.hour_vars = []
        self.controller = None
        self.init_ui()

    def init_ui(self):
        """初始化GUI控件"""
        title_frame = ttk.Frame(self.root)
        title_frame.pack(pady=5, fill="x")
        ttk.Label(title_frame, text="⚡ Hutchsion订票工具 ⚡", font=("Arial", 14, "bold")).pack()

        # 状态显示
        status_frame = ttk.Frame(self.root)
        status_frame.pack(pady=2, fill="x", padx=20)
        self.page_status_var = tk.StringVar(value="页面状态: 检测中...")
        ttk.Label(status_frame, textvariable=self.page_status_var, foreground="blue").pack(side="left")

        # 类型选择和刷新周期设置
        settings_frame = ttk.LabelFrame(self.root, text="设置")
        settings_frame.pack(pady=8, padx=20, fill="x")

        # 第一行：预定类型
        type_row = ttk.Frame(settings_frame)
        type_row.pack(pady=5, fill="x")

        ttk.Label(type_row, text="预定类型：", width=10).pack(side="left", padx=5)
        self.type_var = tk.StringVar(value="IMPORT")
        type_combo = ttk.Combobox(type_row, textvariable=self.type_var, values=["IMPORT", "EXPORT"], width=10,
                                   state="readonly")
        type_combo.pack(side="left", padx=5)
        type_combo.bind("<<ComboboxSelected>>", lambda e: setattr(global_state, "req_type", self.type_var.get()))

        ttk.Label(type_row, text="（每个小时最多填写4）", foreground="blue").pack(side="left", padx=20)

        # 第二行：刷新周期设置
        refresh_row = ttk.Frame(settings_frame)
        refresh_row.pack(pady=5, fill="x")

        ttk.Label(refresh_row, text="刷新周期：", width=10).pack(side="left", padx=5)

        # 刷新周期输入框（支持小数）
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

        # 验证输入是否为有效数字
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
                spin = ttk.Spinbox(hour_cell, from_=0, to=99, textvariable=var, width=6, font=("Arial", 10))
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
        ttk.Button(quick_frame, text="全部设为4", command=lambda: [v.set(4) for v in self.hour_vars], width=10).pack(
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

        self.controller.start()
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
    TARGET_URL = "https://hpaportal.com.au/HPAPB/Login"

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
        page_controller.close_browser()
        root.destroy()


    root.protocol("WM_DELETE_WINDOW", on_close)

    print("✅ GUI已启动，您现在可以手动进行页面跳转")
    print("当回到预定页面后，点击'开始预定'即可开始")


    # 启动页面状态检查
    def update_page_status():
        if page_controller.is_on_target_page():
            app.page_status_var.set("页面状态: ✅ 在预定页面")
        else:
            app.page_status_var.set("页面状态: ❌ 不在预定页面")
        root.after(2000, update_page_status)


    root.after(2000, update_page_status)
    root.mainloop()