#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片管理器打包脚本
使用PyInstaller将Python程序打包成exe文件
"""

import os
import sys
import subprocess
from pathlib import Path

def build_exe():
    """构建exe文件"""
    print("开始构建图片管理器exe文件...")
    
    # 确保在正确的目录中
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    
    # 构建PyInstaller命令
    cmd = [
        'pyinstaller',
        '--onefile',  # 打包成单个exe文件
        '--windowed',  # 不显示控制台窗口
        '--name=ImageManager',  # 指定exe文件名
        '--clean',  # 清理缓存
        '--noconfirm',  # 不询问覆盖
        'image_manager.py'
    ]
    
    # 如果存在图标文件，添加图标参数
    if Path('icon.ico').exists():
        # 使用绝对路径确保图标正确应用
        icon_path = Path('icon.ico').absolute()
        cmd.insert(-1, f'--icon={icon_path}')
        print(f"使用图标文件: {icon_path}")
    elif Path('icon.svg').exists():
        print("注意: 找到SVG图标文件，但PyInstaller需要ICO格式")
        print("可以使用在线工具将SVG转换为ICO格式")
    else:
        print("未找到图标文件，将使用默认图标")
    
    try:
        # 执行打包命令
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("打包成功！")
        print(f"exe文件位置: {script_dir / 'dist' / 'ImageManager.exe'}")
        
        # 构建完成后删除spec文件
        spec_file = Path('ImageManager.spec')
        if spec_file.exists():
            spec_file.unlink()
            print("已删除临时文件: ImageManager.spec")
        
    except subprocess.CalledProcessError as e:
        print(f"打包失败: {e}")
        print(f"错误输出: {e.stderr}")
        return False
    except FileNotFoundError:
        print("错误: 未找到pyinstaller，请先安装: pip install pyinstaller")
        return False

    return True

def install_dependencies():
    """安装依赖包"""
    print("安装依赖包...")
    try:
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'], check=True)
        print("依赖包安装完成")
        return True
    except subprocess.CalledProcessError as e:
        print(f"依赖包安装失败: {e}")
        return False

def main():
    """主函数"""
    print("=" * 50)
    print("图片管理器构建工具")
    print("=" * 50)
    
    # 检查是否存在requirements.txt
    if not Path('requirements.txt').exists():
        print("错误: 未找到requirements.txt文件")
        return
    
    # 检查是否存在主程序文件
    if not Path('image_manager.py').exists():
        print("错误: 未找到image_manager.py文件")
        return
    
    # 检查依赖包
    print("检查依赖包...")
    try:
        import tkinter
        import PIL
        import psutil
        import watchdog
        print("依赖包检查完成")
    except ImportError as e:
        print(f"缺少依赖包: {e}")
        print("正在安装依赖包...")
        if not install_dependencies():
            return
    
    # 直接开始构建exe
    print("开始构建exe文件...")
    if build_exe():
        print("\n构建完成！可以在dist目录中找到ImageManager.exe文件")
    else:
        print("\n构建失败，请检查错误信息")

if __name__ == "__main__":
    main()