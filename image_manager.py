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
        
        # 加载配置
        self.load_config()
        
        # 创建菜单栏
        self.create_menu()
        
        # 创建界面
        self.create_widgets()
        
        # 绑定关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def create_menu(self):
        """创建菜单栏"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # 配置菜单
        config_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="配置", menu=config_menu)
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
                'scenarios': self.scenarios
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("错误", f"保存配置文件失败: {e}")
    
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
            dataset_path = Path(self.source_dir.get())
            images_path = dataset_path / "images"
            labels_path = dataset_path / "labels"
            
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
            
            # 添加检测完成日志
            self.add_operation_log(f"检测完成: 找到 {len(self.image_files)} 个图片文件 {('(有序)' if is_ordered else '(无序)')}")
            
            self.root.after(0, lambda: self.status_label.config(text=status_text))
            
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("错误", f"检测过程中出现错误: {str(e)}"))
    
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