# 贡献指南

感谢您对Image Dataset Manager项目的关注！我们欢迎各种形式的贡献。

## 如何贡献

### 报告问题

如果您发现了bug或有功能建议，请：

1. 检查[Issues页面](../../issues)确认问题未被报告
2. 创建新的Issue，详细描述：
   - 问题的具体表现
   - 重现步骤
   - 您的系统环境（Windows版本、Python版本等）
   - 相关的错误信息或截图

### 提交代码

1. **Fork项目**到您的GitHub账户

2. **克隆您的Fork**：
```bash
git clone https://github.com/YOUR_USERNAME/image-dataset-manager.git
cd image-dataset-manager
```

3. **创建功能分支**：
```bash
git checkout -b feature/your-feature-name
```

4. **设置开发环境**：
```bash
pip install -r requirements.txt
```

5. **进行开发**：
   - 遵循现有的代码风格
   - 添加必要的注释
   - 确保代码能正常运行

6. **测试您的更改**：
```bash
python image_manager.py
```

7. **提交更改**：
```bash
git add .
git commit -m "feat: 添加新功能描述"
```

8. **推送到您的Fork**：
```bash
git push origin feature/your-feature-name
```

9. **创建Pull Request**：
   - 访问原项目页面
   - 点击"New Pull Request"
   - 详细描述您的更改

## 代码规范

### Python代码风格

- 使用4个空格缩进
- 遵循PEP 8规范
- 函数和变量使用snake_case命名
- 类使用PascalCase命名
- 添加适当的docstring和注释

### 提交信息规范

使用以下格式：

```
type(scope): description

[optional body]

[optional footer]
```

**Type类型：**
- `feat`: 新功能
- `fix`: 修复bug
- `docs`: 文档更新
- `style`: 代码格式调整
- `refactor`: 代码重构
- `test`: 测试相关
- `chore`: 构建过程或辅助工具的变动

**示例：**
```
feat(detection): 添加新的图片查看器支持

- 支持PhotoViewer Pro
- 改进窗口标题解析逻辑
- 添加相关测试用例

Closes #123
```

## 开发环境

### 系统要求

- Windows 10/11
- Python 3.8+
- Git

### 推荐工具

- **IDE**: PyCharm, VS Code
- **调试**: Python内置调试器
- **版本控制**: Git

### 项目结构

```
image-dataset-manager/
├── .github/workflows/     # GitHub Actions配置
├── image_manager.py       # 主程序文件
├── build.py              # 构建脚本
├── requirements.txt      # Python依赖
├── README.md            # 项目说明
├── CONTRIBUTING.md      # 贡献指南
├── LICENSE              # 许可证
└── .gitignore          # Git忽略文件
```

## 发布流程

项目维护者会定期发布新版本：

1. 更新版本号
2. 创建Git标签
3. GitHub Actions自动构建和发布
4. 更新Release说明

## 获取帮助

如果您在贡献过程中遇到问题：

1. 查看现有的[Issues](../../issues)
2. 创建新的Issue寻求帮助
3. 在Pull Request中@项目维护者

## 行为准则

请遵循以下原则：

- 尊重所有贡献者
- 保持友好和专业的交流
- 接受建设性的反馈
- 专注于对项目最有利的解决方案

感谢您的贡献！🎉