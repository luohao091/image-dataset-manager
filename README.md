# 图片管理器 (Image Manager)

一个用于管理数据集图片的桌面应用程序，支持自动检测当前查看的图片并提供批量复制/移动功能。

## 功能特性

- **自动检测**: 自动监控当前打开的图片查看器，实时跟踪正在查看的图片
- **手动检测**: 提供手动检测按钮，通过点击窗口来识别当前图片
- **数据集支持**: 支持YOLO格式数据集，自动处理images和labels目录
- **批量操作**: 支持批量复制或移动图片及对应的标注文件
- **范围选择**: 可设置起始和结束图片，批量处理指定范围的文件
- **多目标管理**: 支持配置多个目标目录，方便分类整理

## 系统要求

- Windows 10/11
- Python 3.7+ (如果从源码运行)

## 安装使用

### 方式一：直接运行可执行文件
1. 下载 `ImageManager.exe`
2. 双击运行即可

### 方式二：从源码运行
1. 克隆项目
```bash
git clone https://github.com/luohao091/image-dataset-manager.git
cd image-manager
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 运行程序
```bash
python image_manager.py
```

## 使用说明

1. **选择数据集目录**: 点击"浏览"按钮选择包含images子目录的数据集根目录
2. **开始检测**: 点击"开始检测"按钮启动自动监控
3. **设置范围**: 在图片查看器中浏览到起始图片，点击"设为起始"；浏览到结束图片，点击"设为结束"
4. **选择目标**: 勾选要复制/移动到的目标目录
5. **执行操作**: 点击"复制图片"或"移动图片"按钮

### 手动检测功能
如果自动检测无法正常工作，可以使用手动检测：
1. 点击"手动检测"按钮
2. 在15秒内点击图片查看器窗口
3. 程序会分析点击的窗口并尝试检测当前图片

## 支持的图片格式

- JPG/JPEG
- PNG
- BMP
- GIF
- TIFF
- WebP

## 支持的图片查看器

- Windows照片应用
- Windows图片查看器
- IrfanView
- FastStone Image Viewer
- XnView
- ACDSee
- GIMP
- Photoshop
- 画图工具
- 以及其他常见图片查看软件

## 构建说明

### 本地构建

1. 安装依赖：
```bash
pip install -r requirements.txt
pip install pyinstaller
```

2. 运行构建脚本：
```bash
python build.py
```

3. 生成的可执行文件位于 `dist/` 目录下

### 自动构建

项目配置了GitHub Actions自动构建流程：

- **持续集成**：每次推送到主分支时自动构建
- **发布构建**：创建新的Git标签时自动创建Release并上传可执行文件

#### 创建发布版本

1. 创建并推送标签：
```bash
git tag v1.0.0
git push origin v1.0.0
```

2. GitHub Actions会自动：
   - 构建Windows可执行文件
   - 创建GitHub Release
   - 上传构建产物

#### 下载预构建版本

访问 [Releases页面](../../releases) 下载最新的预构建可执行文件。

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！