# 缓存和预览功能改进计划

## 用户问题
1. 能否缓存网站的目录结构，只有点击扫描目录时才更新
2. 预览功能如何使用

## 分析

### 1. 缓存功能
**当前问题**：每次启动都重新扫描，没有缓存机制

**解决方案**：
- 将目录结构保存到JSON文件
- 启动时自动加载缓存
- 点击"扫描目录"时更新缓存

**实现方式**：
```python
import json

# 保存缓存
def save_cache(tree_data, file_path="cache.json"):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(tree_data, f, ensure_ascii=False, indent=2)

# 加载缓存
def load_cache(file_path="cache.json"):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None
```

### 2. 预览功能使用
**当前问题**：用户不知道如何触发预览

**分析代码**：
- 预览在 `on_tree_select` 中触发（点击文件时）
- 但同时会触发 `on_tree_click` 切换选中状态
- 这可能导致用户体验混乱

**改进方案**：
- 区分"选中"和"预览"操作
- 单击：切换选中状态（复选框）
- 双击：预览文件内容
- 或者：右键菜单提供预览选项

**实现方式**：
```python
# 修改事件绑定
self.tree.bind("<ButtonRelease-1>", self.on_tree_click)  # 单击：切换选中
self.tree.bind("<Double-1>", self.on_tree_double_click)   # 双击：预览

# 或者使用右键菜单
self.tree.bind("<Button-3>", self.show_context_menu)  # 右键：显示菜单
```

## 实施计划

### 任务1：添加缓存功能
1. 在 `__init__` 中添加缓存文件路径
2. 修改 `scan_website` 方法，扫描完成后保存缓存
3. 添加 `_load_cache` 方法，启动时加载缓存
4. 修改 `_create_widgets`，启动时自动加载缓存

### 任务2：改进预览功能
1. 修改事件绑定，区分单击和双击
2. 单击：切换选中状态
3. 双击：预览文件内容
4. 添加右键菜单（可选）

### 任务3：测试
1. 测试缓存保存和加载
2. 测试预览功能
3. 测试打包后的exe

## 预期成果
1. 目录结构缓存到本地文件
2. 启动时自动加载缓存
3. 点击"扫描目录"时更新缓存
4. 双击文件预览内容
5. 单击文件切换选中状态