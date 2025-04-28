import logging
from typing import Dict, Any, Optional, List, Union

# 设置日志记录器
logger = logging.getLogger(__name__)

# 定义分页状态的数据结构
class PageStateData:
    def __init__(self, page: int, total: int, data: Optional[Any] = None, keyword: Optional[str] = None):
        self.page = page
        self.total = total
        self.data = data # 可以存储任务列表、历史记录列表等
        self.keyword = keyword # 用于搜索分页

# 状态管理器
class PageStateManager:
    def __init__(self):
        # 结构: {state_type: {user_id: PageStateData}}
        self._states: Dict[str, Dict[int, PageStateData]] = {
            "history": {},
            "search": {},
            "status": {},
        }
        logger.info("分页状态管理器已初始化")

    def update_state(self, state_type: str, user_id: int, page: int, total: int, data: Optional[Any] = None, keyword: Optional[str] = None):
        """更新指定类型和用户的分页状态"""
        if state_type not in self._states:
            logger.warning(f"尝试更新未知的状态类型: {state_type}")
            return
        self._states[state_type][user_id] = PageStateData(page, total, data, keyword)
        logger.debug(f"更新状态: type={state_type}, user={user_id}, page={page}, total={total}")

    def get_state(self, state_type: str, user_id: int) -> Optional[PageStateData]:
        """获取指定类型和用户的分页状态"""
        if state_type not in self._states:
            logger.warning(f"尝试获取未知的状态类型: {state_type}")
            return None
        return self._states[state_type].get(user_id)

    def clear_state(self, state_type: str, user_id: int):
        """清除指定类型和用户的分页状态"""
        if state_type in self._states and user_id in self._states[state_type]:
            del self._states[state_type][user_id]
            logger.debug(f"清除状态: type={state_type}, user={user_id}")

    def clear_all_states(self, user_id: int):
        """清除指定用户的所有分页状态"""
        for state_type in self._states:
            if user_id in self._states[state_type]:
                del self._states[state_type][user_id]
        logger.debug(f"清除用户 {user_id} 的所有分页状态")

# 创建一个全局实例（或者在 bot_app.py 中创建并注入）
page_state_manager = PageStateManager()

# --- 辅助函数 (可选，用于简化处理器中的调用) ---

def get_page_state_manager() -> PageStateManager:
    """获取分页状态管理器实例"""
    # 这里可以直接返回全局实例，或者如果采用依赖注入，则从 context 获取
    return page_state_manager