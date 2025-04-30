"""
历史记录管理模块 - 使用 SQLite 数据库存储和管理下载历史
"""

import os
import logging
import aiosqlite
import json
import time
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path # Added import

from .config import get_config

logger = logging.getLogger(__name__)

class HistoryError(Exception):
    """历史记录操作错误的基类"""
    pass

class DatabaseError(HistoryError):
    """数据库操作错误"""
    pass


class HistoryManager:
    """历史记录管理类，提供对下载任务历史记录的异步 CRUD 操作"""
    
    def __init__(self, db_path: Optional[str] = None):
        """
        初始化历史记录管理器
        
        Args:
            db_path: 数据库文件路径，默认从配置加载
        """
        config = get_config()
        self.db_path = db_path or config.database_path
        self.max_history = config.max_history
        self._ensure_dir_exists()
        self._connection = None
        logger.info(f"历史记录管理器已初始化，数据库路径: {self.db_path}")
    
    def _ensure_dir_exists(self) -> None:
        """确保数据库目录存在"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"已创建数据库目录: {db_dir}")
    
    async def _get_connection(self) -> aiosqlite.Connection:
        """
        获取数据库连接
        
        Returns:
            aiosqlite.Connection 对象
            
        Raises:
            DatabaseError: 当数据库连接失败时
        """
        if self._connection is None:
            try:
                self._connection = await aiosqlite.connect(self.db_path)
                # 启用外键约束
                await self._connection.execute("PRAGMA foreign_keys = ON")
                # 设置返回结果为字典形式
                self._connection.row_factory = aiosqlite.Row
                
            except Exception as e:
                logger.error(f"连接数据库失败: {e}")
                raise DatabaseError(f"连接数据库失败: {e}")
                
        return self._connection
    
    async def close(self) -> None:
        """关闭数据库连接"""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.debug("数据库连接已关闭")
    
    async def init_db(self) -> None:
        """
        初始化数据库表结构
        
        Raises:
            DatabaseError: 当初始化数据库失败时
        """
        try:
            conn = await self._get_connection()
            await conn.executescript("""
                -- 创建下载历史表
                CREATE TABLE IF NOT EXISTS download_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gid TEXT NOT NULL UNIQUE,  -- Aria2 下载任务 GID
                    name TEXT NOT NULL,        -- 文件名
                    status TEXT NOT NULL,      -- 状态: completed, error, removed
                    timestamp INTEGER NOT NULL, -- 完成/出错/移除时间戳
                    size INTEGER,              -- 文件大小（字节）
                    error_code INTEGER,        -- 错误代码（如果有）
                    error_message TEXT,        -- 错误信息（如果有）
                    files TEXT,                -- 文件列表的 JSON 字符串
                    notified INTEGER DEFAULT 0, -- 是否已通知: 0=否，1=是
                    extra JSON                 -- 其他额外信息的 JSON 字符串
                );
                
                -- 创建索引
                CREATE INDEX IF NOT EXISTS idx_gid ON download_history(gid);
                CREATE INDEX IF NOT EXISTS idx_timestamp ON download_history(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_status ON download_history(status);
            """)
            await conn.commit()
            logger.info("数据库表结构初始化完成")
            
        except Exception as e:
            logger.error(f"初始化数据库失败: {e}")
            raise DatabaseError(f"初始化数据库失败: {e}")
    
    def _convert_paths_to_strings(self, data: Any) -> Any:
        """递归地将数据结构中的 Path 对象转换为字符串"""
        if isinstance(data, list):
            return [self._convert_paths_to_strings(item) for item in data]
        elif isinstance(data, dict):
            return {key: self._convert_paths_to_strings(value) for key, value in data.items()}
        elif isinstance(data, Path):
            return str(data)
        else:
            return data

    async def add_history(self,
                         gid: str,
                         name: str,
                         status: str, 
                         size: Optional[int] = None,
                         error_code: Optional[int] = None,
                         error_message: Optional[str] = None,
                         files: Optional[List[Dict[str, Any]]] = None,
                         timestamp: Optional[int] = None,
                         notified: bool = False,
                         extra: Optional[Dict[str, Any]] = None) -> int:
        """
        添加历史记录
        
        Args:
            gid: Aria2 下载任务 GID
            name: 文件名
            status: 状态 (completed, error, removed)
            size: 文件大小（字节），可选
            error_code: 错误代码，可选
            error_message: 错误信息，可选
            files: 文件列表，可选
            timestamp: 时间戳，默认为当前时间
            notified: 是否已通知，默认为 False
            extra: 其他额外信息，可选
            
        Returns:
            新插入记录的 ID
            
        Raises:
            DatabaseError: 当添加记录失败时
        """
        if timestamp is None:
            timestamp = int(time.time())
            
        try:
            conn = await self._get_connection()

            # Convert Path objects to strings before serialization
            files_serializable = self._convert_paths_to_strings(files) if files else None
            extra_serializable = self._convert_paths_to_strings(extra) if extra else None

# DEBUG: Log the data before JSON serialization
            logger.debug(f"Before UPDATE/INSERT - files_serializable type: {type(files_serializable)}, content: {files_serializable}")
            logger.debug(f"Before UPDATE/INSERT - extra_serializable type: {type(extra_serializable)}, content: {extra_serializable}")
            # 尝试更新现有记录（如果 GID 已存在）
            cursor = await conn.execute("""
                UPDATE download_history
                SET name = ?, status = ?, timestamp = ?, size = ?, 
                    error_code = ?, error_message = ?, files = ?, 
                    notified = ?, extra = ?
                WHERE gid = ?
            """, (
                name, status, timestamp, size,
                error_code, error_message, json.dumps(files_serializable) if files_serializable else None,
                1 if notified else 0, json.dumps(extra_serializable) if extra_serializable else None,
                gid
            ))
            
            if cursor.rowcount == 0:  # 如果没有更新任何行，则插入新记录
                cursor = await conn.execute("""
                    INSERT INTO download_history (
                        gid, name, status, timestamp, size, 
                        error_code, error_message, files, notified, extra
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    gid, name, status, timestamp, size,
                    error_code, error_message, json.dumps(files_serializable) if files_serializable else None,
                    1 if notified else 0, json.dumps(extra_serializable) if extra_serializable else None
                ))
            
            await conn.commit()
            record_id = cursor.lastrowid
            
            logger.info(f"添加/更新历史记录: GID={gid}, 状态={status}, ID={record_id}")
            
            # 自动修剪旧记录
            await self._trim_history()
            
            return record_id
            
        except Exception as e:
            logger.error(f"添加历史记录失败: {e}")
            raise DatabaseError(f"添加历史记录失败: {e}")
    
    async def get_history(self, 
                        page: int = 1, 
                        page_size: Optional[int] = None, 
                        status: Optional[str] = None) -> Tuple[List[Dict[str, Any]], int]:
        """
        获取历史记录（支持分页）
        
        Args:
            page: 页码（从 1 开始），默认为 1
            page_size: 每页记录数，默认从配置加载
            status: 可选，筛选特定状态 (completed, error, removed)
            
        Returns:
            包含两个元素的元组: (记录列表, 总记录数)
            
        Raises:
            DatabaseError: 当查询记录失败时
        """
        config = get_config()
        if page_size is None:
            page_size = config.items_per_page
            
        if page < 1:
            page = 1
            
        offset = (page - 1) * page_size
        
        try:
            conn = await self._get_connection()
            
            # 构建 SQL 查询
            query = "SELECT * FROM download_history"
            count_query = "SELECT COUNT(*) as total FROM download_history"
            params = []
            
            if status:
                query += " WHERE status = ?"
                count_query += " WHERE status = ?"
                params.append(status)
                
            query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([page_size, offset])
            
            # 获取总记录数
            cursor = await conn.execute(count_query, params[:-2] if status else [])
            total = (await cursor.fetchone())["total"]
            
            # 获取分页数据
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            
            # 将记录转换为字典列表
            result = []
            for row in rows:
                item = dict(row)
                
                # JSON 反序列化
                if item["files"]:
                    item["files"] = json.loads(item["files"])
                if item["extra"]:
                    item["extra"] = json.loads(item["extra"])
                    
                # 布尔值转换
                item["notified"] = bool(item["notified"])
                
                # 添加格式化的日期时间字符串
                dt = datetime.fromtimestamp(item["timestamp"])
                item["datetime"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                
                result.append(item)
            
            logger.debug(f"获取历史记录: 页码={page}, 每页={page_size}, 总数={total}, 返回={len(result)}")
            return result, total
            
        except Exception as e:
            logger.error(f"获取历史记录失败: {e}")
            raise DatabaseError(f"获取历史记录失败: {e}")
    
    async def get_history_by_gid(self, gid: str) -> Optional[Dict[str, Any]]:
        """
        通过 GID 获取单个历史记录
        
        Args:
            gid: Aria2 下载任务 GID
            
        Returns:
            记录字典，如果未找到则返回 None
            
        Raises:
            DatabaseError: 当查询记录失败时
        """
        try:
            conn = await self._get_connection()
            
            cursor = await conn.execute(
                "SELECT * FROM download_history WHERE gid = ?", (gid,)
            )
            row = await cursor.fetchone()
            
            if not row:
                return None
                
            item = dict(row)
            
            # JSON 反序列化
            if item["files"]:
                item["files"] = json.loads(item["files"])
            if item["extra"]:
                item["extra"] = json.loads(item["extra"])
                
            # 布尔值转换
            item["notified"] = bool(item["notified"])
            
            # 添加格式化的日期时间字符串
            dt = datetime.fromtimestamp(item["timestamp"])
            item["datetime"] = dt.strftime("%Y-%m-%d %H:%M:%S")
            
            return item
            
        except Exception as e:
            logger.error(f"通过 GID 获取历史记录失败: {e}")
            raise DatabaseError(f"通过 GID 获取历史记录失败: {e}")
    
    async def mark_as_notified(self, gid: str) -> bool:
        """
        将历史记录标记为已通知
        
        Args:
            gid: Aria2 下载任务 GID
            
        Returns:
            操作是否成功
            
        Raises:
            DatabaseError: 当更新记录失败时
        """
        try:
            conn = await self._get_connection()
            
            cursor = await conn.execute(
                "UPDATE download_history SET notified = 1 WHERE gid = ?", (gid,)
            )
            await conn.commit()
            
            success = cursor.rowcount > 0
            if success:
                logger.debug(f"已将 GID={gid} 标记为已通知")
            else:
                logger.warning(f"未找到 GID={gid} 的记录，无法标记为已通知")
                
            return success
            
        except Exception as e:
            logger.error(f"标记为已通知失败: {e}")
            raise DatabaseError(f"标记为已通知失败: {e}")
    
    async def get_unnotified_completed(self) -> List[Dict[str, Any]]:
        """
        获取所有未通知的已完成或出错的下载任务
        
        Returns:
            未通知的已完成/出错任务列表
            
        Raises:
            DatabaseError: 当查询记录失败时
        """
        try:
            conn = await self._get_connection()
            
            cursor = await conn.execute(
                "SELECT * FROM download_history WHERE notified = 0 AND status IN ('completed', 'error') ORDER BY timestamp DESC"
            )
            rows = await cursor.fetchall()
            
            result = []
            for row in rows:
                item = dict(row)
                
                # JSON 反序列化
                if item["files"]:
                    item["files"] = json.loads(item["files"])
                if item["extra"]:
                    item["extra"] = json.loads(item["extra"])
                    
                # 布尔值转换
                item["notified"] = bool(item["notified"])
                
                # 添加格式化的日期时间字符串
                dt = datetime.fromtimestamp(item["timestamp"])
                item["datetime"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                
                result.append(item)
            
            return result
            
        except Exception as e:
            logger.error(f"获取未通知的完成任务失败: {e}")
            raise DatabaseError(f"获取未通知的完成任务失败: {e}")
    
    async def search_history(self, keyword: str, page: int = 1, page_size: Optional[int] = None) -> Tuple[List[Dict[str, Any]], int]:
        """
        搜索历史记录
        
        Args:
            keyword: 搜索关键词，将在 name 和 error_message 字段中搜索
            page: 页码（从 1 开始），默认为 1
            page_size: 每页记录数，默认从配置加载
            
        Returns:
            包含两个元素的元组: (记录列表, 总记录数)
            
        Raises:
            DatabaseError: 当查询记录失败时
        """
        config = get_config()
        if page_size is None:
            page_size = config.items_per_page
            
        if page < 1:
            page = 1
            
        offset = (page - 1) * page_size
        keyword_param = f"%{keyword}%"
        
        try:
            conn = await self._get_connection()
            
            # 获取总记录数
            count_query = "SELECT COUNT(*) as total FROM download_history WHERE name LIKE ? OR error_message LIKE ?"
            cursor = await conn.execute(count_query, (keyword_param, keyword_param))
            total = (await cursor.fetchone())["total"]
            
            # 获取分页数据
            query = """
                SELECT * FROM download_history 
                WHERE name LIKE ? OR error_message LIKE ? 
                ORDER BY timestamp DESC LIMIT ? OFFSET ?
            """
            cursor = await conn.execute(query, (keyword_param, keyword_param, page_size, offset))
            rows = await cursor.fetchall()
            
            # 将记录转换为字典列表
            result = []
            for row in rows:
                item = dict(row)
                
                # JSON 反序列化
                if item["files"]:
                    item["files"] = json.loads(item["files"])
                if item["extra"]:
                    item["extra"] = json.loads(item["extra"])
                    
                # 布尔值转换
                item["notified"] = bool(item["notified"])
                
                # 添加格式化的日期时间字符串
                dt = datetime.fromtimestamp(item["timestamp"])
                item["datetime"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                
                result.append(item)
            
            logger.debug(f"搜索历史记录: 关键词='{keyword}', 页码={page}, 每页={page_size}, 总数={total}, 返回={len(result)}")
            return result, total
            
        except Exception as e:
            logger.error(f"搜索历史记录失败: {e}")
            raise DatabaseError(f"搜索历史记录失败: {e}")
    
    async def clear_history(self) -> int:
        """
        清空历史记录
        
        Returns:
            清除的记录数
            
        Raises:
            DatabaseError: 当清除记录失败时
        """
        try:
            conn = await self._get_connection()
            
            cursor = await conn.execute("DELETE FROM download_history")
            await conn.commit()
            
            count = cursor.rowcount
            logger.info(f"已清空历史记录: {count} 条记录被删除")
            
            return count
            
        except Exception as e:
            logger.error(f"清空历史记录失败: {e}")
            raise DatabaseError(f"清空历史记录失败: {e}")
    
    async def _trim_history(self) -> int:
        """
        修剪过旧的历史记录，保留最新的 max_history 条
        
        Returns:
            删除的记录数
            
        Raises:
            DatabaseError: 当删除记录失败时
        """
        if self.max_history <= 0:
            return 0
            
        try:
            conn = await self._get_connection()
            
            # 获取当前记录数
            cursor = await conn.execute("SELECT COUNT(*) as count FROM download_history")
            current_count = (await cursor.fetchone())["count"]
            
            if current_count <= self.max_history:
                return 0
                
            # 计算需要删除的记录数
            to_delete = current_count - self.max_history
            
            # 找出最早的 to_delete 条记录并删除
            delete_query = """
                DELETE FROM download_history
                WHERE id IN (
                    SELECT id FROM download_history
                    ORDER BY timestamp ASC
                    LIMIT ?
                )
            """
            cursor = await conn.execute(delete_query, (to_delete,))
            await conn.commit()
            
            actual_deleted = cursor.rowcount
            logger.info(f"已修剪历史记录: {actual_deleted} 条记录被删除，保留最新的 {self.max_history} 条")
            
            return actual_deleted
            
        except Exception as e:
            logger.error(f"修剪历史记录失败: {e}")
            raise DatabaseError(f"修剪历史记录失败: {e}")


# 全局单例历史记录管理器
_history_manager = None

async def get_history_manager(db_path: Optional[str] = None) -> HistoryManager:
    """
    获取历史记录管理器单例
    
    Args:
        db_path: 数据库文件路径，默认从配置加载，仅在首次调用时有效
        
    Returns:
        HistoryManager 实例
    """
    global _history_manager
    if _history_manager is None:
        _history_manager = HistoryManager(db_path)
        await _history_manager.init_db()
    return _history_manager