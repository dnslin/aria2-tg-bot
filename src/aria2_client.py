"""
Aria2 客户端模块 - 封装与 Aria2 RPC 的异步交互
"""

import logging
import asyncio
from typing import Dict, List, Optional, Any, Tuple, Union
import aria2p
import aiohttp
from .config import get_config

logger = logging.getLogger(__name__)

class Aria2Error(Exception):
    """Aria2 操作相关错误的基类"""
    pass

class Aria2ConnectionError(Aria2Error):
    """Aria2 连接错误"""
    pass

class Aria2RequestError(Aria2Error):
    """Aria2 请求错误"""
    pass

class Aria2TaskNotFoundError(Aria2Error):
    """Aria2 任务不存在错误"""
    pass


class Aria2Client:
    """Aria2 客户端类，封装与 Aria2 RPC 的异步交互"""
    
    def __init__(self, host: Optional[str] = None, port: Optional[int] = None, secret: Optional[str] = None):
        """
        初始化 Aria2 客户端
        
        Args:
            host: Aria2 RPC 主机地址，默认从配置加载
            port: Aria2 RPC 端口，默认从配置加载
            secret: Aria2 RPC 密钥，默认从配置加载
        """
        config = get_config()
        self.host = host or config.aria2_host
        self.port = port or config.aria2_port
        self.secret = secret or config.aria2_secret
        self.timeout = config.get('aria2', 'timeout', 10)
        
        # 初始化 aria2p API 对象
        self.api = aria2p.API(
            aria2p.Client(
                host=self.host,
                port=self.port,
                secret=self.secret
            )
        )
        
        logger.info(f"Aria2 客户端已初始化: {self.host}:{self.port}")
    
    async def _check_connection(self) -> bool:
        """
        检查与 Aria2 RPC 服务器的连接
        
        Returns:
            连接是否成功
            
        Raises:
            Aria2ConnectionError: 当连接失败时
        """
        try:
            # 使用同步方法进行简单测试（getVersion），但在异步环境中执行
            loop = asyncio.get_running_loop()
            version = await loop.run_in_executor(None, self.api.client.get_version)
            logger.debug(f"Aria2 连接成功，版本: {version}")
            return True
        except Exception as e:
            logger.error(f"Aria2 连接失败: {e}")
            raise Aria2ConnectionError(f"无法连接到 Aria2 RPC 服务器: {e}")
    
    async def add_download(self, urls: Union[str, List[str]], options: Optional[Dict[str, Any]] = None) -> str:
        """
        添加下载任务
        
        Args:
            urls: 单个 URL 或 URL 列表
            options: 下载选项，可选
            
        Returns:
            下载任务的 GID
            
        Raises:
            Aria2ConnectionError: 连接失败时
            Aria2RequestError: 请求失败时
        """
        await self._check_connection()
        
        try:
            loop = asyncio.get_running_loop()
            if isinstance(urls, str):
                urls = [urls]
                
            # 使用 run_in_executor 在异步环境中执行同步方法
            download = await loop.run_in_executor(
                None,
                lambda: self.api.add_uris(urls, options=options)
            )
            
            logger.info(f"添加下载任务成功: {urls[0][:50]}... GID: {download.gid}")
            return download.gid
            
        except Exception as e:
            logger.error(f"添加下载任务失败: {e}")
            raise Aria2RequestError(f"添加下载任务失败: {e}")
    
    async def get_download(self, gid: str) -> Dict[str, Any]:
        """
        获取下载任务信息
        
        Args:
            gid: 下载任务的 GID
            
        Returns:
            下载任务信息的字典
            
        Raises:
            Aria2TaskNotFoundError: 任务不存在时
            Aria2ConnectionError: 连接失败时
            Aria2RequestError: 请求失败时
        """
        await self._check_connection()
        
        try:
            loop = asyncio.get_running_loop()
            download = await loop.run_in_executor(None, lambda: self.api.get_download(gid))
            
            # 将 Download 对象转换为字典
            info = {
                'gid': download.gid,
                'status': download.status,
                'name': download.name,
                'total_length': download.total_length,
                'completed_length': download.completed_length,
                'download_speed': download.download_speed,
                'upload_speed': download.upload_speed,
                'connections': download.connections,
                'progress': download.progress * 100,  # 转换为百分比
                'error_code': download.error_code,
                'error_message': download.error_message,
                'files': [{'path': f.path, 'name': f.name} for f in download.files],
                'dir': download.dir,
                'is_active': download.is_active,
                'is_complete': download.is_complete,
                'is_paused': download.is_paused,
                'is_removed': download.is_removed,
                'is_waiting': download.is_waiting,
                'created_time': download.created_time
            }
            
            # 计算预计剩余时间（ETA）
            if download.download_speed > 0 and not download.is_complete:
                remaining_bytes = download.total_length - download.completed_length
                eta_seconds = remaining_bytes / download.download_speed
                info['eta_seconds'] = eta_seconds
            else:
                info['eta_seconds'] = 0
            
            return info
            
        except aria2p.client.ClientException as e:
            if "Download not found" in str(e):
                logger.error(f"下载任务不存在: {gid}")
                raise Aria2TaskNotFoundError(f"下载任务不存在: {gid}")
            logger.error(f"获取下载任务信息失败: {e}")
            raise Aria2RequestError(f"获取下载任务信息失败: {e}")
        except Exception as e:
            logger.error(f"获取下载任务信息失败: {e}")
            raise Aria2RequestError(f"获取下载任务信息失败: {e}")
    
    async def get_active_downloads(self) -> List[Dict[str, Any]]:
        """
        获取所有活动下载任务
        
        Returns:
            活动下载任务列表
            
        Raises:
            Aria2ConnectionError: 连接失败时
            Aria2RequestError: 请求失败时
        """
        await self._check_connection()
        
        try:
            loop = asyncio.get_running_loop()
            downloads = await loop.run_in_executor(None, self.api.get_active_downloads)
            
            # 将 Download 对象转换为字典列表
            return [
                {
                    'gid': d.gid,
                    'status': d.status,
                    'name': d.name,
                    'total_length': d.total_length,
                    'completed_length': d.completed_length,
                    'progress': d.progress * 100,  # 转换为百分比
                    'download_speed': d.download_speed,
                    'is_active': d.is_active,
                    'is_waiting': d.is_waiting
                }
                for d in downloads
            ]
            
        except Exception as e:
            logger.error(f"获取活动下载任务失败: {e}")
            raise Aria2RequestError(f"获取活动下载任务失败: {e}")
    
    async def get_waiting_downloads(self) -> List[Dict[str, Any]]:
        """
        获取所有等待中的下载任务
        
        Returns:
            等待中的下载任务列表
            
        Raises:
            Aria2ConnectionError: 连接失败时
            Aria2RequestError: 请求失败时
        """
        await self._check_connection()
        
        try:
            loop = asyncio.get_running_loop()
            downloads = await loop.run_in_executor(None, self.api.get_waiting_downloads)
            
            return [
                {
                    'gid': d.gid,
                    'status': d.status,
                    'name': d.name,
                    'total_length': d.total_length,
                    'completed_length': d.completed_length,
                    'progress': d.progress * 100,  # 转换为百分比
                    'is_waiting': d.is_waiting
                }
                for d in downloads
            ]
            
        except Exception as e:
            logger.error(f"获取等待中的下载任务失败: {e}")
            raise Aria2RequestError(f"获取等待中的下载任务失败: {e}")
    
    async def get_stopped_downloads(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        获取已停止的下载任务
        
        Args:
            limit: 返回的最大任务数
            
        Returns:
            已停止的下载任务列表
            
        Raises:
            Aria2ConnectionError: 连接失败时
            Aria2RequestError: 请求失败时
        """
        await self._check_connection()
        
        try:
            loop = asyncio.get_running_loop()
            downloads = await loop.run_in_executor(None, lambda: self.api.get_stopped_downloads(limit=limit))
            
            return [
                {
                    'gid': d.gid,
                    'status': d.status,
                    'name': d.name,
                    'total_length': d.total_length,
                    'completed_length': d.completed_length,
                    'progress': d.progress * 100,  # 转换为百分比
                    'error_code': d.error_code,
                    'error_message': d.error_message,
                    'is_complete': d.is_complete,
                    'is_removed': d.is_removed
                }
                for d in downloads
            ]
            
        except Exception as e:
            logger.error(f"获取已停止的下载任务失败: {e}")
            raise Aria2RequestError(f"获取已停止的下载任务失败: {e}")
    
    async def pause_download(self, gid: str) -> bool:
        """
        暂停下载任务
        
        Args:
            gid: 下载任务的 GID
            
        Returns:
            操作是否成功
            
        Raises:
            Aria2TaskNotFoundError: 任务不存在时
            Aria2ConnectionError: 连接失败时
            Aria2RequestError: 请求失败时
        """
        await self._check_connection()
        
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: self.api.pause([gid]))
            logger.info(f"暂停下载任务: {gid}")
            return result
            
        except aria2p.client.ClientException as e:
            if "Download not found" in str(e):
                logger.error(f"下载任务不存在: {gid}")
                raise Aria2TaskNotFoundError(f"下载任务不存在: {gid}")
            logger.error(f"暂停下载任务失败: {e}")
            raise Aria2RequestError(f"暂停下载任务失败: {e}")
        except Exception as e:
            logger.error(f"暂停下载任务失败: {e}")
            raise Aria2RequestError(f"暂停下载任务失败: {e}")
    
    async def resume_download(self, gid: str) -> bool:
        """
        恢复下载任务
        
        Args:
            gid: 下载任务的 GID
            
        Returns:
            操作是否成功
            
        Raises:
            Aria2TaskNotFoundError: 任务不存在时
            Aria2ConnectionError: 连接失败时
            Aria2RequestError: 请求失败时
        """
        await self._check_connection()
        
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: self.api.resume([gid]))
            logger.info(f"恢复下载任务: {gid}")
            return result
            
        except aria2p.client.ClientException as e:
            if "Download not found" in str(e):
                logger.error(f"下载任务不存在: {gid}")
                raise Aria2TaskNotFoundError(f"下载任务不存在: {gid}")
            logger.error(f"恢复下载任务失败: {e}")
            raise Aria2RequestError(f"恢复下载任务失败: {e}")
        except Exception as e:
            logger.error(f"恢复下载任务失败: {e}")
            raise Aria2RequestError(f"恢复下载任务失败: {e}")
    
    async def remove_download(self, gid: str) -> bool:
        """
        删除下载任务
        
        Args:
            gid: 下载任务的 GID
            
        Returns:
            操作是否成功
            
        Raises:
            Aria2TaskNotFoundError: 任务不存在时
            Aria2ConnectionError: 连接失败时
            Aria2RequestError: 请求失败时
        """
        await self._check_connection()
        
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: self.api.remove([gid]))
            logger.info(f"删除下载任务: {gid}")
            return result
            
        except aria2p.client.ClientException as e:
            if "Download not found" in str(e):
                logger.error(f"下载任务不存在: {gid}")
                raise Aria2TaskNotFoundError(f"下载任务不存在: {gid}")
            logger.error(f"删除下载任务失败: {e}")
            raise Aria2RequestError(f"删除下载任务失败: {e}")
        except Exception as e:
            logger.error(f"删除下载任务失败: {e}")
            raise Aria2RequestError(f"删除下载任务失败: {e}")
    
    async def pause_all(self) -> bool:
        """
        暂停所有下载任务
        
        Returns:
            操作是否成功
            
        Raises:
            Aria2ConnectionError: 连接失败时
            Aria2RequestError: 请求失败时
        """
        await self._check_connection()
        
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self.api.pause_all)
            logger.info("暂停所有下载任务")
            return result
            
        except Exception as e:
            logger.error(f"暂停所有下载任务失败: {e}")
            raise Aria2RequestError(f"暂停所有下载任务失败: {e}")
    
    async def resume_all(self) -> bool:
        """
        恢复所有下载任务
        
        Returns:
            操作是否成功
            
        Raises:
            Aria2ConnectionError: 连接失败时
            Aria2RequestError: 请求失败时
        """
        await self._check_connection()
        
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self.api.resume_all)
            logger.info("恢复所有下载任务")
            return result
            
        except Exception as e:
            logger.error(f"恢复所有下载任务失败: {e}")
            raise Aria2RequestError(f"恢复所有下载任务失败: {e}")
    
    async def get_global_status(self) -> Dict[str, Any]:
        """
        获取 Aria2 全局状态
        
        Returns:
            全局状态信息的字典
            
        Raises:
            Aria2ConnectionError: 连接失败时
            Aria2RequestError: 请求失败时
        """
        await self._check_connection()
        
        try:
            loop = asyncio.get_running_loop()
            
            # 获取全局统计信息
            stats = await loop.run_in_executor(None, self.api.get_global_stat)
            
            # 获取不同状态的下载任务数量
            active_downloads = await loop.run_in_executor(None, lambda: len(self.api.get_active_downloads()))
            waiting_downloads = await loop.run_in_executor(None, lambda: len(self.api.get_waiting_downloads()))
            stopped_downloads = await loop.run_in_executor(None, lambda: len(self.api.get_stopped_downloads()))
            
            return {
                'download_speed': int(stats.download_speed),  # bytes/sec
                'upload_speed': int(stats.upload_speed),      # bytes/sec
                'active_downloads': active_downloads,
                'waiting_downloads': waiting_downloads,
                'stopped_downloads': stopped_downloads,
                'total_downloads': active_downloads + waiting_downloads + stopped_downloads,
                'num_active': int(stats.num_active),          # 活动下载数
                'num_waiting': int(stats.num_waiting),        # 等待下载数
                'num_stopped': int(stats.num_stopped),        # 已停止下载数（包括完成和错误的）
                'total_size': int(stats.total_size),          # 当前活动下载的总大小（字节）
                'server_time': int(stats.server_time),        # 服务器时间戳
                'version': await loop.run_in_executor(None, lambda: self.api.client.get_version())
            }
            
        except Exception as e:
            logger.error(f"获取全局状态失败: {e}")
            raise Aria2RequestError(f"获取全局状态失败: {e}")


# 全局单例客户端
_client = None

async def get_aria2_client(host: Optional[str] = None, port: Optional[int] = None, secret: Optional[str] = None) -> Aria2Client:
    """
    获取 Aria2 客户端单例
    
    Args:
        host: Aria2 RPC 主机地址，默认从配置加载
        port: Aria2 RPC 端口，默认从配置加载
        secret: Aria2 RPC 密钥，默认从配置加载
        
    Returns:
        Aria2Client 实例
    """
    global _client
    if _client is None:
        _client = Aria2Client(host, port, secret)
    return _client