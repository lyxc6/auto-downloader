"""树形组件扩展"""

from collections import deque

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidgetItem
from qfluentwidgets import RoundMenu, TreeWidget

from ...models import DownloadItem
from ...utils.helpers import format_size


class TreeIndex:
    """树数据索引：全量项 / 父子索引 / 加载状态 / 未扫描目录的统一管理

    四个平行结构必须保持同步，所有增删改统一经由此类，
    避免树组件内部多处手工维护导致状态漂移。
    """

    def __init__(self):
        self._all_items: dict[str, DownloadItem] = {}
        self._children_index: dict[str, list[str]] = {}
        self._loaded: set[str] = set()
        self._unscanned_dirs: set[str] = set()
        # 目录 id -> 文件后代总数（勾选三态 O(1) 判定用）
        self._dir_file_count: dict[str, int] = {}

    # ==================== 只读访问（供 Qt 层查询） ====================

    @property
    def all_items(self) -> dict[str, DownloadItem]:
        return self._all_items

    @property
    def children_index(self) -> dict[str, list[str]]:
        return self._children_index

    @property
    def loaded(self) -> set[str]:
        return self._loaded

    @property
    def unscanned_dirs(self) -> set[str]:
        return self._unscanned_dirs

    def has(self, item_id: str) -> bool:
        return item_id in self._all_items

    def get(self, item_id: str) -> DownloadItem | None:
        return self._all_items.get(item_id)

    def dir_file_count(self, item_id: str) -> int:
        """目录的文件后代总数（O(1)）"""
        return self._dir_file_count.get(item_id, 0)

    def ancestors(self, item_id: str) -> list[str]:
        """返回 item 的所有祖先目录 id（自底向上，不含自身）"""
        result: list[str] = []
        seen: set[str] = set()
        item = self._all_items.get(item_id)
        parent_id = item.parent_id if item else ""
        while parent_id and parent_id not in seen:
            result.append(parent_id)
            seen.add(parent_id)
            parent_item = self._all_items.get(parent_id)
            parent_id = parent_item.parent_id if parent_item else ""
        return result

    @staticmethod
    def sort_key(item: DownloadItem) -> tuple:
        """排序键：目录优先，按名称字母顺序"""
        return (0 if item.is_dir else 1, item.name.lower())

    # ==================== 增删改（统一入口） ====================

    def load_all(self, items_dict: dict[str, DownloadItem]) -> None:
        """全量重建索引（load_from_items / 缓存恢复场景）"""
        self._all_items = dict(items_dict)
        self._children_index = {}
        for item in self._all_items.values():
            self._children_index.setdefault(item.parent_id, []).append(item.item_id)
        for child_ids in self._children_index.values():
            child_ids.sort(key=lambda cid: self.sort_key(self._all_items[cid]))
        self._loaded = set()
        self._unscanned_dirs = set()
        self._rebuild_dir_file_count()

    def _rebuild_dir_file_count(self):
        """重建目录文件计数（每个文件沿祖先链 +1，一次 O(N×深度)）"""
        counts: dict[str, int] = {}
        for item in self._all_items.values():
            if item.is_file:
                for pid in self.ancestors(item.item_id):
                    counts[pid] = counts.get(pid, 0) + 1
        self._dir_file_count = counts

    def _bump_dir_file_count(self, item: DownloadItem, delta: int) -> None:
        """沿祖先链增减文件计数（add/remove 时维护）"""
        if not item.is_file:
            return
        for pid in self.ancestors(item.item_id):
            self._dir_file_count[pid] = self._dir_file_count.get(pid, 0) + delta

    def add_item(self, item: DownloadItem) -> bool:
        """增量添加（实时扫描 / 节流批量路径共用）

        目录项自动进入未扫描集合（与 add_items_batch 保持一致）。
        Returns:
            True 表示真正新增，False 表示已存在
        """
        if item.item_id in self._all_items:
            return False
        self._all_items[item.item_id] = item
        self._children_index.setdefault(item.parent_id, []).append(item.item_id)
        if item.is_dir:
            self._unscanned_dirs.add(item.item_id)
            self._dir_file_count.setdefault(item.item_id, 0)
        else:
            self._bump_dir_file_count(item, 1)
        return True

    def set_unscanned_dirs(self, dirs: set[str]) -> None:
        """整体替换未扫描集合（apply_scan_status 场景）"""
        self._unscanned_dirs = set(dirs)

    def mark_dir_scanned(self, dir_id: str) -> None:
        """单个目录扫描完成：从未扫描集合移除"""
        self._unscanned_dirs.discard(dir_id)

    def file_descendants(self, item_id: str) -> list[str]:
        """BFS 索引收集所有文件后代 item_id"""
        result: list[str] = []
        queue = deque(self._children_index.get(item_id, []))
        while queue:
            cid = queue.popleft()
            item = self._all_items[cid]
            if item.is_file:
                result.append(cid)
            else:
                queue.extend(self._children_index.get(cid, []))
        return result

    def remove_descendants(self, dir_item_id: str) -> set[str]:
        """移除目录的所有后代（含子目录和文件），保留目录自身

        Returns:
            被移除的 item_id 集合
        """
        descendant_ids: set[str] = set()
        queue = deque(self._children_index.get(dir_item_id, []))
        while queue:
            cid = queue.popleft()
            descendant_ids.add(cid)
            queue.extend(self._children_index.get(cid, []))

        # 统计被移除的文件数，沿祖先链递减计数（被移除目录自身的计数已随移除消失）
        removed_files = sum(1 for did in descendant_ids if self._all_items[did].is_file)
        for pid in [dir_item_id, *self.ancestors(dir_item_id)]:
            if pid in self._dir_file_count:
                self._dir_file_count[pid] -= removed_files

        for did in descendant_ids:
            self._all_items.pop(did, None)
            self._children_index.pop(did, None)
            self._loaded.discard(did)
            self._unscanned_dirs.discard(did)
            self._dir_file_count.pop(did, None)

        # 目录自身的孩子列表已清空
        self._children_index.pop(dir_item_id, None)
        self._loaded.discard(dir_item_id)
        self._unscanned_dirs.discard(dir_item_id)

        return descendant_ids

    def clear(self) -> None:
        """清空全部索引"""
        self._all_items.clear()
        self._children_index.clear()
        self._loaded.clear()
        self._unscanned_dirs.clear()
        self._dir_file_count.clear()


class DownloadTreeWidget(TreeWidget):
    """下载树形组件（虚拟加载）"""

    refresh_dir_requested = Signal(str)
    checked_ids_changed = Signal(set)  # 勾选集合变化（实时同步）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._index = TreeIndex()
        self._items: dict[str, QTreeWidgetItem] = {}  # realized 节点（item_id -> QTreeWidgetItem）
        self._checked_set: set[str] = set()  # 勾选真值源（与 realize 状态无关）
        # 目录 id -> 已勾选文件后代数（勾选三态 O(1) 判定用，勾选变化时增量维护）
        self._checked_dir_count: dict[str, int] = {}
        self._updating = False
        self._batch_expanding = False
        self.setHeaderLabels(["名称", "类型", "大小"])
        self.setColumnWidth(0, 300)
        self.setColumnWidth(1, 80)
        self.setColumnWidth(2, 100)
        self.itemChanged.connect(self._on_item_changed)
        self.itemExpanded.connect(self._on_item_expanded)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    # ==================== 兼容只读视图（测试与外部内省用） ====================

    @property
    def _all_items(self) -> dict[str, DownloadItem]:
        return self._index.all_items

    @property
    def _children_index(self) -> dict[str, list[str]]:
        return self._index.children_index

    @property
    def _loaded(self) -> set[str]:
        return self._index.loaded

    @property
    def _unscanned_dirs(self) -> set[str]:
        return self._index.unscanned_dirs

    def load_from_items(self, items_dict: dict[str, DownloadItem]) -> None:
        """一次性接收全量项，预建索引，仅 realize 根节点"""
        self.clear_all()
        self._index.load_all(items_dict)
        self._updating = True
        try:
            for cid in self._index.children_index.get("", []):
                self._realize_node(cid, None)
        finally:
            self._updating = False

    def _realize_node(self, item_id, parent_item):
        """创建单个 QTreeWidgetItem 并挂载"""
        item = self._all_items[item_id]
        tw = QTreeWidgetItem()
        tw.setText(0, item.name)
        tw.setText(1, self._dir_icon(item_id) if item.is_dir else "📄")
        tw.setText(2, format_size(item.size) if item.is_file else "")
        tw.setFlags(tw.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        tw.setData(0, Qt.ItemDataRole.UserRole, item_id)
        tw.setCheckState(0, self._compute_check_state(item_id))
        if self._children_index.get(item_id) and item_id not in self._loaded:
            tw.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        if parent_item is None:
            self.addTopLevelItem(tw)
        else:
            parent_item.addChild(tw)
        self._items[item_id] = tw
        return tw

    def _dir_icon(self, item_id: str) -> str:
        """目录状态图标：📂=未扫描完成, 📁=已扫描完成"""
        return "📂" if item_id in self._unscanned_dirs else "📁"

    def apply_scan_status(self, unscanned_dirs: set[str]) -> None:
        """更新目录节点的扫描状态图标"""
        self._index.set_unscanned_dirs(unscanned_dirs)
        for item_id, tw in self._items.items():
            item = self._all_items.get(item_id)
            if item and item.is_dir:
                tw.setText(1, self._dir_icon(item_id))

    def mark_dir_scanned(self, dir_id: str) -> None:
        """单个目录扫描完成：从未扫描集合移除并更新图标"""
        self._index.mark_dir_scanned(dir_id)
        tw = self._items.get(dir_id)
        if tw is not None:
            tw.setText(1, self._dir_icon(dir_id))

    def _sort_children_of(self, parent_id: str) -> None:
        """对指定父节点的子节点排序（索引+Qt 树）"""
        child_ids = self._children_index.get(parent_id)
        if not child_ids or len(child_ids) <= 1:
            return
        child_ids.sort(key=lambda cid: self._index.sort_key(self._all_items[cid]))
        if parent_id == "":
            self._reorder_top_level_items(child_ids)
        elif parent_id in self._loaded:
            parent_tw = self._items.get(parent_id)
            if parent_tw is not None:
                self._reorder_child_items(parent_tw, child_ids)

    def _reorder_top_level_items(self, sorted_ids: list[str]) -> None:
        """按排序后的 item_id 顺序重排顶级节点"""
        item_map: dict[str, QTreeWidgetItem] = {}
        while self.topLevelItemCount() > 0:
            tw = self.takeTopLevelItem(0)
            cid = tw.data(0, Qt.ItemDataRole.UserRole)
            if cid:
                item_map[cid] = tw
        for cid in sorted_ids:
            tw = item_map.pop(cid, None)
            if tw is not None:
                self.addTopLevelItem(tw)
        # 剩余项（不应出现）按原顺序补回
        for tw in item_map.values():
            self.addTopLevelItem(tw)

    def _reorder_child_items(self, parent_tw: QTreeWidgetItem, sorted_ids: list[str]) -> None:
        """按排序后的 item_id 顺序重排子节点"""
        item_map: dict[str, QTreeWidgetItem] = {}
        while parent_tw.childCount() > 0:
            tw = parent_tw.takeChild(0)
            cid = tw.data(0, Qt.ItemDataRole.UserRole)
            if cid:
                item_map[cid] = tw
        for cid in sorted_ids:
            tw = item_map.pop(cid, None)
            if tw is not None:
                parent_tw.addChild(tw)
        for tw in item_map.values():
            parent_tw.addChild(tw)

    def _on_item_expanded(self, tw):
        """展开时按需 populate 子节点"""
        if self._batch_expanding:
            return
        item_id = tw.data(0, Qt.ItemDataRole.UserRole)
        if item_id in self._loaded:
            return
        self._loaded.add(item_id)
        tw.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicatorWhenChildless)
        self._updating = True
        try:
            for cid in self._children_index.get(item_id, []):
                self._realize_node(cid, tw)
        finally:
            self._updating = False

    def _compute_check_state(self, item_id):
        """从勾选计数缓存计算三态（O(1)，不依赖 realized 子节点）"""
        item = self._all_items[item_id]
        if item.is_file:
            return Qt.CheckState.Checked if item_id in self._checked_set else Qt.CheckState.Unchecked
        total = self._index.dir_file_count(item_id)
        if total <= 0:
            return Qt.CheckState.Unchecked
        checked = self._checked_dir_count.get(item_id, 0)
        if checked >= total:
            return Qt.CheckState.Checked
        if checked <= 0:
            return Qt.CheckState.Unchecked
        return Qt.CheckState.PartiallyChecked

    def _update_checked_counts(self, file_ids: list[str], delta: int) -> None:
        """批量更新勾选计数：file_ids 中每个文件沿祖先链 ±1"""
        for fid in file_ids:
            for pid in self._index.ancestors(fid):
                self._checked_dir_count[pid] = self._checked_dir_count.get(pid, 0) + delta

    def add_item(self, item: DownloadItem):
        """增量添加（实时扫描路径）：更新索引，按需 realize"""
        if not self._index.add_item(item):
            return
        self._updating = True
        try:
            parent_tw = self._items.get(item.parent_id)
            if item.parent_id == "":
                self._realize_node(item.item_id, None)
            elif parent_tw is not None and item.parent_id in self._loaded:
                self._realize_node(item.item_id, parent_tw)
            elif parent_tw is not None:
                parent_tw.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        finally:
            self._updating = False

    def add_items_batch(self, items_list: list[DownloadItem]) -> None:
        """批量添加（节流扫描信号路径）"""
        affected_parents: set[str] = set()
        self._updating = True
        try:
            for item in items_list:
                if not self._index.add_item(item):
                    continue
                affected_parents.add(item.parent_id)
                parent_tw = self._items.get(item.parent_id)
                if item.parent_id == "":
                    self._realize_node(item.item_id, None)
                elif parent_tw is not None and item.parent_id in self._loaded:
                    self._realize_node(item.item_id, parent_tw)
                elif parent_tw is not None:
                    parent_tw.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        finally:
            for pid in affected_parents:
                self._sort_children_of(pid)
            self._updating = False

    def is_checked(self, item_id: str) -> bool:
        """是否选中（半选状态返回 False）"""
        tw = self._items.get(item_id)
        if tw is not None:
            return tw.checkState(0) == Qt.CheckState.Checked
        return item_id in self._checked_set

    def get_checked_items(self) -> list[str]:
        """获取所有选中项（O(1)，返回集合副本）"""
        return list(self._checked_set)

    def get_checked_files(self) -> list[DownloadItem]:
        """返回勾选的 DownloadItem 列表（从 _all_items + _checked_set，不依赖 cache_manager）"""
        return [
            self._all_items[iid] for iid in self._checked_set if iid in self._all_items and self._all_items[iid].is_file
        ]

    def _set_checked_set(self, checked_ids: set[str], notify: bool = False) -> None:
        """设置真值源并刷新已实现节点三态（select_all/deselect_all/apply_checked_items 共用）"""
        new_set = set(checked_ids)
        # 增量维护勾选计数：只处理新旧集合的差异，避免全量重算
        removed = self._checked_set - new_set
        added = new_set - self._checked_set
        if removed:
            self._update_checked_counts(list(removed), -1)
        if added:
            self._update_checked_counts(list(added), 1)
        self._checked_set = new_set
        self._updating = True
        try:
            for iid, tw in self._items.items():
                tw.setCheckState(0, self._compute_check_state(iid))
        finally:
            self._updating = False
        if notify:
            self.checked_ids_changed.emit(set(self._checked_set))

    def select_all(self):
        """全选：所有文件加入真值源，刷新已实现节点"""
        self._set_checked_set({iid for iid, it in self._all_items.items() if it.is_file}, notify=True)

    def deselect_all(self):
        """取消全选：清空真值源，刷新已实现节点"""
        self._set_checked_set(set(), notify=True)

    def _on_item_changed(self, tw, column):
        """勾选状态变化：先变异真值源，再级联已实现节点"""
        if self._updating or column != 0:
            return
        item_id = tw.data(0, Qt.ItemDataRole.UserRole)
        checked = tw.checkState(0) == Qt.CheckState.Checked
        self._updating = True
        try:
            item = self._all_items[item_id]
            files = [item_id] if item.is_file else self._index.file_descendants(item_id)
            if checked:
                self._checked_set.update(files)
            else:
                self._checked_set.difference_update(files)
            self._update_checked_counts(files, 1 if checked else -1)
            self._cascade_check_realized(tw, checked)
            p = tw.parent()
            while p is not None:
                pid = p.data(0, Qt.ItemDataRole.UserRole)
                p.setCheckState(0, self._compute_check_state(pid))
                p = p.parent()
        finally:
            self._updating = False
        self.checked_ids_changed.emit(set(self._checked_set))

    def _cascade_check_realized(self, tw, checked):
        """递归设置已实现子节点勾选状态"""
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(tw.childCount()):
            child = tw.child(i)
            child.setCheckState(0, state)
            self._cascade_check_realized(child, checked)

    def expand_all_items(self):
        """批量展开所有已加载节点（不触发新的加载）"""
        self._batch_expanding = True
        self.blockSignals(True)
        self.setUpdatesEnabled(False)
        try:
            self._expand_loaded_recursive(self.invisibleRootItem())
        finally:
            self._batch_expanding = False
            self.blockSignals(False)
            self.setUpdatesEnabled(True)
            self.doItemsLayout()

    def _expand_loaded_recursive(self, tw_item):
        """递归展开已加载的节点（未加载的保持折叠）"""
        for i in range(tw_item.childCount()):
            child = tw_item.child(i)
            item_id = child.data(0, Qt.ItemDataRole.UserRole)
            if item_id in self._loaded:
                child.setExpanded(True)
                self._expand_loaded_recursive(child)

    def collapse_all_items(self):
        """收起所有"""
        self.collapseAll()

    def apply_checked_items(self, checked_ids: set[str]) -> None:
        """按 checked_ids 设置真值源，并刷新已实现节点三态（恢复场景）"""
        self._set_checked_set(checked_ids)

    def mark_loaded(self, item_id: str) -> None:
        """标记节点为已加载（子节点已填充或即将在扫描中增量填充）"""
        self._loaded.add(item_id)

    def update_item_size(self, item_id: str) -> None:
        """更新单个文件节点的大小显示"""
        tw = self._items.get(item_id)
        if tw is not None:
            item = self._all_items.get(item_id)
            if item is not None and item.is_file:
                self._updating = True
                try:
                    tw.setText(2, format_size(item.size))
                finally:
                    self._updating = False

    def clear_all(self):
        """清空所有"""
        self.clear()
        self._items.clear()
        self._index.clear()
        self._checked_set.clear()
        self._checked_dir_count.clear()

    def _show_context_menu(self, pos):
        """显示右键菜单"""
        item = self.itemAt(pos)
        if item is None:
            return
        item_id = item.data(0, Qt.ItemDataRole.UserRole)
        if item_id is None or item_id not in self._all_items:
            return
        dl_item = self._all_items[item_id]
        if not dl_item.is_dir:
            return
        menu = RoundMenu("", self)
        from PySide6.QtGui import QAction

        refresh_action = QAction("🔄 刷新此目录", self)
        refresh_action.triggered.connect(lambda checked=False, iid=item_id: self.refresh_dir_requested.emit(iid))
        menu.addAction(refresh_action)
        menu.exec_(self.viewport().mapToGlobal(pos))

    def _remove_realized_children(self, dir_item_id: str) -> None:
        """移除已 realized 的后代节点（Qt 层，含 C++ 对象已删除防御）"""
        tree_item = self._items.get(dir_item_id)
        if tree_item is None:
            return
        realized_desc: set[str] = set()

        def _collect_realized(tw_item, acc: set):
            for i in range(tw_item.childCount()):
                child = tw_item.child(i)
                cid = child.data(0, Qt.ItemDataRole.UserRole)
                if cid is not None:
                    acc.add(cid)
                _collect_realized(child, acc)

        _collect_realized(tree_item, realized_desc)
        for did in realized_desc:
            tw = self._items.pop(did, None)
            if tw is not None:
                try:
                    parent = tw.parent()
                except RuntimeError:
                    continue  # C++ 对象已删除（因父节点被移除时连带销毁）
                if parent is not None:
                    parent.removeChild(tw)
                else:
                    idx = self.indexOfTopLevelItem(tw)
                    if idx >= 0:
                        self.takeTopLevelItem(idx)

    def remove_children_of(self, dir_item_id: str) -> set[str]:
        """移除指定目录的所有子节点（含后代），保留目录自身。返回被移除的 item_id 集合"""
        descendant_ids = self._index.remove_descendants(dir_item_id)
        self._remove_realized_children(dir_item_id)
        # 同步清理勾选真值源中的失效 id，并递减相关目录勾选计数
        removed_checked = {fid for fid in descendant_ids if fid in self._checked_set}
        if removed_checked:
            self._update_checked_counts(list(removed_checked), -1)
        self._checked_set.difference_update(descendant_ids)
        # 被移除目录自身的勾选计数一并清除（含未勾选但残留的目录键）
        for did in descendant_ids:
            self._checked_dir_count.pop(did, None)

        tree_item = self._items.get(dir_item_id)
        if tree_item is not None and dir_item_id in self._all_items:
            tree_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)

        return descendant_ids
