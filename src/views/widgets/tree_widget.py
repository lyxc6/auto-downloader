"""树形组件扩展"""
from PySide6.QtWidgets import QTreeWidgetItem
from PySide6.QtCore import Qt

from qfluentwidgets import TreeWidget

from ...models import DownloadItem, ItemType


class DownloadTreeWidget(TreeWidget):
    """下载树形组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = {}  # item_id -> QTreeWidgetItem
        self._updating = False
        self.setHeaderLabels(["名称", "类型", "大小"])
        self.setColumnWidth(0, 300)
        self.setColumnWidth(1, 80)
        self.setColumnWidth(2, 100)
        self.itemChanged.connect(self._on_item_changed)
    
    def add_item(self, item: DownloadItem):
        """添加项目"""
        if item.item_id in self._items:
            return
        
        # 创建树项
        tree_item = QTreeWidgetItem()
        tree_item.setText(0, item.name)
        tree_item.setText(1, "📁" if item.is_dir else "📄")
        tree_item.setText(2, self._format_size(item.size) if item.is_file else "")
        tree_item.setFlags(
            tree_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
        )
        tree_item.setCheckState(0, Qt.CheckState.Unchecked)
        
        # 设置数据
        tree_item.setData(0, Qt.ItemDataRole.UserRole, item.item_id)
        
        # 添加到父节点或根节点
        if item.parent_id and item.parent_id in self._items:
            parent_item = self._items[item.parent_id]
            parent_item.addChild(tree_item)
        else:
            self.addTopLevelItem(tree_item)
        
        self._items[item.item_id] = tree_item
    
    def toggle_check(self, item_id: str):
        """切换选中状态"""
        if item_id in self._items:
            item = self._items[item_id]
            is_checked = item.checkState(0) == Qt.CheckState.Checked
            item.setCheckState(
                0, 
                Qt.CheckState.Unchecked if is_checked else Qt.CheckState.Checked
            )
    
    def is_checked(self, item_id: str) -> bool:
        """是否选中"""
        if item_id in self._items:
            return self._items[item_id].checkState(0) == Qt.CheckState.Checked
        return False
    
    def get_checked_items(self) -> list:
        """获取所有选中项"""
        checked = []
        for item_id, item in self._items.items():
            if item.checkState(0) == Qt.CheckState.Checked:
                checked.append(item_id)
        return checked
    
    def select_all(self):
        """全选——只操作顶级节点，级联自动处理子项"""
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            item.setCheckState(0, Qt.CheckState.Checked)
    
    def deselect_all(self):
        """取消全选——只操作顶级节点，级联自动处理子项"""
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            item.setCheckState(0, Qt.CheckState.Unchecked)
    
    def _on_item_changed(self, item, column):
        """勾选状态变化时级联处理"""
        if self._updating or column != 0:
            return
        self._updating = True
        checked = item.checkState(0) == Qt.CheckState.Checked
        self._cascade_check(item, checked)
        self._update_parent_state(item.parent())
        self._updating = False
    
    def _cascade_check(self, item, checked):
        """递归设置子节点勾选状态"""
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, state)
            self._cascade_check(child, checked)
    
    def _update_parent_state(self, parent):
        """根据子节点状态更新父节点勾选"""
        if parent is None:
            return
        checked_count = 0
        unchecked_count = 0
        total = parent.childCount()
        for i in range(total):
            state = parent.child(i).checkState(0)
            if state == Qt.CheckState.Checked:
                checked_count += 1
            elif state == Qt.CheckState.Unchecked:
                unchecked_count += 1
        if checked_count == total:
            parent.setCheckState(0, Qt.CheckState.Checked)
        elif unchecked_count == total:
            parent.setCheckState(0, Qt.CheckState.Unchecked)
        else:
            parent.setCheckState(0, Qt.CheckState.PartiallyChecked)
        self._update_parent_state(parent.parent())
    
    def expand_all_items(self):
        """展开所有"""
        self.expandAll()
    
    def collapse_all_items(self):
        """收起所有"""
        self.collapseAll()
    
    def clear_all(self):
        """清空所有"""
        self.clear()
        self._items.clear()
    
    @staticmethod
    def _format_size(size: int) -> str:
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"
