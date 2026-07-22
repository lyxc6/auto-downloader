# 自动下载器 v2.0 - 迁移任务清单

## 项目概述

将现有tkinter应用迁移为PySide6 + PySide6-Fluent-Widgets，实现Win11风格界面。

## 技术栈

- **GUI框架**: PySide6
- **UI组件库**: PySide6-Fluent-Widgets
- **架构模式**: MVC
- **Python版本**: 3.10+

## 任务清单

| 任务 | 文件 | 负责模块 | 依赖 | 状态 |
|------|------|----------|------|------|
| 任务1 | task1_models.md | 数据模型层 | 无 | ⬜ 待开始 |
| 任务2 | task2_services.md | 服务层 | 任务1 | ⬜ 待开始 |
| 任务3 | task3_controllers.md | 控制器层 | 任务1,2 | ⬜ 待开始 |
| 任务4 | task4_views.md | 视图层 | 任务1,3 | ⬜ 待开始 |
| 任务5 | task5_integration.md | 集成入口 | 全部 | ⬜ 待开始 |

## 依赖关系

```
任务1 (Models)
    ↓
任务2 (Services) ← 依赖 Models
    ↓
任务3 (Controllers) ← 依赖 Models, Services
    ↓
任务4 (Views) ← 依赖 Models, Controllers
    ↓
任务5 (Integration) ← 依赖全部
```

## 并行开发建议

### 第一批次（可并行）
- **任务1**: 数据模型层 - 无依赖，可立即开始

### 第二批次（可并行）
- **任务2**: 服务层 - 依赖任务1
- **任务4的部分**: 视图层的独立组件（log_widget, tree_widget）

### 第三批次（可并行）
- **任务3**: 控制器层 - 依赖任务1,2
- **任务4的主体**: 视图层主体（需要控制器）

### 第四批次
- **任务5**: 集成 - 依赖全部

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 按任务顺序开发

每个任务文档包含：
- 任务描述
- 文件清单
- 完整代码
- 验证标准

### 3. 验证每个模块

```bash
# 验证任务1
python -c "from src.models import *; print('Models OK')"

# 验证任务2
python -c "from src.services import *; print('Services OK')"

# 验证任务3
python -c "from src.controllers import *; print('Controllers OK')"

# 验证任务4
python -c "from src.views import *; print('Views OK')"

# 运行应用
python main.py
```

## 新增功能

### 1. 主题切换
- 浅色主题
- 深色主题
- 跟随系统

### 2. 配置管理
- 图形化设置界面
- 下载目录设置
- 并发数设置
- 超时设置

### 3. 下载队列
- 可视化进度条
- 状态实时更新
- 队列管理

## 预期效果

| 功能 | 旧版(tkinter) | 新版(Fluent) |
|------|---------------|--------------|
| 界面风格 | Windows 95 | Windows 11 |
| 主题切换 | ❌ | ✅ |
| 动画效果 | ❌ | ✅ |
| 响应式布局 | ❌ | ✅ |
| 配置管理 | 代码修改 | 图形界面 |

## 注意事项

1. **线程安全**: 所有耗时操作在后台线程执行
2. **信号槽**: 使用PySide6的信号槽机制通信
3. **错误处理**: 完善的异常处理和用户提示
4. **资源管理**: 正确关闭session和释放资源

## 文件清单

```
tasks/
├── README.md              # 本文件
├── task1_models.md        # 任务1：数据模型层
├── task2_services.md      # 任务2：服务层
├── task3_controllers.md   # 任务3：控制器层
├── task4_views.md         # 任务4：视图层
└── task5_integration.md   # 任务5：集成入口
```
