#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片管理器 - 检测图片目录有序性并支持范围选择复制/移动
作者: AI Assistant
版本: 1.0
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import shutil
import threading
import time
from pathlib import Path
import re
import json
from PIL import Image, ImageTk
import psutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import queue
from concurrent.futures import ThreadPoolExecutor
try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False
    print("注意: paramiko库未安装，SSH服务器模式将被禁用。如需完整功能，请运行: pip install paramiko")
try:
    import win32gui
    import win32process
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    print("注意: pywin32库未安装，窗口监控功能将被禁用。如需完整功能，请运行: pip install pywin32")

class ProgressDialog:
    """进度条对话框"""
    
    def __init__(self, parent, title="操作进度"):
        self.parent = parent
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.geometry("500x300")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # 居中显示
        self.dialog.geometry("+%d+%d" % (parent.winfo_rootx() + 50, parent.winfo_rooty() + 50))
        
        # 创建界面
        self.create_widgets()
        
        # 任务相关变量
        self.tasks = {}  # {task_id: {"name": str, "progress": int, "status": str}}
        self.cancelled = False
        
    def create_widgets(self):
        """创建界面组件"""
        # 主框架
        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 总体进度标签
        self.overall_label = ttk.Label(main_frame, text="准备开始...", font=("Arial", 10, "bold"))
        self.overall_label.pack(pady=(0, 10))
        
        # 总体进度条
        self.overall_progress = ttk.Progressbar(main_frame, mode='determinate')
        self.overall_progress.pack(fill=tk.X, pady=(0, 20))
        
        # 任务列表框架
        list_frame = ttk.LabelFrame(main_frame, text="任务详情", padding="5")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # 创建滚动文本框显示任务进度
        self.text_frame = tk.Frame(list_frame)
        self.text_frame.pack(fill=tk.BOTH, expand=True)
        
        self.text_widget = tk.Text(self.text_frame, height=8, wrap=tk.WORD, state=tk.DISABLED)
        scrollbar = ttk.Scrollbar(self.text_frame, orient=tk.VERTICAL, command=self.text_widget.yview)
        self.text_widget.configure(yscrollcommand=scrollbar.set)
        
        self.text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        self.cancel_button = ttk.Button(button_frame, text="取消", command=self.cancel_task)
        self.cancel_button.pack(side=tk.RIGHT, padx=(5, 0))
        
        self.close_button = ttk.Button(button_frame, text="关闭", command=self.close_dialog, state=tk.DISABLED)
        self.close_button.pack(side=tk.RIGHT)
        
    def update_overall_progress(self, current, total, text=""):
        """更新总体进度"""
        if total > 0:
            progress = (current / total) * 100
            self.overall_progress['value'] = progress
            
        if text:
            self.overall_label.config(text=text)
            
    def add_task_log(self, message):
        """添加任务日志"""
        self.text_widget.config(state=tk.NORMAL)
        self.text_widget.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
        self.text_widget.see(tk.END)
        self.text_widget.config(state=tk.DISABLED)
        
    def cancel_task(self):
        """取消任务"""
        self.cancelled = True
        self.cancel_button.config(state=tk.DISABLED)
        self.add_task_log("正在取消任务...")
        
    def task_completed(self):
        """任务完成"""
        self.cancel_button.config(state=tk.DISABLED)
        self.close_button.config(state=tk.NORMAL)
        self.overall_progress['value'] = 100
        
    def close_dialog(self):
        """关闭对话框"""
        self.dialog.destroy()
        
    def is_cancelled(self):
        """检查是否已取消"""
        return self.cancelled

class ImageFileHandler(FileSystemEventHandler):
    """文件系统事件处理器，用于跟踪图片文件的打开"""
    
    def __init__(self, callback):
        self.callback = callback
        self.image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}
    
    def on_modified(self, event):
        if not event.is_directory:
            file_path = event.src_path
            if Path(file_path).suffix.lower() in self.image_extensions:
                self.callback(file_path)

class ImageManager:
    """图片管理器主类"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("图片管理器 v1.0")
        self.root.geometry("1000x700")
        self.root.resizable(True, True)
        
        # 初始化变量
        self.source_dir = tk.StringVar()
        self.target_dir = tk.StringVar()
        self.start_image = None
        self.end_image = None
        self.image_files = []
        self.current_opened_image = None
        self.observer = None
        self.is_detecting = False
        self.window_monitor_thread = None
        self.window_monitor_running = False
        
        # 配置相关变量
        self.config_file = "config.json"
        self.target_directories = {}  # 兼容旧格式 {名称: 路径}
        self.scenarios = {}  # 新格式 {场景名称: {子目录名称: 路径}}
        self.selected_target = tk.StringVar()
        self.scenario_collapsed = {}  # 场景折叠状态 {场景名称: True/False}
        
        # 异步任务相关变量
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.task_queue = queue.Queue()
        self.progress_dialog = None
        self.current_task = None
        self.task_cancelled = False
        
        # 模式相关变量
        self.operation_mode = tk.StringVar(value="windows")  # windows 或 server
        
        # SSH服务器配置
        self.ssh_config = {
            "host": "",
            "username": "",
            "password": "",
            "share_path": "/data/share"  # 服务器上share目录的绝对路径
        }
        self.ssh_client = None
        self.ssh_connection_time = None  # 连接建立时间
        self.ssh_last_activity = None    # 最后活动时间
        self.ssh_connection_timeout = 7200  # 连接超时时间（秒），增加到2小时
        self.ssh_directory_cache = set()  # 已创建目录的缓存
        self.ssh_connection_pool = {}  # SSH连接池
        self.max_pool_size = 3  # 最大连接池大小
        self.connection_reuse_count = 0  # 连接复用计数
        self.max_reuse_count = 1000  # 最大复用次数，超过后重建连接
        
        # 加载配置
        self.load_config()
        
        # 创建菜单栏
        self.create_menu()
        
        # 创建界面
        self.create_widgets()
        
        # 更新模式显示
        self.update_mode_display()
        
        # 绑定关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def create_menu(self):
        """创建菜单栏"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # 配置菜单
        config_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="配置", menu=config_menu)
        config_menu.add_command(label="操作模式配置", command=self.open_mode_config)
        config_menu.add_separator()
        config_menu.add_command(label="目标目录配置", command=self.open_target_config)
        config_menu.add_separator()
        config_menu.add_command(label="退出", command=self.on_closing)
    
    def load_config(self):
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.target_directories = config.get('target_directories', {})
                    self.scenarios = config.get('scenarios', {})
                    
                    # 加载操作模式
                    mode = config.get('operation_mode', 'windows')
                    self.operation_mode.set(mode)
                    
                    # 加载SSH配置
                    ssh_config = config.get('ssh_config', {})
                    self.ssh_config.update(ssh_config)
                    
                    # 如果有旧格式的target_directories，转换为新格式
                    if self.target_directories and not self.scenarios:
                        self.scenarios = {}
                        for name, path in self.target_directories.items():
                            # 从路径中提取场景名和子目录名
                            path_parts = path.replace('/', '\\').split('\\')
                            if len(path_parts) >= 2:
                                # 倒数第二级作为场景名，最后一级作为子目录名
                                scenario_name = path_parts[-2]
                                subdir_name = path_parts[-1]
                            else:
                                # 如果路径层级不够，使用原名称作为子目录，场景名为默认
                                scenario_name = '默认场景'
                                subdir_name = name
                            
                            # 确保场景存在
                            if scenario_name not in self.scenarios:
                                self.scenarios[scenario_name] = {}
                            
                            # 添加子目录
                            self.scenarios[scenario_name][subdir_name] = path
                        
                        self.target_directories = {}  # 清空旧格式
                    
                    # 设置默认选中的目标目录
                    if self.scenarios:
                        first_scenario = list(self.scenarios.keys())[0]
                        if self.scenarios[first_scenario]:
                            first_subdir = list(self.scenarios[first_scenario].keys())[0]
                            self.selected_target.set(f"{first_scenario}::{first_subdir}")
        except Exception as e:
            print(f"加载配置文件失败: {e}")
            self.target_directories = {}
            self.scenarios = {}
    
    def save_config(self):
        """保存配置文件"""
        try:
            config = {
                'target_directories': self.target_directories,  # 保持兼容性
                'scenarios': self.scenarios,
                'operation_mode': self.operation_mode.get(),
                'ssh_config': self.ssh_config
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("错误", f"保存配置文件失败: {e}")
    
    def open_mode_config(self):
        """打开操作模式配置对话框"""
        mode_window = tk.Toplevel(self.root)
        mode_window.title("操作模式配置")
        mode_window.geometry("600x500")
        mode_window.resizable(True, True)  # 允许用户调整大小
        mode_window.minsize(500, 400)  # 设置最小尺寸
        mode_window.transient(self.root)
        mode_window.grab_set()
        
        # 居中显示对话框
        mode_window.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (600 // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (500 // 2)
        mode_window.geometry(f"600x500+{x}+{y}")
        
        # 主框架
        main_frame = ttk.Frame(mode_window, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 模式选择框架
        mode_frame = ttk.LabelFrame(main_frame, text="操作模式选择", padding="10")
        mode_frame.pack(fill=tk.X, pady=(0, 15))
        
        # 模式选择单选按钮
        ttk.Radiobutton(mode_frame, text="Windows本地模式", 
                       variable=self.operation_mode, value="windows").pack(anchor=tk.W, pady=2)
        ttk.Radiobutton(mode_frame, text="SSH服务器模式", 
                       variable=self.operation_mode, value="server").pack(anchor=tk.W, pady=2)
        
        # SSH配置框架
        ssh_frame = ttk.LabelFrame(main_frame, text="SSH服务器配置", padding="10")
        ssh_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # SSH配置变量
        ssh_host = tk.StringVar(value=self.ssh_config.get("host", ""))
        ssh_username = tk.StringVar(value=self.ssh_config.get("username", ""))
        ssh_password = tk.StringVar(value=self.ssh_config.get("password", ""))
        ssh_share_path = tk.StringVar(value=self.ssh_config.get("share_path", "/data/share"))
        
        # SSH主机
        ttk.Label(ssh_frame, text="SSH主机:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(ssh_frame, textvariable=ssh_host, width=40).grid(row=0, column=1, sticky=tk.W+tk.E, pady=5, padx=(10, 0))
        
        # SSH用户名
        ttk.Label(ssh_frame, text="用户名:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(ssh_frame, textvariable=ssh_username, width=40).grid(row=1, column=1, sticky=tk.W+tk.E, pady=5, padx=(10, 0))
        
        # SSH密码
        ttk.Label(ssh_frame, text="密码:").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(ssh_frame, textvariable=ssh_password, show="*", width=40).grid(row=2, column=1, sticky=tk.W+tk.E, pady=5, padx=(10, 0))
        
        # 服务器share目录路径
        ttk.Label(ssh_frame, text="服务器share目录:").grid(row=3, column=0, sticky=tk.W, pady=5)
        ttk.Entry(ssh_frame, textvariable=ssh_share_path, width=40).grid(row=3, column=1, sticky=tk.W+tk.E, pady=5, padx=(10, 0))
        
        # 配置网格权重
        ssh_frame.columnconfigure(1, weight=1)
        
        # 说明文本
        info_text = "说明:\n" + \
                   "• Windows本地模式: 直接在本地文件系统进行操作\n" + \
                   "• SSH服务器模式: 通过SSH连接到远程服务器执行操作\n" + \
                   "• 服务器share目录: 服务器上共享目录的绝对路径\n" + \
                   "• 例如: /data/share 对应 \\\\192.168.11.189\\share"
        
        info_label = ttk.Label(ssh_frame, text=info_text, foreground="gray", font=("Arial", 8))
        info_label.grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
        
        # 按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        def test_ssh_connection():
            """测试SSH连接"""
            if not PARAMIKO_AVAILABLE:
                messagebox.showerror("错误", "paramiko库未安装，无法使用SSH功能")
                return
                
            host = ssh_host.get().strip()
            username = ssh_username.get().strip()
            password = ssh_password.get()
            
            if not all([host, username, password]):
                messagebox.showwarning("警告", "请填写完整的SSH连接信息")
                return
            
            try:
                # 创建SSH客户端测试连接
                test_client = paramiko.SSHClient()
                test_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                test_client.connect(hostname=host, username=username, password=password, timeout=10)
                test_client.close()
                messagebox.showinfo("成功", "SSH连接测试成功！")
            except Exception as e:
                messagebox.showerror("连接失败", f"SSH连接测试失败:\n{str(e)}")
        
        def save_config_only():
            """仅保存配置，不关闭对话框"""
            # 获取当前选择的操作模式
            selected_mode = self.operation_mode.get()
            
            # 如果选择服务器模式，需要校验SSH连接
            if selected_mode == "server":
                if not PARAMIKO_AVAILABLE:
                    messagebox.showerror("错误", "paramiko库未安装，无法使用SSH功能")
                    return
                    
                host = ssh_host.get().strip()
                username = ssh_username.get().strip()
                password = ssh_password.get()
                share_path = ssh_share_path.get().strip()
                
                # 检查必填字段
                if not all([host, username, password, share_path]):
                    messagebox.showwarning("警告", "服务器模式下请填写完整的SSH连接信息和共享路径")
                    return
                
                # 测试SSH连接
                try:
                    test_client = paramiko.SSHClient()
                    test_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    test_client.connect(hostname=host, username=username, password=password, timeout=10)
                    
                    # 测试共享路径是否存在
                    stdin, stdout, stderr = test_client.exec_command(f'test -d "{share_path}" && echo "exists" || echo "not_exists"')
                    result = stdout.read().decode().strip()
                    
                    if result != "exists":
                        test_client.close()
                        messagebox.showerror("路径错误", f"服务器上的共享路径不存在: {share_path}")
                        return
                    
                    test_client.close()
                    
                except Exception as e:
                    messagebox.showerror("连接失败", f"SSH连接校验失败:\n{str(e)}\n\n请检查连接信息后重试")
                    return
            
            # 更新SSH配置
            self.ssh_config["host"] = ssh_host.get().strip()
            self.ssh_config["username"] = ssh_username.get().strip()
            self.ssh_config["password"] = ssh_password.get()
            self.ssh_config["share_path"] = ssh_share_path.get().strip()
            
            # 保存配置到文件
            self.save_config()
            
            # 更新模式显示
            self.update_mode_display()
            
            # 显示保存成功信息
            if selected_mode == "server":
                messagebox.showinfo("成功", f"配置已保存\n当前模式: SSH服务器模式\n服务器: {ssh_host.get().strip()}")
            else:
                messagebox.showinfo("成功", "配置已保存\n当前模式: Windows本地模式")
        
        def save_and_close():
            """保存配置并关闭对话框"""
            # 先保存配置
            save_config_only()
            
            # 关闭SSH连接（如果存在）
            if self.ssh_client:
                try:
                    self.ssh_client.close()
                except:
                    pass
                self.ssh_client = None
            
            mode_window.destroy()
        
        # 按钮 - 使用网格布局避免重叠
        ttk.Button(button_frame, text="测试SSH连接", command=test_ssh_connection).grid(row=0, column=0, padx=(0, 10), pady=5)
        ttk.Button(button_frame, text="保存配置", command=save_config_only).grid(row=0, column=1, padx=(0, 10), pady=5)
        ttk.Button(button_frame, text="保存并关闭", command=save_and_close).grid(row=0, column=2, padx=(0, 10), pady=5)
        ttk.Button(button_frame, text="取消", command=mode_window.destroy).grid(row=0, column=3, padx=(0, 0), pady=5)
        
        # 配置按钮框架的列权重，使按钮均匀分布
        for i in range(4):
            button_frame.columnconfigure(i, weight=1)
    
    def convert_smb_to_linux_path(self, smb_path):
        """将SMB路径转换为Linux绝对路径
        
        Args:
            smb_path: SMB路径，如 \\\\192.168.11.189\\share\\数据\\测试集\\coal-3218
            
        Returns:
            转换后的Linux路径，如 /data/share/数据/测试集/coal-3218
        """
        if not smb_path or not isinstance(smb_path, str):
            return smb_path
            
        # 移除开头的反斜杠并分割路径
        path_clean = smb_path.strip().replace('\\', '/')
        
        # 分割路径组件
        path_parts = [part for part in path_clean.split('/') if part]
        
        if len(path_parts) < 2:
            return smb_path  # 路径格式不正确，返回原路径
            
        # 第一部分是IP地址，第二部分是share，从第三部分开始是实际路径
        if len(path_parts) >= 2 and path_parts[1] == 'share':
            # 获取服务器share目录的绝对路径
            server_share_path = self.ssh_config.get('share_path', '/data/share')
            
            # 构建Linux路径：服务器share路径 + 相对路径
            if len(path_parts) > 2:
                relative_path = '/'.join(path_parts[2:])
                linux_path = f"{server_share_path.rstrip('/')}/{relative_path}"
            else:
                linux_path = server_share_path
                
            return linux_path
        
        return smb_path  # 无法转换，返回原路径
    
    def convert_windows_to_linux_path(self, windows_path):
        """将Windows路径转换为Linux路径（用于服务器模式）
        
        Args:
            windows_path: Windows路径，可能是本地路径或SMB路径
            
        Returns:
            转换后的Linux路径
        """
        if not windows_path or not isinstance(windows_path, str):
            return windows_path
            
        # 如果是SMB路径（以\\开头），使用SMB转换逻辑
        if windows_path.startswith('\\\\'):
            return self.convert_smb_to_linux_path(windows_path)
        
        # 如果是普通Windows路径，直接转换反斜杠为正斜杠
        linux_path = windows_path.replace('\\', '/')
        
        # 处理Windows驱动器路径（如C:\path -> /mnt/c/path）
        if len(linux_path) >= 2 and linux_path[1] == ':':
            drive_letter = linux_path[0].lower()
            rest_path = linux_path[2:].lstrip('/')
            linux_path = f"/mnt/{drive_letter}/{rest_path}" if rest_path else f"/mnt/{drive_letter}"
            
        return linux_path
    
    def get_effective_path(self, path):
        """根据当前操作模式获取有效路径
        
        Args:
            path: 原始路径
            
        Returns:
            根据操作模式转换后的有效路径
        """
        if self.operation_mode.get() == "server":
            return self.convert_windows_to_linux_path(path)
        else:
             return path  # Windows模式直接返回原路径
     
    def get_ssh_client(self, retry_count=3):
        """获取SSH客户端连接（支持持久连接和自动重连）
        
        Args:
            retry_count: 重试次数
            
        Returns:
            SSH客户端对象，如果连接失败返回None
        """
        if not PARAMIKO_AVAILABLE:
            raise Exception("paramiko库未安装，无法使用SSH功能")
        
        current_time = time.time()
        
        # 检查现有连接是否有效
        if self.ssh_client is not None:
            # 检查连接是否超时
            if (self.ssh_connection_time and 
                current_time - self.ssh_connection_time > self.ssh_connection_timeout):
                self.close_ssh_connection()
            # 检查连接复用次数是否超限
            elif self.connection_reuse_count >= self.max_reuse_count:
                print(f"连接复用次数达到上限({self.max_reuse_count})，重建连接")
                self.close_ssh_connection()
            # 检查连接是否仍然活跃
            elif not self._is_ssh_connection_alive():
                self.close_ssh_connection()
        
        # 如果没有有效连接，创建新连接（带重试机制）
        if self.ssh_client is None:
            last_error = None
            
            for attempt in range(retry_count):
                try:
                    self.ssh_client = paramiko.SSHClient()
                    self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    
                    host = self.ssh_config.get("host", "")
                    username = self.ssh_config.get("username", "")
                    password = self.ssh_config.get("password", "")
                    
                    if not all([host, username, password]):
                        raise Exception("SSH配置信息不完整")
                    
                    # 增加连接参数以提高稳定性
                    self.ssh_client.connect(
                        hostname=host,
                        username=username,
                        password=password,
                        timeout=60,  # 增加连接超时
                        banner_timeout=60,  # 增加banner超时
                        auth_timeout=60,  # 增加认证超时
                        look_for_keys=False,
                        allow_agent=False,
                        compress=True,  # 启用压缩减少网络负载
                        sock=None,
                        gss_auth=False,
                        gss_kex=False,
                        gss_deleg_creds=True,
                        gss_host=None
                    )
                    
                    # 设置TCP keepalive和socket选项以保持连接稳定
                    transport = self.ssh_client.get_transport()
                    if transport:
                        # 设置更长的keepalive间隔，减少服务器压力
                        transport.set_keepalive(120)  # 每2分钟发送keepalive
                        
                        # 设置socket选项
                        sock = transport.sock
                        if sock:
                            import socket
                            # 启用TCP keepalive
                            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                            # 设置keepalive参数（Windows）
                            if hasattr(socket, 'TCP_KEEPIDLE'):
                                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 120)
                            if hasattr(socket, 'TCP_KEEPINTVL'):
                                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 30)
                            if hasattr(socket, 'TCP_KEEPCNT'):
                                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
                            # 设置接收缓冲区大小
                            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
                            # 设置发送缓冲区大小
                            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
                            # 禁用Nagle算法以减少延迟
                            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    
                    # 记录连接时间
                    self.ssh_connection_time = current_time
                    self.ssh_last_activity = current_time
                    self.connection_reuse_count = 0  # 重置复用计数
                    
                    print(f"SSH连接建立成功，主机: {host}")
                    
                    # 连接成功，跳出重试循环
                    break
                    
                except Exception as e:
                    last_error = e
                    if self.ssh_client:
                        try:
                            self.ssh_client.close()
                        except:
                            pass
                        self.ssh_client = None
                        self.ssh_connection_time = None
                        self.ssh_last_activity = None
                    
                    # 如果不是最后一次尝试，等待后重试
                    if attempt < retry_count - 1:
                        wait_time = (attempt + 1) * 2  # 指数退避：2, 4, 6秒
                        time.sleep(wait_time)
                    
            # 如果所有重试都失败，抛出最后的错误
            if self.ssh_client is None and last_error:
                raise Exception(f"SSH连接失败（重试{retry_count}次后）: {str(last_error)}")
        
        # 更新最后活动时间和复用计数
        self.ssh_last_activity = current_time
        self.connection_reuse_count += 1
        return self.ssh_client
     
    def execute_ssh_command(self, command, retry_count=2):
         """执行SSH命令（带重试机制）
         
         Args:
             command: 要执行的命令
             retry_count: 重试次数
             
         Returns:
             tuple: (stdout, stderr, exit_code)
         """
         last_error = None
         
         for attempt in range(retry_count + 1):
             try:
                 ssh_client = self.get_ssh_client()
                 
                 # 设置更长的命令超时时间，适应大批量操作
                 stdin, stdout, stderr = ssh_client.exec_command(command, timeout=600)
                 
                 # 等待命令执行完成
                 exit_code = stdout.channel.recv_exit_status()
                 
                 stdout_text = stdout.read().decode('utf-8')
                 stderr_text = stderr.read().decode('utf-8')
                 
                 return stdout_text, stderr_text, exit_code
                 
             except Exception as e:
                 last_error = e
                 error_str = str(e).lower()
                 
                 # 检查是否是连接相关的错误
                 connection_errors = [
                     'connection reset',
                     'connection closed',
                     'connection lost',
                     'broken pipe',
                     'socket is closed',
                     '远程主机强迫关闭',
                     'connection aborted',
                     'connection refused'
                 ]
                 
                 is_connection_error = any(err in error_str for err in connection_errors)
                 
                 if is_connection_error and attempt < retry_count:
                     # 连接错误，关闭当前连接并重试
                     self.close_ssh_connection()
                     wait_time = (attempt + 1) * 3  # 指数退避：3, 6秒
                     time.sleep(wait_time)
                     continue
                 else:
                     # 非连接错误或已达到最大重试次数
                     break
         
         # 抛出最后的错误
         raise Exception(f"SSH命令执行失败（重试{retry_count}次后）: {str(last_error)}")
     
    def _is_ssh_connection_alive(self):
        """检查SSH连接是否仍然活跃
        
        Returns:
            bool: 连接是否活跃
        """
        if not self.ssh_client:
            return False
        
        try:
            # 发送一个简单的命令来测试连接
            transport = self.ssh_client.get_transport()
            if transport is None or not transport.is_active():
                return False
            
            # 执行一个轻量级命令
            stdin, stdout, stderr = self.ssh_client.exec_command('echo test', timeout=5)
            result = stdout.read().decode('utf-8').strip()
            return result == 'test'
        except:
            return False
    
    def close_ssh_connection(self):
        """关闭SSH连接并清理相关状态"""
        if self.ssh_client:
            try:
                print(f"关闭SSH连接，复用次数: {self.connection_reuse_count}")
                self.ssh_client.close()
            except:
                pass
            self.ssh_client = None
            self.ssh_connection_time = None
            self.ssh_last_activity = None
            self.connection_reuse_count = 0  # 重置复用计数
            # 清理目录缓存（连接断开后重新建立时需要重新检查）
            self.ssh_directory_cache.clear()
     
    def test_ssh_path_access(self, path):
         """测试SSH路径访问
         
         Args:
             path: 要测试的Linux路径
             
         Returns:
             bool: 路径是否可访问
         """
         try:
             command = f"test -e '{path}' && echo 'exists' || echo 'not_exists'"
             stdout, stderr, exit_code = self.execute_ssh_command(command)
             return stdout.strip() == 'exists'
         except:
             return False
     
    def create_ssh_directory(self, path):
        """通过SSH创建目录（带缓存优化）
        
        Args:
            path: 要创建的目录路径
            
        Returns:
            bool: 是否创建成功
        """
        # 检查缓存，如果已经创建过则直接返回成功
        if path in self.ssh_directory_cache:
            return True
        
        try:
            # 首先检查目录是否已存在
            check_command = f"test -d '{path}' && echo 'exists' || echo 'not_exists'"
            stdout, stderr, exit_code = self.execute_ssh_command(check_command)
            
            if exit_code == 0 and stdout.strip() == 'exists':
                # 目录已存在，添加到缓存
                self.ssh_directory_cache.add(path)
                return True
            
            # 目录不存在，创建目录
            create_command = f"mkdir -p '{path}'"
            stdout, stderr, exit_code = self.execute_ssh_command(create_command)
            
            if exit_code == 0:
                # 创建成功，添加到缓存
                self.ssh_directory_cache.add(path)
                return True
            else:
                return False
                
        except Exception as e:
            return False
     
    def open_target_config(self):
        """打开场景和子目录配置对话框"""
        config_window = tk.Toplevel(self.root)
        config_window.title("场景和子目录配置")
        config_window.geometry("700x500")
        config_window.resizable(True, True)
        config_window.transient(self.root)
        config_window.grab_set()
        
        # 居中显示对话框
        config_window.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (700 // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (500 // 2)
        config_window.geometry(f"700x500+{x}+{y}")
        
        # 主框架
        main_frame = ttk.Frame(config_window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 场景和子目录列表框架
        list_frame = ttk.LabelFrame(main_frame, text="场景和子目录列表", padding="5")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # 创建Treeview来显示场景和子目录的层级结构
        tree = ttk.Treeview(list_frame, show='tree headings', height=12)
        tree.heading('#0', text='场景/子目录')
        tree.column('#0', width=250)
        
        # 添加路径列
        tree['columns'] = ('path',)
        tree.heading('path', text='路径')
        tree.column('path', width=400)
        
        # 滚动条
        scrollbar_tree = ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar_tree.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_tree.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 刷新树形列表
        def refresh_tree():
            for item in tree.get_children():
                tree.delete(item)
            for scenario_name, subdirs in self.scenarios.items():
                scenario_item = tree.insert('', tk.END, text=scenario_name, values=('',), tags=('scenario',))
                for subdir_name, subdir_path in subdirs.items():
                    tree.insert(scenario_item, tk.END, text=subdir_name, values=(subdir_path,), tags=('subdir',))
                tree.item(scenario_item, open=True)  # 展开场景节点
        
        # 配置标签样式
        tree.tag_configure('scenario', background='#e6f3ff')
        tree.tag_configure('subdir', background='#f0f0f0')
        
        refresh_tree()
        
        # 按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        # 添加场景
        def add_scenario():
            add_window = tk.Toplevel(config_window)
            add_window.title("添加场景")
            add_window.geometry("350x120")
            add_window.transient(config_window)
            add_window.grab_set()
            
            # 居中显示对话框
            add_window.update_idletasks()
            x = config_window.winfo_x() + (config_window.winfo_width() // 2) - (350 // 2)
            y = config_window.winfo_y() + (config_window.winfo_height() // 2) - (120 // 2)
            add_window.geometry(f"350x120+{x}+{y}")
            
            frame = ttk.Frame(add_window, padding="10")
            frame.pack(fill=tk.BOTH, expand=True)
            
            ttk.Label(frame, text="场景名称:").grid(row=0, column=0, sticky=tk.W, pady=5)
            name_var = tk.StringVar()
            ttk.Entry(frame, textvariable=name_var, width=25).grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=5)
            
            def save_scenario():
                name = name_var.get().strip()
                if not name:
                    messagebox.showwarning("警告", "请填写场景名称")
                    return
                if name in self.scenarios:
                    messagebox.showwarning("警告", "该场景名称已存在")
                    return
                
                self.scenarios[name] = {}
                self.save_config()
                refresh_tree()
                self.update_target_checkboxes()
                add_window.destroy()
            
            button_frame_add = ttk.Frame(frame)
            button_frame_add.grid(row=1, column=0, columnspan=2, pady=10)
            ttk.Button(button_frame_add, text="保存", command=save_scenario).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame_add, text="取消", command=add_window.destroy).pack(side=tk.LEFT, padx=5)
            
            frame.columnconfigure(1, weight=1)
        
        # 添加子目录
        def add_subdir():
            selection = tree.selection()
            if not selection:
                messagebox.showwarning("警告", "请先选择一个场景")
                return
            
            item = tree.item(selection[0])
            # 判断选中的是场景还是子目录
            if 'scenario' in tree.item(selection[0], 'tags'):
                scenario_name = item['text']
            elif 'subdir' in tree.item(selection[0], 'tags'):
                parent_item = tree.parent(selection[0])
                scenario_name = tree.item(parent_item)['text']
            else:
                messagebox.showwarning("警告", "请选择一个场景")
                return
            
            add_window = tk.Toplevel(config_window)
            add_window.title(f"为场景 '{scenario_name}' 添加子目录")
            add_window.geometry("450x150")
            add_window.transient(config_window)
            add_window.grab_set()
            
            # 居中显示对话框
            add_window.update_idletasks()
            x = config_window.winfo_x() + (config_window.winfo_width() // 2) - (450 // 2)
            y = config_window.winfo_y() + (config_window.winfo_height() // 2) - (150 // 2)
            add_window.geometry(f"450x150+{x}+{y}")
            
            frame = ttk.Frame(add_window, padding="10")
            frame.pack(fill=tk.BOTH, expand=True)
            
            ttk.Label(frame, text="子目录名称:").grid(row=0, column=0, sticky=tk.W, pady=5)
            name_var = tk.StringVar()
            ttk.Entry(frame, textvariable=name_var, width=30).grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=5)
            
            ttk.Label(frame, text="路径:").grid(row=1, column=0, sticky=tk.W, pady=5)
            path_var = tk.StringVar()
            path_entry = ttk.Entry(frame, textvariable=path_var, width=30)
            path_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=5)
            
            def browse_path():
                directory = filedialog.askdirectory(title="选择目标目录")
                if directory:
                    path_var.set(directory)
            
            ttk.Button(frame, text="浏览", command=browse_path).grid(row=1, column=2, padx=5, pady=5)
            
            def save_subdir():
                name = name_var.get().strip()
                path = path_var.get().strip()
                if not name or not path:
                    messagebox.showwarning("警告", "请填写完整的名称和路径")
                    return
                if name in self.scenarios[scenario_name]:
                    messagebox.showwarning("警告", "该子目录名称在此场景中已存在")
                    return
                if not os.path.exists(path):
                    messagebox.showwarning("警告", "路径不存在")
                    return
                
                self.scenarios[scenario_name][name] = path
                self.save_config()
                refresh_tree()
                self.update_target_checkboxes()
                add_window.destroy()
            
            button_frame_add = ttk.Frame(frame)
            button_frame_add.grid(row=2, column=0, columnspan=3, pady=10)
            ttk.Button(button_frame_add, text="保存", command=save_subdir).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame_add, text="取消", command=add_window.destroy).pack(side=tk.LEFT, padx=5)
            
            frame.columnconfigure(1, weight=1)
        
        # 删除功能
        def delete_item():
            selection = tree.selection()
            if not selection:
                messagebox.showwarning("警告", "请选择要删除的项目")
                return
            
            item = tree.item(selection[0])
            if 'scenario' in tree.item(selection[0], 'tags'):
                # 删除场景
                scenario_name = item['text']
                if messagebox.askyesno("确认", f"确定要删除场景 '{scenario_name}' 及其所有子目录吗？"):
                    del self.scenarios[scenario_name]
                    self.save_config()
                    refresh_tree()
                    self.update_target_checkboxes()
            elif 'subdir' in tree.item(selection[0], 'tags'):
                # 删除子目录
                subdir_name = item['text']
                parent_item = tree.parent(selection[0])
                scenario_name = tree.item(parent_item)['text']
                if messagebox.askyesno("确认", f"确定要删除子目录 '{subdir_name}' 吗？"):
                    del self.scenarios[scenario_name][subdir_name]
                    self.save_config()
                    refresh_tree()
                    self.update_target_checkboxes()
        
        # 编辑功能
        def edit_item():
            selection = tree.selection()
            if not selection:
                messagebox.showwarning("警告", "请选择要编辑的项目")
                return
            
            item = tree.item(selection[0])
            if 'scenario' in tree.item(selection[0], 'tags'):
                # 编辑场景名称
                old_name = item['text']
                
                edit_window = tk.Toplevel(config_window)
                edit_window.title("编辑场景名称")
                edit_window.geometry("350x120")
                edit_window.transient(config_window)
                edit_window.grab_set()
                
                # 居中显示对话框
                edit_window.update_idletasks()
                x = config_window.winfo_x() + (config_window.winfo_width() // 2) - (350 // 2)
                y = config_window.winfo_y() + (config_window.winfo_height() // 2) - (120 // 2)
                edit_window.geometry(f"350x120+{x}+{y}")
                
                frame = ttk.Frame(edit_window, padding="10")
                frame.pack(fill=tk.BOTH, expand=True)
                
                ttk.Label(frame, text="场景名称:").grid(row=0, column=0, sticky=tk.W, pady=5)
                name_var = tk.StringVar(value=old_name)
                ttk.Entry(frame, textvariable=name_var, width=25).grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=5)
                
                def save_scenario():
                    name = name_var.get().strip()
                    if not name:
                        messagebox.showwarning("警告", "请填写场景名称")
                        return
                    if name != old_name and name in self.scenarios:
                        messagebox.showwarning("警告", "该场景名称已存在")
                        return
                    
                    # 重命名场景
                    if old_name in self.scenarios:
                        self.scenarios[name] = self.scenarios.pop(old_name)
                    self.save_config()
                    refresh_tree()
                    self.update_target_checkboxes()
                    edit_window.destroy()
                
                button_frame_edit = ttk.Frame(frame)
                button_frame_edit.grid(row=1, column=0, columnspan=2, pady=10)
                ttk.Button(button_frame_edit, text="保存", command=save_scenario).pack(side=tk.LEFT, padx=5)
                ttk.Button(button_frame_edit, text="取消", command=edit_window.destroy).pack(side=tk.LEFT, padx=5)
                
                frame.columnconfigure(1, weight=1)
                
            elif 'subdir' in tree.item(selection[0], 'tags'):
                # 编辑子目录
                old_subdir_name = item['text']
                old_path = item['values'][0]
                parent_item = tree.parent(selection[0])
                scenario_name = tree.item(parent_item)['text']
                
                edit_window = tk.Toplevel(config_window)
                edit_window.title(f"编辑场景 '{scenario_name}' 的子目录")
                edit_window.geometry("450x150")
                edit_window.transient(config_window)
                edit_window.grab_set()
                
                # 居中显示对话框
                edit_window.update_idletasks()
                x = config_window.winfo_x() + (config_window.winfo_width() // 2) - (450 // 2)
                y = config_window.winfo_y() + (config_window.winfo_height() // 2) - (150 // 2)
                edit_window.geometry(f"450x150+{x}+{y}")
                
                frame = ttk.Frame(edit_window, padding="10")
                frame.pack(fill=tk.BOTH, expand=True)
                
                ttk.Label(frame, text="子目录名称:").grid(row=0, column=0, sticky=tk.W, pady=5)
                name_var = tk.StringVar(value=old_subdir_name)
                ttk.Entry(frame, textvariable=name_var, width=30).grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=5)
                
                ttk.Label(frame, text="路径:").grid(row=1, column=0, sticky=tk.W, pady=5)
                path_var = tk.StringVar(value=old_path)
                path_entry = ttk.Entry(frame, textvariable=path_var, width=30)
                path_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=5)
                
                def browse_path():
                    directory = filedialog.askdirectory(title="选择目标目录")
                    if directory:
                        path_var.set(directory)
                
                ttk.Button(frame, text="浏览", command=browse_path).grid(row=1, column=2, padx=5, pady=5)
                
                def save_subdir():
                    name = name_var.get().strip()
                    path = path_var.get().strip()
                    if not name or not path:
                        messagebox.showwarning("警告", "请填写完整的名称和路径")
                        return
                    if name != old_subdir_name and name in self.scenarios[scenario_name]:
                        messagebox.showwarning("警告", "该子目录名称在此场景中已存在")
                        return
                    if not os.path.exists(path):
                        messagebox.showwarning("警告", "路径不存在")
                        return
                    
                    # 删除旧的，添加新的
                    if old_subdir_name in self.scenarios[scenario_name]:
                        del self.scenarios[scenario_name][old_subdir_name]
                    self.scenarios[scenario_name][name] = path
                    self.save_config()
                    refresh_tree()
                    self.update_target_checkboxes()
                    edit_window.destroy()
                
                button_frame_edit = ttk.Frame(frame)
                button_frame_edit.grid(row=2, column=0, columnspan=3, pady=10)
                ttk.Button(button_frame_edit, text="保存", command=save_subdir).pack(side=tk.LEFT, padx=5)
                ttk.Button(button_frame_edit, text="取消", command=edit_window.destroy).pack(side=tk.LEFT, padx=5)
                
                frame.columnconfigure(1, weight=1)
        
        ttk.Button(button_frame, text="添加场景", command=add_scenario).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="添加子目录", command=add_subdir).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="编辑", command=edit_item).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="删除", command=delete_item).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="关闭", command=config_window.destroy).pack(side=tk.RIGHT, padx=5)
    
    def create_widgets(self):
        """创建界面组件"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # 源目录选择
        ttk.Label(main_frame, text="数据集目录:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.source_dir, width=50).grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=5)
        ttk.Button(main_frame, text="浏览", command=self.browse_dataset_dir).grid(row=0, column=2, padx=5, pady=5)
        
        # 检测按钮
        self.detect_btn = ttk.Button(main_frame, text="开始检测", command=self.start_detection)
        self.detect_btn.grid(row=1, column=0, columnspan=3, pady=10)
        
        # 状态显示
        self.status_label = ttk.Label(main_frame, text="请选择数据集目录")
        self.status_label.grid(row=2, column=0, columnspan=3, pady=5)
        
        # 操作模式显示
        self.mode_label = ttk.Label(main_frame, text="", foreground='blue', font=('Arial', 9))
        self.mode_label.grid(row=2, column=2, sticky=tk.E, pady=5)
        self.update_mode_display()
        
        # 移除图片列表展示区域以拓宽目标目录展示
        
        # 控制按钮框架
        control_frame = ttk.LabelFrame(main_frame, text="图片范围选择", padding="5")
        control_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        
        # 当前打开的图片显示
        current_frame = ttk.Frame(control_frame)
        current_frame.grid(row=0, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(current_frame, text="当前打开图片:").grid(row=0, column=0, sticky=tk.W)
        self.current_image_label = ttk.Label(current_frame, text="无")
        self.current_image_label.grid(row=0, column=1, sticky=tk.W, padx=10)
        
        # 手动检测按钮
        self.manual_detect_btn = ttk.Button(current_frame, text="手动检测", command=self.start_manual_detection)
        self.manual_detect_btn.grid(row=0, column=2, sticky=tk.W, padx=(20, 0))
        
        # 检测状态标签
        self.detect_status_label = ttk.Label(current_frame, text="", foreground="blue")
        self.detect_status_label.grid(row=0, column=3, sticky=tk.W, padx=(10, 0))
        
        # 起始和结束图片设置
        ttk.Button(control_frame, text="设为起始图片", command=self.set_start_image).grid(row=1, column=0, padx=5, pady=5)
        ttk.Button(control_frame, text="设为结束图片", command=self.set_end_image).grid(row=1, column=1, padx=5, pady=5)
        
        # 显示选择范围
        self.range_label = ttk.Label(control_frame, text="选择范围: 未设置")
        self.range_label.grid(row=2, column=0, columnspan=2, pady=5)
        
        # 目标目录选择（拓宽显示区域）
        target_frame = ttk.LabelFrame(main_frame, text="目标操作", padding="5")
        target_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        target_frame.columnconfigure(0, weight=1)
        target_frame.rowconfigure(0, weight=1)
        
        # 创建可调节大小的左右分栏布局
        content_paned = ttk.PanedWindow(target_frame, orient=tk.HORIZONTAL)
        content_paned.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        
        # 左侧：目录列表框架
        dir_list_frame = ttk.LabelFrame(content_paned, text="选择目标目录", padding="5")
        dir_list_frame.columnconfigure(0, weight=1)
        dir_list_frame.rowconfigure(0, weight=1)
        
        # 创建滚动框架用于复选框列表
        self.canvas = tk.Canvas(dir_list_frame, height=280, relief="solid", bd=1)
        scrollbar = ttk.Scrollbar(dir_list_frame, orient="vertical", command=self.canvas.yview)
        self.target_checkboxes_frame = ttk.Frame(self.canvas)
        
        # 右侧：操作信息框架
        info_frame = ttk.LabelFrame(content_paned, text="操作信息", padding="5")
        info_frame.columnconfigure(0, weight=1)
        info_frame.rowconfigure(1, weight=1)
        
        # 将左右两个框架添加到PanedWindow中
        content_paned.add(dir_list_frame, weight=1)
        content_paned.add(info_frame, weight=1)
        
        # 操作状态显示
        self.operation_status = tk.Text(info_frame, height=12, width=40, wrap=tk.WORD, 
                                       relief="solid", bd=1, bg="#ffffff", 
                                       font=('Consolas', 9), state=tk.DISABLED)
        info_scrollbar = ttk.Scrollbar(info_frame, orient="vertical", command=self.operation_status.yview)
        self.operation_status.configure(yscrollcommand=info_scrollbar.set)
        
        ttk.Label(info_frame, text="操作日志:").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        self.operation_status.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        info_scrollbar.grid(row=1, column=1, sticky=(tk.N, tk.S))
        
        # 操作按钮框架
        operation_btn_frame = ttk.Frame(info_frame)
        operation_btn_frame.grid(row=2, column=0, columnspan=2, pady=(10, 0), sticky=(tk.W, tk.E))
        
        # 复制和移动按钮
        ttk.Button(operation_btn_frame, text="复制图片", command=self.copy_images).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(operation_btn_frame, text="移动图片", command=self.move_images).pack(side=tk.LEFT)
        
        # 添加初始日志信息
        self.operation_status.config(state=tk.NORMAL)
        self.operation_status.insert(tk.END, "欢迎使用图片管理器\n")
        self.operation_status.insert(tk.END, "请选择数据集目录开始检测\n")
        self.operation_status.insert(tk.END, "选择目标目录后可进行复制或移动操作\n")
        self.operation_status.config(state=tk.DISABLED)
        
        self.target_checkboxes_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.target_checkboxes_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        
        # 绑定鼠标滚轮事件
        def on_mousewheel(event):
            # 检查canvas是否有滚动内容
            if self.canvas.winfo_exists():
                # 获取滚动区域
                bbox = self.canvas.bbox("all")
                if bbox and bbox[3] > self.canvas.winfo_height():
                    self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        # 绑定滚轮事件到多个组件
        def bind_mousewheel(widget):
            widget.bind("<MouseWheel>", on_mousewheel)
            # 递归绑定到所有子组件
            for child in widget.winfo_children():
                bind_mousewheel(child)
        
        bind_mousewheel(self.canvas)
        bind_mousewheel(self.target_checkboxes_frame)
        bind_mousewheel(dir_list_frame)
        
        self.canvas.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        # 配置按钮
        config_btn_frame = ttk.Frame(dir_list_frame)
        config_btn_frame.grid(row=1, column=0, columnspan=2, pady=(5, 0), sticky=tk.W)
        ttk.Button(config_btn_frame, text="配置目录", command=self.open_target_config).pack(side=tk.LEFT)
        ttk.Button(config_btn_frame, text="全部展开", command=self.expand_all_scenarios).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(config_btn_frame, text="全部收起", command=self.collapse_all_scenarios).pack(side=tk.LEFT, padx=(5, 0))
        
        # 存储复选框变量的字典
        self.target_checkbox_vars = {}
        
        # 初始化目标目录复选框
        self.update_target_checkboxes()
    
    def update_mode_display(self):
        """更新操作模式显示"""
        mode = self.operation_mode.get()
        if mode == "server":
            host = self.ssh_config.get("host", "未配置")
            self.mode_label.config(text=f"服务器模式: {host}")
        else:
            self.mode_label.config(text="Windows本地模式")
        
    def add_operation_log(self, message):
        """添加操作日志"""
        if hasattr(self, 'operation_status'):
            self.operation_status.config(state=tk.NORMAL)
            timestamp = time.strftime("%H:%M:%S")
            self.operation_status.insert(tk.END, f"[{timestamp}] {message}\n")
            self.operation_status.see(tk.END)
            self.operation_status.config(state=tk.DISABLED)
            self.root.update_idletasks()
    
    def toggle_scenario_collapse(self, scenario_name):
        """切换场景的折叠/展开状态"""
        self.scenario_collapsed[scenario_name] = not self.scenario_collapsed.get(scenario_name, False)
        
        # 优化：只更新相关场景的显示状态，而不是重建整个界面
        self.update_scenario_display(scenario_name)
    
    def expand_all_scenarios(self):
        """展开所有场景"""
        if hasattr(self, 'scenarios') and self.scenarios:
            for scenario_name in self.scenarios.keys():
                self.scenario_collapsed[scenario_name] = False
                self.update_scenario_display(scenario_name, update_scroll=False)
            # 统一更新滚动区域，提高性能
            self.update_canvas_scroll()
        self.add_operation_log("已展开所有场景")
    
    def collapse_all_scenarios(self):
        """收起所有场景"""
        if hasattr(self, 'scenarios') and self.scenarios:
            for scenario_name in self.scenarios.keys():
                self.scenario_collapsed[scenario_name] = True
                self.update_scenario_display(scenario_name, update_scroll=False)
            # 统一更新滚动区域，提高性能
            self.update_canvas_scroll()
        self.add_operation_log("已收起所有场景")
    
    def on_mousewheel(self, event):
        """鼠标滚轮事件处理"""
        # 检查canvas是否有滚动内容
        if hasattr(self, 'canvas') and self.canvas.winfo_exists():
            # 获取滚动区域
            bbox = self.canvas.bbox("all")
            if bbox and bbox[3] > self.canvas.winfo_height():
                self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
    
    def update_scenario_display(self, scenario_name, update_scroll=True):
        """优化：只更新指定场景的显示状态"""
        if not hasattr(self, 'scenario_widgets'):
            return
            
        if scenario_name in self.scenario_widgets:
            scenario_data = self.scenario_widgets[scenario_name]
            is_collapsed = self.scenario_collapsed.get(scenario_name, False)
            collapse_symbol = "▶" if is_collapsed else "▼"
            
            # 更新场景标签的折叠符号
            scenario_data['label'].config(text=f"{collapse_symbol} 场景: {scenario_name}")
            
            # 显示或隐藏子目录复选框
            for checkbox in scenario_data['checkboxes']:
                if is_collapsed:
                    checkbox.grid_remove()  # 隐藏但不销毁
                else:
                    checkbox.grid()  # 重新显示
            
            # 根据参数决定是否更新Canvas的滚动区域
            if update_scroll:
                self.update_canvas_scroll()
    
    def update_canvas_scroll(self):
        """更新Canvas的滚动区域"""
        if hasattr(self, 'target_checkboxes_frame') and hasattr(self, 'canvas'):
            self.target_checkboxes_frame.update_idletasks()
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    
    def update_target_checkboxes(self):
        """更新目标目录复选框列表"""
        if hasattr(self, 'target_checkboxes_frame'):
            # 清除现有的复选框
            for widget in self.target_checkboxes_frame.winfo_children():
                widget.destroy()
            
            # 清除旧的变量和组件缓存
            self.target_checkbox_vars.clear()
            self.scenario_widgets = {}  # 缓存场景组件
            
            row = 0
            # 为每个场景和子目录创建复选框
            for scenario_name, subdirs in self.scenarios.items():
                # 初始化场景折叠状态（默认展开）
                if scenario_name not in self.scenario_collapsed:
                    self.scenario_collapsed[scenario_name] = False
                
                is_collapsed = self.scenario_collapsed[scenario_name]
                collapse_symbol = "▶" if is_collapsed else "▼"
                
                # 创建可点击的场景标签
                scenario_frame = ttk.Frame(self.target_checkboxes_frame)
                scenario_frame.grid(row=row, column=0, sticky=tk.W, pady=(5, 2))
                
                scenario_label = ttk.Label(
                    scenario_frame,
                    text=f"{collapse_symbol} 场景: {scenario_name}",
                    font=('TkDefaultFont', 9, 'bold'),
                    cursor="hand2"
                )
                scenario_label.pack(side=tk.LEFT)
                
                # 绑定点击事件和滚轮事件
                scenario_label.bind("<Button-1>", lambda e, name=scenario_name: self.toggle_scenario_collapse(name))
                scenario_label.bind("<MouseWheel>", self.on_mousewheel)
                scenario_frame.bind("<MouseWheel>", self.on_mousewheel)
                
                # 缓存场景组件
                scenario_checkboxes = []
                self.scenario_widgets[scenario_name] = {
                    'frame': scenario_frame,
                    'label': scenario_label,
                    'checkboxes': scenario_checkboxes
                }
                
                row += 1
                
                # 为场景下的每个子目录创建复选框（始终创建，但根据折叠状态决定是否显示）
                for subdir_name, subdir_path in subdirs.items():
                    var = tk.BooleanVar()
                    # 使用场景名和子目录名的组合作为键，确保唯一性
                    key = f"{scenario_name}::{subdir_name}"
                    self.target_checkbox_vars[key] = var
                    
                    checkbox = ttk.Checkbutton(
                        self.target_checkboxes_frame,
                        text=f"  └ {subdir_name} ({subdir_path})",
                        variable=var
                    )
                    
                    # 根据折叠状态决定是否显示
                    checkbox.grid(row=row, column=0, sticky=tk.W, pady=1, padx=(20, 0))
                    if is_collapsed:
                        checkbox.grid_remove()  # 如果折叠则隐藏
                    
                    # 为新创建的复选框绑定滚轮事件
                    checkbox.bind("<MouseWheel>", self.on_mousewheel)
                    
                    # 添加到场景的复选框列表
                    scenario_checkboxes.append(checkbox)
                    
                    row += 1
            
            # 如果没有场景，显示提示信息
            if not self.scenarios:
                no_data_label = ttk.Label(
                    self.target_checkboxes_frame,
                    text="暂无配置的场景和子目录",
                    foreground='gray'
                )
                no_data_label.grid(row=0, column=0, sticky=tk.W, pady=5)
    
    def browse_dataset_dir(self):
        """浏览数据集目录"""
        directory = filedialog.askdirectory(title="选择数据集目录")
        if directory:
            self.source_dir.set(directory)
    
    def start_detection(self):
        """开始检测图片目录"""
        if not self.source_dir.get():
            messagebox.showerror("错误", "请先选择数据集目录")
            return
        
        if not os.path.exists(self.source_dir.get()):
            messagebox.showerror("错误", "选择的目录不存在")
            return
        
        if self.is_detecting:
            self.stop_detection()
        else:
            self.add_operation_log(f"开始检测目录: {self.source_dir.get()}")
            self.is_detecting = True
            self.detect_btn.config(text="停止检测")
            self.status_label.config(text="正在检测数据集目录...")
            
            # 在新线程中执行检测
            threading.Thread(target=self.detect_images, daemon=True).start()
            
            # 启动文件监控
            self.start_file_monitoring()
    
    def stop_detection(self):
        """停止检测"""
        self.is_detecting = False
        self.detect_btn.config(text="开始检测")
        self.status_label.config(text="检测已停止")
        
        # 停止文件监控
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
        
        # 停止窗口监控
        self.stop_window_monitoring()
    
    def detect_images(self):
        """检测数据集目录下images子目录中的图片文件"""
        try:
            image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}
            self.image_files = []
            
            # 检查数据集目录结构
            dataset_path = self.source_dir.get()
            
            if self.operation_mode.get() == "server":
                # 服务器模式：转换为服务器路径并通过SSH检查
                server_dataset_path = self.convert_smb_to_linux_path(dataset_path)
                server_images_path = f"{server_dataset_path}/images"
                server_labels_path = f"{server_dataset_path}/labels"
                
                # 检查SSH连接
                try:
                    ssh_client = self.get_ssh_client()
                    if not ssh_client:
                        error_msg = "无法建立SSH连接"
                        self.root.after(0, lambda: self.status_label.config(text=f"错误: {error_msg}"))
                        return
                except Exception as e:
                    error_msg = f"SSH连接失败: {str(e)}"
                    self.root.after(0, lambda: self.status_label.config(text=f"错误: {error_msg}"))
                    return
                
                # 检查images目录是否存在
                stdout, stderr, exit_code = self.execute_ssh_command(f"test -d '{server_images_path}' && echo 'exists' || echo 'not_exists'")
                images_exists = stdout.strip() == 'exists'
                
                if not images_exists:
                    self.root.after(0, lambda: self.status_label.config(text="错误: 数据集目录下未找到images子目录"))
                    return
                
                # 检查labels目录是否存在
                stdout, stderr, exit_code = self.execute_ssh_command(f"test -d '{server_labels_path}' && echo 'exists' || echo 'not_exists'")
                labels_exists = stdout.strip() == 'exists'
                
                if not labels_exists:
                    self.root.after(0, lambda: self.status_label.config(text="警告: 数据集目录下未找到labels子目录"))
                
                # 更新状态为正在扫描
                self.root.after(0, lambda: self.status_label.config(text="正在扫描图片文件..."))
                
                # 扫描images目录中的图片文件 - 优化版本，减少输出
                find_command = f"find '{server_images_path}' -maxdepth 1 -type f \\( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.bmp' -o -iname '*.gif' -o -iname '*.tiff' -o -iname '*.webp' \\) | wc -l"
                
                # 先获取文件数量
                stdout, stderr, exit_code = self.execute_ssh_command(find_command)
                file_count = int(stdout.strip()) if stdout.strip().isdigit() else 0
                
                if file_count > 0:
                    # 如果有文件，再获取文件列表
                    find_command = f"find '{server_images_path}' -maxdepth 1 -type f \\( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.bmp' -o -iname '*.gif' -o -iname '*.tiff' -o -iname '*.webp' \\) | sort"
                    stdout, stderr, exit_code = self.execute_ssh_command(find_command)
                    
                    if exit_code == 0:
                        server_files = stdout.strip().split('\n') if stdout.strip() else []
                        
                        # 批量转换路径，避免逐个日志输出
                        for server_file in server_files:
                            if server_file.strip():  # 跳过空行
                                relative_path = server_file.replace(server_dataset_path, "").lstrip("/")
                                local_file_path = os.path.join(dataset_path, relative_path).replace("/", "\\")
                                self.image_files.append(local_file_path)
                    else:
                        self.add_operation_log(f"[服务器模式] 文件扫描失败: {stderr.strip()}")
                else:
                    self.add_operation_log(f"[服务器模式] 未找到任何图片文件")
            else:
                # 本地模式：使用原有逻辑
                dataset_path_obj = Path(dataset_path)
                images_path = dataset_path_obj / "images"
                labels_path = dataset_path_obj / "labels"
                
                if not images_path.exists():
                    self.root.after(0, lambda: self.status_label.config(text="错误: 数据集目录下未找到images子目录"))
                    return
                
                if not labels_path.exists():
                    self.root.after(0, lambda: self.status_label.config(text="警告: 数据集目录下未找到labels子目录"))
                
                # 扫描images目录中的图片文件
                for file_path in images_path.iterdir():
                    if file_path.is_file() and file_path.suffix.lower() in image_extensions:
                        self.image_files.append(str(file_path))
            
            # 按文件名排序
            self.image_files.sort(key=lambda x: self.natural_sort_key(os.path.basename(x)))
            
            # 更新界面
            self.root.after(0, self.update_image_list)
            
            # 检查有序性
            is_ordered = self.check_image_order()
            status_text = f"检测完成: 在images目录找到 {len(self.image_files)} 个图片文件"
            if is_ordered:
                status_text += " (有序)"
            else:
                status_text += " (无序)"
            
            # 添加简化的检测完成日志
            mode_text = "服务器" if self.operation_mode.get() == "server" else "本地"
            self.add_operation_log(f"[{mode_text}模式] 检测完成: 找到 {len(self.image_files)} 个图片文件")
            self.root.after(0, lambda: self.status_label.config(text=status_text))
            
        except Exception as e:
            error_msg = str(e)
            self.root.after(0, lambda: messagebox.showerror("错误", f"检测过程中出现错误: {error_msg}"))
    
    def natural_sort_key(self, text):
        """自然排序键函数"""
        def convert(text):
            return int(text) if text.isdigit() else text.lower()
        return [convert(c) for c in re.split('([0-9]+)', text)]
    
    def check_image_order(self):
        """检查图片文件是否有序"""
        if len(self.image_files) <= 1:
            return True
        
        # 简单的有序性检查：按文件名排序后是否与原顺序一致
        sorted_files = sorted(self.image_files, key=lambda x: self.natural_sort_key(os.path.basename(x)))
        return self.image_files == sorted_files
    
    def update_image_list(self):
        """更新图片列表显示（已移除图片列表展示）"""
        # 图片列表展示已移除，此方法保留为兼容性
        pass
    
    def start_file_monitoring(self):
        """启动文件监控"""
        if self.observer:
            return
        
        event_handler = ImageFileHandler(self.on_image_opened)
        self.observer = Observer()
        self.observer.schedule(event_handler, self.source_dir.get(), recursive=False)
        self.observer.start()
        
        # 启动窗口监控（如果可用）
        if WIN32_AVAILABLE:
            self.start_window_monitoring()
        else:
            print("窗口监控功能不可用，仅使用基础文件监控")
    
    def start_window_monitoring(self):
        """启动窗口监控线程"""
        if self.window_monitor_running:
            return
        
        self.window_monitor_running = True
        self.window_monitor_thread = threading.Thread(target=self.monitor_active_window, daemon=True)
        self.window_monitor_thread.start()
    
    def stop_window_monitoring(self):
        """停止窗口监控"""
        self.window_monitor_running = False
        if self.window_monitor_thread:
            self.window_monitor_thread.join(timeout=1)
    
    def monitor_active_window(self):
        """监控活动窗口，检测当前显示的图片"""
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}
        
        while self.window_monitor_running:
            try:
                 # 获取当前活动窗口
                 hwnd = win32gui.GetForegroundWindow()
                 if hwnd:
                     # 获取窗口标题和类名
                     window_title = win32gui.GetWindowText(hwnd)
                     class_name = win32gui.GetClassName(hwnd)
                     
                     # 只监控特定的图片查看器程序，排除文件浏览器
                     image_viewer_classes = [
                         'MSPaintApp',  # 画图工具
                         'PhotosApp',   # Windows照片应用
                         'ApplicationFrameWindow',  # Windows 10/11 UWP应用框架（包括照片应用）
                         'Windows.UI.Core.CoreWindow',  # UWP应用核心窗口
                         'IrfanView',   # IrfanView
                         'PictureManagerWnd',  # Office图片管理器
                         'ImageGlass.MainForm',  # ImageGlass
                         'HwndWrapper[DefaultDomain;;',  # WPF应用
                         'WindowsForms10.Window.8.app.0.141b42a_r6_ad1'  # Windows Forms应用
                     ]
                     
                     # 排除文件浏览器和其他非图片查看器窗口
                     excluded_classes = [
                         'CabinetWClass',     # Windows资源管理器
                         'ExploreWClass',     # Windows资源管理器
                         'Progman',           # 桌面
                         'WorkerW',           # 桌面工作区
                         'Shell_TrayWnd',     # 任务栏
                         'DV2ControlHost',    # 资源管理器详细信息面板
                         'DirectUIHWND',      # 资源管理器UI元素
                         '#32770',            # 对话框
                         'ConsoleWindowClass', # 控制台窗口
                         'Chrome_WidgetWin_1', # Chrome浏览器
                         'MozillaWindowClass'  # Firefox浏览器
                     ]
                     
                     if class_name in excluded_classes:
                         # 跳过文件浏览器窗口
                         pass
                     elif class_name in image_viewer_classes or self.is_likely_image_viewer(window_title, class_name):
                        #  print(f"检测到图片查看器: {class_name} - {window_title}")
                         
                         # 特殊处理UWP应用（如Windows照片应用）
                         if class_name == 'ApplicationFrameWindow':
                             # 对于UWP应用，需要检查子窗口来获取实际内容
                             self.handle_uwp_photo_app(hwnd, window_title)
                         elif window_title:
                             # 从窗口标题中提取可能的文件路径
                             potential_files = self.extract_image_paths_from_title(window_title)
                            #  print(f"提取到的文件路径: {potential_files}")
                             
                             for file_path in potential_files:
                                 if self.validate_and_set_current_image(file_path):
                                     break
                     else:
                         # 输出当前窗口信息用于调试
                         if window_title and any(ext in window_title.lower() for ext in ['.jpg', '.jpeg', '.png', '.bmp', '.gif']):
                             print(f"未识别的窗口: {class_name} - {window_title}")
                             
                             # 尝试通过进程检测（适用于通过右键菜单打开的应用）
                             try:
                                 _, pid = win32process.GetWindowThreadProcessId(hwnd)
                                 process = psutil.Process(pid)
                                 process_name = process.name().lower()
                                 
                                 # 检查是否是图片查看相关的进程
                                 photo_processes = ['microsoft.photos.exe', 'photos.exe', 'photoviewer.dll', 
                                                  'mspaint.exe', 'photoshop.exe', 'gimp.exe']
                                 
                                 if any(name in process_name for name in photo_processes):
                                     print(f"通过进程名检测到图片应用: {process_name}")
                                     self.detect_opened_image_from_process(process)
                                     
                             except Exception as e:
                                 print(f"进程检测失败: {e}")
            except Exception as e:
                 print(f"窗口监控错误: {e}")
             
            time.sleep(1)  # 每秒检查一次
    
    def is_likely_image_viewer(self, window_title, class_name):
        """判断是否可能是图片查看器"""
        # 首先检查是否是明确排除的窗口类
        excluded_classes = [
            'CabinetWClass', 'ExploreWClass', 'Progman', 'WorkerW', 
            'Shell_TrayWnd', 'DV2ControlHost', 'DirectUIHWND', '#32770',
            'ConsoleWindowClass', 'Chrome_WidgetWin_1', 'MozillaWindowClass'
        ]
        
        if class_name in excluded_classes:
            return False
            
        # 检查窗口标题是否包含图片文件扩展名
        image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp']
        title_lower = window_title.lower()
        
        # 如果标题包含图片扩展名，且不是文件浏览器相关的标题
        has_image_ext = any(ext in title_lower for ext in image_extensions)
        
        # 更严格的文件浏览器检测
        explorer_keywords = [
            '文件夹', 'folder', '资源管理器', 'explorer', 'file explorer',
            '此电脑', 'this pc', '我的电脑', 'my computer', '计算机', 'computer',
            '下载', 'downloads', '文档', 'documents', '图片', 'pictures',
            '桌面', 'desktop', '回收站', 'recycle bin'
        ]
        is_not_explorer = not any(keyword in title_lower for keyword in explorer_keywords)
        
        # 只有当标题包含图片扩展名且明确不是资源管理器时才认为是图片查看器
        return has_image_ext and is_not_explorer and len(window_title.strip()) > 0
    
    def extract_image_paths_from_title(self, title):
        """从窗口标题中提取可能的图片文件路径"""
        potential_paths = []
        
        # 常见的图片查看器窗口标题格式
        patterns = [
            r'(.+\.(?:jpg|jpeg|png|bmp|gif|tiff|webp))\s*-',  # 文件名 - 应用名
            r'-\s*(.+\.(?:jpg|jpeg|png|bmp|gif|tiff|webp))',   # 应用名 - 文件名
            r'(.+\.(?:jpg|jpeg|png|bmp|gif|tiff|webp))$',     # 只有文件名
            r'([A-Za-z]:\\[^<>:"|?*]+\.(?:jpg|jpeg|png|bmp|gif|tiff|webp))',  # 完整路径
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, title, re.IGNORECASE)
            for match in matches:
                # 如果匹配到的是完整路径
                if os.path.isabs(match):
                    potential_paths.append(match)
                else:
                    # 如果只是文件名，尝试在当前数据集目录的images子目录中查找
                    if hasattr(self, 'source_dir') and self.source_dir.get():
                        # 先尝试在images子目录中查找
                        images_path = os.path.join(self.source_dir.get(), 'images', match)
                        if os.path.exists(images_path):
                            potential_paths.append(images_path)
                        else:
                            # 兼容旧版本，也尝试在根目录中查找
                            full_path = os.path.join(self.source_dir.get(), match)
                            if os.path.exists(full_path):
                                potential_paths.append(full_path)
        
        return potential_paths
    
    def handle_uwp_photo_app(self, hwnd, window_title):
        """处理UWP照片应用的特殊逻辑"""
        try:
            # 获取照片应用的进程ID
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            
            # 检查进程名是否是照片应用
            try:
                process = psutil.Process(pid)
                process_name = process.name().lower()
                
                # Windows照片应用的可能进程名
                photo_app_names = ['microsoft.photos.exe', 'photos.exe', 'photoviewer.dll']
                
                if any(name in process_name for name in photo_app_names):
                    print(f"检测到照片应用进程: {process_name}")
                    
                    # 尝试从进程的打开文件中获取当前显示的图片
                    self.detect_opened_image_from_process(process)
                    
                    # 同时尝试从窗口标题获取信息
                    if window_title:
                        potential_files = self.extract_image_paths_from_title(window_title)
                        for file_path in potential_files:
                            if self.validate_and_set_current_image(file_path):
                                break
                                
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                print(f"无法访问进程信息: {e}")
                
        except Exception as e:
            print(f"处理UWP照片应用时出错: {e}")
    
    def detect_opened_image_from_process(self, process, is_manual_detection=False):
        """从进程的打开文件中检测当前显示的图片"""
        try:
            image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}
            
            # 获取进程打开的所有文件
            open_files = process.open_files()
            
            for file_info in open_files:
                file_path = file_info.path
                if (Path(file_path).suffix.lower() in image_extensions and
                    os.path.exists(file_path)):
                    
                    if is_manual_detection:
                        print(f"[手动检测] 进程打开的图片文件: {file_path}")
                    else:
                        print(f"进程打开的图片文件: {file_path}")
                    
                    # 检查是否在我们的图片列表中
                    if self.validate_and_set_current_image(file_path, is_manual_detection):
                        return True
                        
        except (psutil.AccessDenied, psutil.NoSuchProcess) as e:
            print(f"无法获取进程打开的文件: {e}")
        except Exception as e:
            print(f"检测进程打开文件时出错: {e}")
            
        return False
    
    def validate_and_set_current_image(self, file_path, is_manual_detection=False):
        """验证并设置当前图片"""
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}
        
        # 标准化路径以支持SMB挂载路径
        normalized_file_path = os.path.normpath(file_path)
        
        # 检查文件是否在图片列表中（使用标准化路径比较）
        file_in_list = False
        if hasattr(self, 'image_files'):
            # 标准化所有图片文件路径进行比较
            normalized_image_files = [os.path.normpath(img_path) for img_path in self.image_files]
            file_in_list = normalized_file_path in normalized_image_files
            
            # 如果标准化路径比较失败，尝试文件名比较（适用于SMB路径格式差异）
            if not file_in_list:
                current_filename = os.path.basename(file_path)
                for img_path in self.image_files:
                    if os.path.basename(img_path) == current_filename:
                        file_in_list = True
                        break
        
        if (os.path.exists(file_path) and 
            Path(file_path).suffix.lower() in image_extensions and
            file_in_list):
            
            if is_manual_detection:
                print(f"[手动检测] 成功检测到当前打开的图片: {file_path}")
            else:
                print(f"成功跟踪到图片: {file_path}")
            if self.current_opened_image != file_path:
                self.current_opened_image = file_path
                filename = os.path.basename(file_path)
                self.root.after(0, lambda f=filename: self.current_image_label.config(text=f))
            return True
        else:
            if is_manual_detection:
                print(f"[手动检测] 文件不符合条件: {file_path} (存在:{os.path.exists(file_path)}, 是图片:{Path(file_path).suffix.lower() in image_extensions}, 在列表中:{file_in_list})")
            else:
                print(f"文件不符合条件: {file_path} (存在:{os.path.exists(file_path)}, 是图片:{Path(file_path).suffix.lower() in image_extensions}, 在列表中:{file_in_list})")
            return False
    
    def on_image_opened(self, file_path):
        """当图片文件被打开时的回调"""
        if file_path in self.image_files:
            self.current_opened_image = file_path
            filename = os.path.basename(file_path)
            self.root.after(0, lambda: self.current_image_label.config(text=filename))
    
    def set_start_image(self):
        """设置起始图片"""
        if not self.current_opened_image:
            messagebox.showwarning("警告", "请先打开一个图片文件")
            return
        
        self.start_image = self.current_opened_image
        self.update_range_display()
        messagebox.showinfo("成功", f"已设置起始图片: {os.path.basename(self.start_image)}")
    
    def set_end_image(self):
        """设置结束图片"""
        if not self.current_opened_image:
            messagebox.showwarning("警告", "请先打开一个图片文件")
            return
        
        self.end_image = self.current_opened_image
        self.update_range_display()
        messagebox.showinfo("成功", f"已设置结束图片: {os.path.basename(self.end_image)}")
    
    def update_range_display(self):
        """更新范围显示"""
        if self.start_image and self.end_image:
            start_name = os.path.basename(self.start_image)
            end_name = os.path.basename(self.end_image)
            self.range_label.config(text=f"选择范围: {start_name} 到 {end_name}")
        elif self.start_image:
            start_name = os.path.basename(self.start_image)
            self.range_label.config(text=f"起始图片: {start_name}")
        elif self.end_image:
            end_name = os.path.basename(self.end_image)
            self.range_label.config(text=f"结束图片: {end_name}")
        else:
            self.range_label.config(text="选择范围: 未设置")
    
    def get_selected_images(self):
        """获取选中的图片范围"""
        if not self.start_image or not self.end_image:
            messagebox.showwarning("警告", "请先设置起始和结束图片")
            return []
        
        try:
            start_index = self.image_files.index(self.start_image)
            end_index = self.image_files.index(self.end_image)
            
            # 确保起始索引小于结束索引
            if start_index > end_index:
                start_index, end_index = end_index, start_index
            
            return self.image_files[start_index:end_index + 1]
        except ValueError:
            messagebox.showerror("错误", "选择的图片不在当前目录中")
            return []
    
    def copy_images(self):
        """复制选中的图片"""
        self.process_images(copy=True)
    
    def move_images(self):
        """移动选中的图片"""
        self.process_images(copy=False)
    
    def process_images(self, copy=True):
        """处理数据集（复制或移动images和labels目录）"""
        # 获取选中的目标目录
        selected_targets = []
        for key, var in self.target_checkbox_vars.items():
            if var.get():
                # 解析场景和子目录名称
                if "::" in key:
                    scenario_name, subdir_name = key.split("::", 1)
                    if scenario_name in self.scenarios and subdir_name in self.scenarios[scenario_name]:
                        target_path = self.scenarios[scenario_name][subdir_name]
                        display_name = f"{scenario_name}/{subdir_name}"
                        if os.path.exists(target_path):
                            selected_targets.append((display_name, target_path))
                        else:
                            messagebox.showerror("错误", f"目标目录不存在: {display_name} ({target_path})")
                            return
                # 兼容旧格式
                elif key in self.target_directories:
                    target_path = self.target_directories[key]
                    if os.path.exists(target_path):
                        selected_targets.append((key, target_path))
                    else:
                        messagebox.showerror("错误", f"目标目录不存在: {key} ({target_path})")
                        return
        
        if not selected_targets:
            messagebox.showerror("错误", "请先选择至少一个目标目录")
            return
        
        selected_images = self.get_selected_images()
        if not selected_images:
            return
        
        # 获取数据集目录路径
        dataset_path = Path(self.source_dir.get())
        images_path = dataset_path / "images"
        labels_path = dataset_path / "labels"
        
        operation = "复制" if copy else "移动"
        target_names = [name for name, _ in selected_targets]
        result = messagebox.askyesno("确认", 
            f"确定要{operation} {len(selected_images)} 个数据集文件（images+labels）到以下目录吗？\n" +
            "\n".join([f"- {name}" for name in target_names]))
        if not result:
            return
        
        # 启动异步任务
        self.start_async_process(selected_images, selected_targets, images_path, labels_path, copy)
    
    def start_async_process(self, selected_images, selected_targets, images_path, labels_path, copy):
        """启动异步处理任务"""
        operation = "复制" if copy else "移动"
        
        # 创建进度对话框
        self.progress_dialog = ProgressDialog(self.root, f"{operation}进度")
        self.progress_dialog.add_task_log(f"开始{operation}任务: {len(selected_images)} 个文件到 {len(selected_targets)} 个目录")
        
        # 重置取消标志
        self.task_cancelled = False
        
        # 提交异步任务
        self.current_task = self.executor.submit(
            self.process_images_worker, 
            selected_images, selected_targets, images_path, labels_path, copy
        )
        
        # 启动进度监控
        self.monitor_task_progress()
    
    def process_images_worker(self, selected_images, selected_targets, images_path, labels_path, copy):
        """异步处理图片的工作线程"""
        # 根据操作模式选择不同的处理方法
        if self.operation_mode.get() == "server":
            return self.process_images_worker_ssh(selected_images, selected_targets, images_path, labels_path, copy)
        else:
            return self.process_images_worker_local(selected_images, selected_targets, images_path, labels_path, copy)
    
    def process_images_worker_local(self, selected_images, selected_targets, images_path, labels_path, copy):
        """Windows本地模式的图片处理工作线程"""
        operation = "复制" if copy else "移动"
        total_operations = 0
        failed_operations = []
        
        try:
            # 更新进度
            self.root.after(0, lambda: self.progress_dialog.update_overall_progress(0, len(selected_images) * len(selected_targets), "创建目录结构..."))
            
            # 为每个目标目录创建images和labels子目录
            for i, (target_name, target_path) in enumerate(selected_targets):
                if self.task_cancelled or (self.progress_dialog and self.progress_dialog.is_cancelled()):
                    return {"cancelled": True}
                    
                target_images_path = Path(target_path) / "images"
                target_labels_path = Path(target_path) / "labels"
                
                try:
                    target_images_path.mkdir(exist_ok=True)
                    target_labels_path.mkdir(exist_ok=True)
                    self.root.after(0, lambda name=target_name: self.progress_dialog.add_task_log(f"创建目录结构: {name}"))
                except Exception as e:
                    failed_operations.append(f"创建目录结构 -> {target_name}: {str(e)}")
                    self.root.after(0, lambda name=target_name, err=str(e): self.progress_dialog.add_task_log(f"创建目录失败: {name} - {err}"))
                    continue
            
            # 存储需要删除的原文件（仅用于移动操作）
            files_to_delete = []
            
            # 处理每个图片文件
            total_files = len(selected_images)
            for file_index, image_path in enumerate(selected_images):
                if self.task_cancelled or (self.progress_dialog and self.progress_dialog.is_cancelled()):
                    return {"cancelled": True}
                
                filename = os.path.basename(image_path)
                label_filename = os.path.splitext(filename)[0] + ".txt"
                label_path = images_path.parent / "labels" / label_filename
                
                # 记录需要删除的文件（移动操作时使用）
                if not copy:
                    files_to_delete.append((image_path, label_path if label_path.exists() else None))
                
                # 复制到所有目标目录
                for target_index, (target_name, target_path) in enumerate(selected_targets):
                    if self.task_cancelled or (self.progress_dialog and self.progress_dialog.is_cancelled()):
                        return {"cancelled": True}
                    
                    target_images_dir = Path(target_path) / "images"
                    target_labels_dir = Path(target_path) / "labels"
                    target_image_path = target_images_dir / filename
                    target_label_path = target_labels_dir / label_filename
                    
                    try:
                        # 处理图片文件
                        shutil.copy2(image_path, target_image_path)
                        total_operations += 1
                        
                        # 处理对应的label文件（如果存在）
                        if label_path.exists():
                            shutil.copy2(str(label_path), target_label_path)
                            total_operations += 1
                        
                        # 更新进度
                        current_progress = file_index * len(selected_targets) + target_index + 1
                        total_progress = total_files * len(selected_targets)
                        progress_text = f"{operation}中: {filename} -> {target_name} ({current_progress}/{total_progress})"
                        
                        self.root.after(0, lambda cp=current_progress, tp=total_progress, pt=progress_text: 
                                       self.progress_dialog.update_overall_progress(cp, tp, pt))
                        
                        if target_index == 0:  # 只在第一个目标目录时记录日志，避免重复
                            self.root.after(0, lambda fn=filename: self.progress_dialog.add_task_log(f"处理文件: {fn}"))
                        
                    except Exception as e:
                        failed_operations.append(f"{filename} -> {target_name}: {str(e)}")
                        self.root.after(0, lambda fn=filename, tn=target_name, err=str(e): 
                                       self.progress_dialog.add_task_log(f"失败: {fn} -> {tn} - {err}"))
            
            # 如果是移动操作，删除原文件
            if not copy and not (self.task_cancelled or (self.progress_dialog and self.progress_dialog.is_cancelled())):
                self.root.after(0, lambda: self.progress_dialog.add_task_log("删除原文件..."))
                
                for image_path, label_path in files_to_delete:
                    if self.task_cancelled or (self.progress_dialog and self.progress_dialog.is_cancelled()):
                        return {"cancelled": True}
                    
                    try:
                        # 删除图片文件
                        if os.path.exists(image_path):
                            os.remove(image_path)
                        
                        # 删除对应的label文件（如果存在）
                        if label_path and os.path.exists(label_path):
                            os.remove(label_path)
                            
                    except Exception as e:
                        failed_operations.append(f"删除原文件 {os.path.basename(image_path)}: {str(e)}")
                        self.root.after(0, lambda fn=os.path.basename(image_path), err=str(e): 
                                       self.progress_dialog.add_task_log(f"删除失败: {fn} - {err}"))
            
            return {
                "success": True,
                "total_operations": total_operations,
                "failed_operations": failed_operations,
                "operation": operation,
                "selected_images": selected_images,
                "selected_targets": selected_targets,
                "copy": copy
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "operation": operation
            }
    
    def execute_batch_ssh_operations(self, operations, operation_type="copy", max_workers=4, atomic=True):
        """批量执行SSH操作，支持并行处理和数据一致性保证
        
        Args:
            operations: 操作列表，每个元素为 (source_path, target_path, file_type)
            operation_type: 操作类型 'copy' 或 'move'
            max_workers: 最大并行工作线程数
            atomic: 是否启用原子性操作（事务性保证）
            
        Returns:
            dict: 操作结果
        """
        if not operations:
            return {"success": True, "message": "没有需要处理的操作"}
        
        # 预先检查SSH连接
        try:
            ssh_client = self.get_ssh_client()
            if not ssh_client:
                return {"success": False, "error": "无法建立SSH连接"}
        except Exception as e:
            return {"success": False, "error": f"SSH连接失败: {str(e)}"}
        
        if atomic:
            # 使用事务性操作保证原子性
            return self._execute_atomic_operations(operations, operation_type, max_workers)
        else:
            # 根据操作数量选择处理策略
            if len(operations) <= 10:
                # 少量文件使用批量脚本
                return self._execute_batch_script(operations, operation_type)
            else:
                # 大量文件使用并行处理
                return self._execute_parallel_operations(operations, operation_type, max_workers)
    def _execute_batch_script(self, operations, operation_type="copy"):
        """使用批量脚本执行SSH操作（增强版）"""
        script_path = None
        backup_script_path = None
        
        try:
            # 分批处理大量操作，避免脚本过大
            batch_size = 100
            total_success = 0
            total_failed = 0
            
            for i in range(0, len(operations), batch_size):
                batch_operations = operations[i:i + batch_size]
                
                # 创建临时脚本文件路径
                script_path = f"/tmp/batch_operations_{int(time.time())}_{i}.sh"
                backup_script_path = f"/tmp/backup_operations_{int(time.time())}_{i}.sh"
                
                # 构建批量操作脚本
                script_lines = ["#!/bin/bash", "set -e"]
                backup_lines = ["#!/bin/bash", "set -e"]
                
                # 为移动操作准备备份脚本（用于回滚）
                if operation_type == "move":
                    script_lines.append("# 批量移动操作")
                    for source_path, target_path, file_type in batch_operations:
                        script_lines.append(f"mv '{source_path}' '{target_path}'")
                        # 备份脚本用于回滚
                        backup_lines.append(f"mv '{target_path}' '{source_path}'")
                else:
                    script_lines.append("# 批量复制操作")
                    for source_path, target_path, file_type in batch_operations:
                        script_lines.append(f"cp '{source_path}' '{target_path}'")
                
                script_content = "\n".join(script_lines)
                backup_content = "\n".join(backup_lines)
                
                # 使用SFTP上传脚本文件，避免参数列表过长问题
                try:
                    sftp = ssh_client.open_sftp()
                    
                    # 上传主脚本
                    with sftp.open(script_path, 'w') as f:
                        f.write(script_content)
                    
                    # 如果是移动操作，也上传备份脚本
                    if operation_type == "move":
                        with sftp.open(backup_script_path, 'w') as f:
                            f.write(backup_content)
                    
                    sftp.close()
                    print(f"脚本文件上传成功: {script_path}")
                    
                except Exception as e:
                    return {"success": False, "error": f"SFTP脚本上传失败: {str(e)}"}
                
                # 设置脚本执行权限
                chmod_cmd = f"chmod +x '{script_path}'"
                if operation_type == "move":
                    chmod_cmd += f" && chmod +x '{backup_script_path}'"
                
                stdout, stderr, exit_code = self.execute_ssh_command(chmod_cmd, retry_count=2)
                if exit_code != 0:
                    return {"success": False, "error": f"设置脚本权限失败: {stderr}"}
                
                # 执行批量操作脚本（带重试）
                exec_cmd = f"bash '{script_path}'"
                stdout, stderr, exit_code = self.execute_ssh_command(exec_cmd, retry_count=2)
            
                # 清理脚本文件
                cleanup_cmd = f"rm -f '{script_path}'"
                if operation_type == "move":
                    cleanup_cmd += f" '{backup_script_path}'"
                try:
                    self.execute_ssh_command(cleanup_cmd)
                except:
                    pass  # 清理失败不影响主要操作
                
                if exit_code == 0:
                    total_success += len(batch_operations)
                else:
                    total_failed += len(batch_operations)
                    # 如果是移动操作且失败，尝试回滚
                    if operation_type == "move":
                        try:
                            rollback_cmd = f"bash '{backup_script_path}'"
                            self.execute_ssh_command(rollback_cmd)
                        except:
                            pass  # 回滚失败记录但不中断
                    
                    return {
                        "success": False,
                        "error": f"批量操作失败: {stderr}",
                        "operations_count": len(batch_operations),
                        "batch_index": i
                    }
            
            return {
                "success": True,
                "operations_count": total_success,
                "total_batches": (len(operations) + batch_size - 1) // batch_size
            }
                
        except Exception as e:
            # 确保清理临时文件
            if script_path:
                try:
                    cleanup_cmd = f"rm -f '{script_path}'"
                    if backup_script_path:
                        cleanup_cmd += f" '{backup_script_path}'"
                    self.execute_ssh_command(cleanup_cmd)
                except:
                    pass
            return {"success": False, "error": f"批量操作异常: {str(e)}"}
    
    def _execute_parallel_operations(self, operations, operation_type="copy", max_workers=4):
        """并行执行SSH操作
        
        Args:
            operations: 操作列表
            operation_type: 操作类型
            max_workers: 最大并行工作线程数
            
        Returns:
            dict: 操作结果
        """
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        try:
            # 检查SSH连接
            ssh_client = self.get_ssh_client()
            if not ssh_client:
                return {"success": False, "error": "无法建立SSH连接"}
            
            # 线程安全的结果收集
            results = []
            results_lock = threading.Lock()
            failed_operations = []
            
            def execute_single_operation(operation):
                """执行单个文件操作"""
                source_path, target_path, file_type = operation
                try:
                    # 为每个线程获取独立的SSH客户端
                    thread_ssh = self.get_ssh_client()
                    if not thread_ssh:
                        return {"success": False, "error": "线程SSH连接失败", "operation": operation}
                    
                    # 执行操作
                    if operation_type == "move":
                        cmd = f"mv '{source_path}' '{target_path}'"
                    else:
                        cmd = f"cp '{source_path}' '{target_path}'"
                    
                    stdout, stderr, exit_code = self.execute_ssh_command(cmd)
                    
                    if exit_code == 0:
                        return {"success": True, "operation": operation}
                    else:
                        return {"success": False, "error": stderr, "operation": operation}
                        
                except Exception as e:
                    return {"success": False, "error": str(e), "operation": operation}
            
            # 使用线程池并行执行
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有任务
                future_to_operation = {executor.submit(execute_single_operation, op): op for op in operations}
                
                # 收集结果
                for future in as_completed(future_to_operation):
                    result = future.result()
                    
                    with results_lock:
                        results.append(result)
                        if not result["success"]:
                            failed_operations.append(result["operation"])
            
            # 统计结果
            success_count = sum(1 for r in results if r["success"])
            total_count = len(operations)
            
            if len(failed_operations) == 0:
                return {
                    "success": True,
                    "operations_count": total_count,
                    "success_count": success_count,
                    "method": "parallel"
                }
            else:
                # 如果是移动操作且有失败，需要回滚成功的操作
                if operation_type == "move" and success_count > 0:
                    self._rollback_successful_moves(results)
                
                return {
                    "success": False,
                    "error": f"并行操作部分失败，成功: {success_count}/{total_count}",
                    "operations_count": total_count,
                    "success_count": success_count,
                    "failed_operations": failed_operations,
                    "method": "parallel"
                }
                
        except Exception as e:
            return {"success": False, "error": f"并行操作异常: {str(e)}"}
    
    def _rollback_successful_moves(self, results):
        """回滚成功的移动操作"""
        try:
            for result in results:
                if result["success"] and "operation" in result:
                    source_path, target_path, file_type = result["operation"]
                    # 回滚：将目标文件移回源位置
                    rollback_cmd = f"mv '{target_path}' '{source_path}'"
                    self.execute_ssh_command(rollback_cmd)
        except Exception as e:
             print(f"回滚操作失败: {e}")
    
    def _execute_atomic_operations(self, operations, operation_type="copy", max_workers=4):
        """原子性执行SSH操作，保证事务性和数据一致性
        
        Args:
            operations: 操作列表
            operation_type: 操作类型
            max_workers: 最大并行工作线程数
            
        Returns:
            dict: 操作结果
        """
        import uuid
        import time
        
        try:
            ssh_client = self.get_ssh_client()
            if not ssh_client:
                return {"success": False, "error": "无法建立SSH连接"}
            
            # 生成事务ID
            transaction_id = str(uuid.uuid4())[:8]
            temp_dir = f"/tmp/atomic_transaction_{transaction_id}"
            
            # 第一阶段：预检查和准备
            print(f"开始原子性操作事务: {transaction_id}")
            
            # 创建临时目录用于事务管理
            create_temp_cmd = f"mkdir -p '{temp_dir}'"
            stdout, stderr, exit_code = self.execute_ssh_command(create_temp_cmd)
            if exit_code != 0:
                return {"success": False, "error": f"创建事务临时目录失败: {stderr}"}
            
            # 预检查所有源文件是否存在
            missing_files = []
            for source_path, target_path, file_type in operations:
                check_cmd = f"test -f '{source_path}'"
                stdout, stderr, exit_code = self.execute_ssh_command(check_cmd)
                if exit_code != 0:
                    missing_files.append(source_path)
            
            if missing_files:
                # 清理临时目录
                self.execute_ssh_command(f"rm -rf '{temp_dir}'")
                return {
                    "success": False,
                    "error": f"源文件不存在: {', '.join(missing_files[:5])}{'...' if len(missing_files) > 5 else ''}"
                }
            
            # 第二阶段：执行操作到临时位置
            temp_operations = []
            for i, (source_path, target_path, file_type) in enumerate(operations):
                temp_target = f"{temp_dir}/file_{i}_{file_type}"
                temp_operations.append((source_path, temp_target, target_path, file_type))
            
            # 先复制所有文件到临时位置
            failed_temp_ops = []
            for source_path, temp_target, final_target, file_type in temp_operations:
                copy_cmd = f"cp '{source_path}' '{temp_target}'"
                stdout, stderr, exit_code = self.execute_ssh_command(copy_cmd)
                if exit_code != 0:
                    failed_temp_ops.append((source_path, stderr))
            
            if failed_temp_ops:
                # 清理临时目录
                self.execute_ssh_command(f"rm -rf '{temp_dir}'")
                return {
                    "success": False,
                    "error": f"临时复制失败: {failed_temp_ops[0][1]}",
                    "failed_count": len(failed_temp_ops)
                }
            
            # 第三阶段：原子性提交
            commit_script_path = f"{temp_dir}/commit.sh"
            rollback_script_path = f"{temp_dir}/rollback.sh"
            
            # 构建提交脚本
            commit_lines = ["#!/bin/bash", "set -e"]
            rollback_lines = ["#!/bin/bash", "set -e"]
            
            for source_path, temp_target, final_target, file_type in temp_operations:
                # 提交：将临时文件移动到最终位置
                commit_lines.append(f"mv '{temp_target}' '{final_target}'")
                
                # 回滚脚本：如果是移动操作，需要能够恢复
                if operation_type == "move":
                    rollback_lines.append(f"mv '{final_target}' '{source_path}'")
                else:
                    rollback_lines.append(f"rm -f '{final_target}'")
            
            # 如果是移动操作，在提交脚本中删除源文件
            if operation_type == "move":
                for source_path, temp_target, final_target, file_type in temp_operations:
                    commit_lines.append(f"rm -f '{source_path}'")
            
            # 使用SFTP上传脚本，避免参数列表过长问题
            commit_content = "\n".join(commit_lines)
            rollback_content = "\n".join(rollback_lines)
            
            try:
                sftp = ssh_client.open_sftp()
                
                # 上传提交脚本
                with sftp.open(commit_script_path, 'w') as f:
                    f.write(commit_content)
                
                # 上传回滚脚本
                with sftp.open(rollback_script_path, 'w') as f:
                    f.write(rollback_content)
                
                sftp.close()
                print(f"原子性操作脚本上传成功: {commit_script_path}")
                
            except Exception as e:
                self.execute_ssh_command(f"rm -rf '{temp_dir}'")
                return {"success": False, "error": f"SFTP脚本上传失败: {str(e)}"}
            
            # 设置脚本权限
            chmod_cmd = f"chmod +x '{commit_script_path}' '{rollback_script_path}'"
            self.execute_ssh_command(chmod_cmd)
            
            # 执行提交
            commit_cmd = f"bash '{commit_script_path}'"
            stdout, stderr, exit_code = self.execute_ssh_command(commit_cmd)
            
            if exit_code == 0:
                # 成功：清理临时目录
                self.execute_ssh_command(f"rm -rf '{temp_dir}'")
                return {
                    "success": True,
                    "operations_count": len(operations),
                    "transaction_id": transaction_id,
                    "method": "atomic"
                }
            else:
                # 失败：执行回滚
                print(f"提交失败，执行回滚: {stderr}")
                rollback_cmd = f"bash '{rollback_script_path}'"
                self.execute_ssh_command(rollback_cmd)
                
                # 清理临时目录
                self.execute_ssh_command(f"rm -rf '{temp_dir}'")
                
                return {
                    "success": False,
                    "error": f"原子性操作失败并已回滚: {stderr}",
                    "transaction_id": transaction_id,
                    "operations_count": len(operations)
                }
                
        except Exception as e:
            # 异常情况：尝试清理
            try:
                if 'temp_dir' in locals():
                    self.execute_ssh_command(f"rm -rf '{temp_dir}'")
            except:
                pass
            return {"success": False, "error": f"原子性操作异常: {str(e)}"}
    
    def execute_rsync_operation(self, source_files, target_dir, operation_type="copy"):
        """使用rsync进行批量文件操作
        
        Args:
            source_files: 源文件列表
            target_dir: 目标目录
            operation_type: 操作类型 'copy' 或 'move'
            
        Returns:
            dict: 操作结果
        """
        try:
            ssh_client = self.get_ssh_client()
            if not ssh_client:
                return {"success": False, "error": "无法建立SSH连接"}
            
            # 检查rsync是否可用，使用多种方式检查
            # 首先尝试 command -v（POSIX标准）
            check_cmd = "command -v rsync"
            stdout, stderr, exit_code = self.execute_ssh_command(check_cmd)
            
            if exit_code != 0:
                # 如果 command -v 失败，尝试 which
                check_cmd = "which rsync"
                stdout, stderr, exit_code = self.execute_ssh_command(check_cmd)
                
                if exit_code != 0:
                    # 如果 which 也失败，尝试直接执行 rsync --version
                    check_cmd = "rsync --version"
                    stdout, stderr, exit_code = self.execute_ssh_command(check_cmd)
                    
                    if exit_code != 0:
                        return {"success": False, "error": f"服务器上未安装rsync或rsync不可用: {stderr.strip()}"}
            
            self.add_operation_log(f"rsync检查成功: {stdout.strip()}")
            
            # 使用SFTP创建临时文件列表，避免参数列表过长问题
            file_list_path = f"/tmp/rsync_files_{int(time.time())}.txt"
            file_list_content = "\n".join(source_files)
            
            try:
                sftp = ssh_client.open_sftp()
                with sftp.open(file_list_path, 'w') as f:
                    f.write(file_list_content)
                sftp.close()
                self.add_operation_log(f"rsync文件列表上传成功: {file_list_path}")
            except Exception as e:
                return {"success": False, "error": f"SFTP文件列表上传失败: {str(e)}"}
            
            # 构建rsync命令
            rsync_options = "-av --files-from='{}'".format(file_list_path)
            if operation_type == "move":
                rsync_options += " --remove-source-files"
            
            # 执行rsync操作
            rsync_cmd = f"rsync {rsync_options} / '{target_dir}'"
            stdout, stderr, exit_code = self.execute_ssh_command(rsync_cmd)
            
            # 清理临时文件
            cleanup_cmd = f"rm -f '{file_list_path}'"
            self.execute_ssh_command(cleanup_cmd)
            
            if exit_code == 0:
                return {
                    "success": True,
                    "files_count": len(source_files),
                    "stdout": stdout
                }
            else:
                return {
                    "success": False,
                    "error": f"rsync操作失败: {stderr}",
                    "files_count": len(source_files)
                }
                
        except Exception as e:
            return {"success": False, "error": f"rsync操作异常: {str(e)}"}
    
    def execute_rsync_batch_operations(self, operations, operation_type="copy"):
        """使用rsync执行批量文件操作（高性能优化版）
        
        Args:
            operations: 操作列表 [(src, dst, ftype), ...]
            operation_type: 操作类型 (copy/move)
            
        Returns:
            dict: 操作结果
        """
        try:
            ssh_client = self.get_ssh_client()
            if not ssh_client:
                return {"success": False, "error": "无法建立SSH连接"}
            
            # 检查rsync是否可用
            check_cmd = "command -v rsync || which rsync || rsync --version"
            stdout, stderr, exit_code = self.execute_ssh_command(check_cmd)
            
            if exit_code != 0:
                return {"success": False, "error": f"服务器上未安装rsync或rsync不可用: {stderr.strip()}"}
            
            self.add_operation_log("rsync检查成功")
            
            # 按目标目录分组操作
            target_groups = {}
            for src, dst, ftype in operations:
                target_dir = os.path.dirname(dst)
                if target_dir not in target_groups:
                    target_groups[target_dir] = []
                target_groups[target_dir].append((src, dst, ftype))
            
            # 并行处理多个目标目录
            import threading
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            total_files = 0
            failed_dirs = []
            
            def process_target_dir(target_dir, group_operations):
                """处理单个目标目录的rsync操作"""
                try:
                    # 确保目标目录存在
                    mkdir_cmd = f"mkdir -p '{target_dir}'"
                    self.execute_ssh_command(mkdir_cmd)
                    
                    # 使用更高效的rsync方式：直接构建源文件列表
                    source_files = [src for src, dst, ftype in group_operations]
                    
                    # 创建临时文件列表（只包含源文件路径）
                    timestamp = int(time.time())
                    dir_hash = hash(target_dir) % 10000
                    file_list = f"/tmp/rsync_files_{timestamp}_{dir_hash}.txt"
                    
                    # 上传文件列表
                    sftp = ssh_client.open_sftp()
                    with sftp.open(file_list, 'w') as f:
                        f.write("\n".join(source_files))
                    sftp.close()
                    
                    # 使用高性能rsync参数：
                    # -a: 归档模式（保持权限、时间戳等）
                    # -v: 详细输出
                    # --files-from: 从文件读取源文件列表
                    # --no-relative: 不保持相对路径结构
                    # --progress: 显示进度（可选）
                    # -W: 整文件传输（对于局域网更快）
                    # --inplace: 就地更新（减少磁盘I/O）
                    rsync_cmd = f"rsync -avW --inplace --files-from='{file_list}' / '{target_dir}/'"
                    
                    stdout, stderr, exit_code = self.execute_ssh_command(rsync_cmd)
                    
                    # 清理临时文件
                    cleanup_cmd = f"rm -f '{file_list}'"
                    self.execute_ssh_command(cleanup_cmd)
                    
                    if exit_code == 0:
                        self.add_operation_log(f"rsync完成目标目录 {target_dir}: {len(group_operations)} 个文件")
                        return {"success": True, "files_count": len(group_operations), "target_dir": target_dir}
                    else:
                        return {"success": False, "error": stderr, "target_dir": target_dir, "files_count": len(group_operations)}
                        
                except Exception as e:
                    return {"success": False, "error": str(e), "target_dir": target_dir, "files_count": len(group_operations)}
            
            # 使用线程池并行处理目标目录（最多4个并发）
            max_workers = min(4, len(target_groups))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有任务
                future_to_dir = {
                    executor.submit(process_target_dir, target_dir, group_operations): target_dir
                    for target_dir, group_operations in target_groups.items()
                }
                
                # 收集结果
                for future in as_completed(future_to_dir):
                    result = future.result()
                    if result["success"]:
                        total_files += result["files_count"]
                    else:
                        failed_dirs.append(f"{result['target_dir']}: {result['error']}")
            
            if failed_dirs:
                return {
                    "success": False,
                    "error": f"部分目录rsync失败: {'; '.join(failed_dirs)}",
                    "files_count": total_files
                }
            
            return {
                "success": True,
                "files_count": total_files,
                "stdout": f"rsync并行批量操作完成，共处理 {total_files} 个文件到 {len(target_groups)} 个目录"
            }
                
        except Exception as e:
            return {"success": False, "error": f"rsync批量操作异常: {str(e)}"}
    
    def process_images_worker_ssh(self, selected_images, selected_targets, images_path, labels_path, copy):
        """SSH服务器模式的图片处理工作线程（优化版本）"""
        operation = "复制" if copy else "移动"
        total_operations = 0
        failed_operations = []
        
        try:
            # 获取SSH客户端
            ssh_client = self.get_ssh_client()
            if not ssh_client:
                return {
                    "success": False,
                    "error": "无法建立SSH连接",
                    "operation": operation
                }
            
            # 更新进度
            self.root.after(0, lambda: self.progress_dialog.update_overall_progress(0, len(selected_images) * len(selected_targets), "准备批量操作..."))
            
            # 转换路径为Linux格式
            linux_images_path = self.convert_windows_to_linux_path(images_path)
            linux_labels_path = self.convert_windows_to_linux_path(labels_path) if labels_path else None
            
            # 批量创建所有需要的目录（去重优化）
            directories_to_create = set()
            target_paths_map = {}
            
            for target_name, target_path in selected_targets:
                linux_target_path = self.convert_windows_to_linux_path(target_path)
                target_images_path = f"{linux_target_path}/images"
                target_labels_path = f"{linux_target_path}/labels"
                
                directories_to_create.add(target_images_path)
                directories_to_create.add(target_labels_path)
                target_paths_map[target_name] = (target_images_path, target_labels_path)
            
            # 创建目录
            self.root.after(0, lambda: self.progress_dialog.update_overall_progress(0, len(selected_images) * len(selected_targets), "创建远程目录结构..."))
            for directory in directories_to_create:
                if not self.create_ssh_directory(directory):
                    failed_operations.append(f"创建目录失败: {directory}")
            
            # 准备批量操作列表
            batch_operations = []
            
            # 为每个目标目录准备操作
            for target_index, (target_name, target_path) in enumerate(selected_targets):
                target_images_path, target_labels_path = target_paths_map[target_name]
                
                # 准备图片文件操作
                for img_index, image_path in enumerate(selected_images):
                    if self.task_cancelled or (self.progress_dialog and self.progress_dialog.is_cancelled()):
                        self.close_ssh_connection()
                        return {"cancelled": True}
                    
                    # 获取文件名（不包含路径）
                    image_name = os.path.basename(image_path)
                    
                    # 构建源文件的完整Linux路径（从数据集的images目录）
                    source_image_file = f"{linux_images_path}/{image_name}"
                    target_image_file = f"{target_images_path}/{image_name}"
                    
                    # 添加图片操作到批量列表
                    if copy or target_index < len(selected_targets) - 1:
                        # 复制操作或不是最后一个目标
                        batch_operations.append((source_image_file, target_image_file, "image"))
                    else:
                        # 移动操作且是最后一个目标
                        batch_operations.append((source_image_file, target_image_file, "image_move"))
                    
                    # 查找对应的label文件
                    if linux_labels_path:
                        base_name = os.path.splitext(image_name)[0]
                        for ext in ['.txt', '.xml', '.json']:
                            label_name = base_name + ext
                            # 构建源标签文件的完整Linux路径（从数据集的labels目录）
                            source_label_file = f"{linux_labels_path}/{label_name}"
                            
                            # 检查Linux服务器上是否存在该标签文件
                            check_cmd = f"test -f '{source_label_file}'"
                            _, _, exit_code = self.execute_ssh_command(check_cmd)
                            
                            if exit_code == 0:  # 文件存在
                                target_label_file = f"{target_labels_path}/{label_name}"
                                
                                # 添加标签操作到批量列表
                                if copy or target_index < len(selected_targets) - 1:
                                    batch_operations.append((source_label_file, target_label_file, "label"))
                                else:
                                    batch_operations.append((source_label_file, target_label_file, "label_move"))
                                break
            
            # 分离复制和移动操作
            copy_operations = [(src, dst, ftype) for src, dst, ftype in batch_operations if not ftype.endswith('_move')]
            move_operations = [(src, dst, ftype.replace('_move', '')) for src, dst, ftype in batch_operations if ftype.endswith('_move')]
            
            # 执行批量复制操作
            if copy_operations:
                self.root.after(0, lambda: self.progress_dialog.update_overall_progress(0, len(selected_images) * len(selected_targets), f"批量复制 {len(copy_operations)} 个文件..."))
                
                # 尝试使用rsync，如果失败则使用批量脚本
                # rsync需要按目标目录分组处理
                rsync_result = self.execute_rsync_batch_operations(copy_operations, "copy")
                
                if not rsync_result["success"]:
                    # rsync失败，使用批量脚本
                    self.root.after(0, lambda: self.progress_dialog.add_task_log(f"rsync不可用，使用批量脚本: {rsync_result['error']}"))
                    batch_result = self.execute_batch_ssh_operations(copy_operations, "copy")
                    
                    if not batch_result["success"]:
                        failed_operations.append(f"批量复制失败: {batch_result['error']}")
                    else:
                        total_operations += batch_result["operations_count"]
                        self.root.after(0, lambda: self.progress_dialog.add_task_log(f"批量复制完成: {batch_result['operations_count']} 个文件"))
                else:
                    total_operations += rsync_result["files_count"]
                    self.root.after(0, lambda: self.progress_dialog.add_task_log(f"rsync复制完成: {rsync_result['files_count']} 个文件"))
            
            # 执行批量移动操作
            if move_operations:
                self.root.after(0, lambda: self.progress_dialog.update_overall_progress(0, len(selected_images) * len(selected_targets), f"批量移动 {len(move_operations)} 个文件..."))
                
                # 移动操作使用批量脚本（支持回滚）
                batch_result = self.execute_batch_ssh_operations(move_operations, "move")
                
                if not batch_result["success"]:
                    failed_operations.append(f"批量移动失败: {batch_result['error']}")
                else:
                    total_operations += batch_result["operations_count"]
                    self.root.after(0, lambda: self.progress_dialog.add_task_log(f"批量移动完成: {batch_result['operations_count']} 个文件"))
            
            # 关闭SSH连接
            self.close_ssh_connection()
            
            return {
                "success": True,
                "total_operations": total_operations,
                "failed_operations": failed_operations,
                "operation": operation,
                "selected_images": selected_images,
                "selected_targets": selected_targets,
                "copy": copy,
                "batch_optimized": True
            }
            

            
        except Exception as e:
            self.close_ssh_connection()
            return {
                "success": False,
                "error": str(e),
                "operation": operation
            }
    
    def monitor_task_progress(self):
        """监控任务进度"""
        if self.current_task and not self.current_task.done():
            # 任务还在进行中，继续监控
            self.root.after(100, self.monitor_task_progress)
        elif self.current_task:
            # 任务完成，处理结果
            try:
                result = self.current_task.result()
                self.handle_task_completion(result)
            except Exception as e:
                self.handle_task_error(str(e))
    
    def handle_task_completion(self, result):
        """处理任务完成"""
        if result.get("cancelled"):
            self.progress_dialog.add_task_log("任务已取消")
            self.progress_dialog.task_completed()
            self.add_operation_log("操作已取消")
            return
        
        if not result.get("success"):
            error = result.get("error", "未知错误")
            self.progress_dialog.add_task_log(f"任务失败: {error}")
            self.progress_dialog.task_completed()
            messagebox.showerror("错误", f"{result.get('operation', '操作')}过程中出现错误: {error}")
            self.add_operation_log(f"{result.get('operation', '操作')}失败: {error}")
            return
        
        # 任务成功完成
        operation = result["operation"]
        total_operations = result["total_operations"]
        failed_operations = result["failed_operations"]
        selected_images = result["selected_images"]
        selected_targets = result["selected_targets"]
        copy = result["copy"]
        
        self.progress_dialog.add_task_log(f"任务完成: 总操作 {total_operations} 次")
        self.progress_dialog.task_completed()
        
        # 显示结果
        if failed_operations:
            error_msg = f"部分操作失败:\n" + "\n".join(failed_operations[:5])
            if len(failed_operations) > 5:
                error_msg += f"\n... 还有 {len(failed_operations) - 5} 个失败"
            messagebox.showwarning("部分成功", 
                f"成功{operation}了 {total_operations} 次\n\n{error_msg}")
            self.add_operation_log(f"{operation}操作部分成功: 成功 {total_operations} 次，失败 {len(failed_operations)} 次")
        else:
            messagebox.showinfo("成功", 
                f"成功{operation}了 {len(selected_images)} 个数据集文件到 {len(selected_targets)} 个目录")
            self.add_operation_log(f"{operation}操作完成: 成功{operation}了 {len(selected_images)} 个数据集文件到 {len(selected_targets)} 个目录")
        
        # 清除所有选中的复选框
        for key, var in self.target_checkbox_vars.items():
            if var.get():
                var.set(False)
        
        # 如果是移动操作，重新检测目录
        if not copy:
            self.detect_images()
    
    def handle_task_error(self, error):
        """处理任务错误"""
        if self.progress_dialog:
            self.progress_dialog.add_task_log(f"任务异常: {error}")
            self.progress_dialog.task_completed()
        messagebox.showerror("错误", f"任务执行异常: {error}")
        self.add_operation_log(f"操作异常: {error}")
    
    def start_manual_detection(self):
        """开始手动检测模式"""
        if not WIN32_AVAILABLE:
            messagebox.showerror("错误", "手动检测功能需要pywin32库支持")
            return
            
        self.detect_status_label.config(text="请点击照片应用窗口...")
        self.manual_detect_btn.config(state="disabled")
        
        # 在新线程中执行手动检测
        threading.Thread(target=self.manual_detection_worker, daemon=True).start()
    
    def manual_detection_worker(self):
        """手动检测工作线程"""
        try:
            import time
            import win32api
            
            # 等待用户准备
            time.sleep(1)
            
            # 监控鼠标点击
            start_time = time.time()
            last_click_time = 0
            click_detected = False
            
            while time.time() - start_time < 15:  # 15秒超时
                try:
                    # 检查鼠标左键状态
                    left_button_state = win32api.GetAsyncKeyState(0x01)
                    
                    # 检测鼠标左键按下（新的点击）
                    if left_button_state & 0x8000 and not click_detected:  # 按键当前被按下且未检测过
                        click_detected = True
                        current_time = time.time()
                        
                        # 避免重复检测同一次点击（间隔至少0.3秒）
                        if current_time - last_click_time > 0.3:
                            last_click_time = current_time
                            
                            # 等待一小段时间确保点击完成
                            time.sleep(0.05)
                            
                            # 获取点击位置的窗口
                            x, y = win32api.GetCursorPos()
                            print(f"检测到点击位置: ({x}, {y})")
                            hwnd = win32gui.WindowFromPoint((x, y))
                            
                            # 尝试获取更合适的父窗口
                            if hwnd:
                                # 获取顶级窗口
                                top_hwnd = win32gui.GetAncestor(hwnd, 2)  # GA_ROOT
                                if top_hwnd and top_hwnd != hwnd:
                                    try:
                                        top_title = win32gui.GetWindowText(top_hwnd)
                                        if top_title:  # 如果顶级窗口有标题，使用它
                                            hwnd = top_hwnd
                                    except:
                                        pass
                            
                            if hwnd:
                                try:
                                    window_title = win32gui.GetWindowText(hwnd)
                                    class_name = win32gui.GetClassName(hwnd)
                                    
                                    print(f"检测到点击窗口: {class_name} - '{window_title}'")
                                    self.root.after(0, lambda: self.detect_status_label.config(text="正在分析窗口..."))
                                    
                                    # 分析窗口
                                    if self.analyze_clicked_window(hwnd, window_title, class_name):
                                        self.root.after(0, lambda: self.detect_status_label.config(text="检测成功!"))
                                        self.root.after(0, lambda: self.manual_detect_btn.config(state="normal"))
                                        return
                                    else:
                                        self.root.after(0, lambda: self.detect_status_label.config(text="未找到图片，请点击其他窗口"))
                                except Exception as e:
                                    print(f"窗口信息获取失败: {e}")
                                    self.root.after(0, lambda: self.detect_status_label.config(text="窗口信息获取失败"))
                    
                    elif not (left_button_state & 0x8000):
                        # 鼠标左键释放，重置检测状态
                        click_detected = False
                    
                    time.sleep(0.05)  # 减少CPU占用
                    
                except Exception as e:
                    print(f"手动检测过程中出错: {e}")
                    time.sleep(0.1)
                    continue
            
            # 超时
            self.root.after(0, lambda: self.detect_status_label.config(text="检测超时，请重试"))
            self.root.after(0, lambda: self.manual_detect_btn.config(state="normal"))
            
        except Exception as e:
            print(f"手动检测失败: {e}")
            self.root.after(0, lambda: self.detect_status_label.config(text=f"检测失败: {str(e)}"))
            self.root.after(0, lambda: self.manual_detect_btn.config(state="normal"))
    
    def analyze_clicked_window(self, hwnd, window_title, class_name):
        """分析点击的窗口"""
        try:
            print(f"分析窗口: {class_name} - {window_title}")
            
            # 获取进程信息
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process = psutil.Process(pid)
                process_name = process.name().lower()
                print(f"进程名: {process_name}")
            except Exception as e:
                print(f"无法获取进程信息: {e}")
                process = None
                process_name = ""
            
            # 1. 首先检查是否是已知的图片查看器
            if self.is_likely_image_viewer(window_title, class_name):
                print("识别为图片查看器")
                # 从窗口标题提取图片路径
                potential_files = self.extract_image_paths_from_title(window_title)
                for file_path in potential_files:
                    if self.validate_and_set_current_image(file_path, is_manual_detection=True):
                        return True
            
            # 2. 检查进程名是否是图片相关应用
            photo_processes = ['microsoft.photos.exe', 'photos.exe', 'photoviewer.dll', 
                             'mspaint.exe', 'photoshop.exe', 'gimp.exe', 'irfanview.exe',
                             'faststone.exe', 'xnview.exe', 'acdsee.exe']
            
            if any(name in process_name for name in photo_processes):
                print(f"识别为图片应用进程: {process_name}")
                if process and self.detect_opened_image_from_process(process, is_manual_detection=True):
                    return True
            
            # 3. 特殊处理UWP应用（Windows照片应用）
            if class_name == 'ApplicationFrameWindow':
                print("检测到UWP应用框架")
                self.handle_uwp_photo_app(hwnd, window_title)
                # UWP应用可能需要更多时间来检测，先返回True
                return True
            
            # 4. 通用检测：检查窗口标题是否包含图片文件扩展名
            if window_title and any(ext in window_title.lower() for ext in ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp']):
                print("窗口标题包含图片扩展名")
                potential_files = self.extract_image_paths_from_title(window_title)
                for file_path in potential_files:
                    if self.validate_and_set_current_image(file_path, is_manual_detection=True):
                        return True
            
            # 5. 最后尝试进程文件检测（适用于所有进程）
            if process:
                print("尝试进程文件检测")
                if self.detect_opened_image_from_process(process, is_manual_detection=True):
                    return True
            
            print("未能从该窗口检测到图片")
            return False
            
        except Exception as e:
            print(f"窗口分析失败: {e}")
            return False
    
    def on_closing(self):
        """程序关闭时的清理工作"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
        
        # 停止窗口监控
        self.stop_window_monitoring()
        
        # 取消当前任务并关闭线程池
        self.task_cancelled = True
        if self.progress_dialog:
            self.progress_dialog.close_dialog()
        self.executor.shutdown(wait=False)
        
        self.root.destroy()

def main():
    """主函数"""
    root = tk.Tk()
    app = ImageManager(root)
    root.mainloop()

if __name__ == "__main__":
    main()