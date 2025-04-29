"""
配置管理模块 - 负责加载和验证 config.yaml 配置文件
"""

import os
import logging
import yaml
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class ConfigError(Exception):
    """配置错误异常类"""
    pass

class Config:
    """配置类，负责加载、验证和提供对配置的访问"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        初始化配置
        
        Args:
            config_path: 配置文件路径，默认为项目根目录下的 config.yaml
        
        Raises:
            ConfigError: 当配置文件不存在、无法解析或缺少必要配置项时
        """
        self.config_path = config_path
        self.config_data = {}
        self.load_config()
        self.validate_config()
    
    def load_config(self) -> None:
        """
        从指定路径加载 YAML 配置文件
        
        Raises:
            ConfigError: 当配置文件不存在或无法解析时
        """
        try:
            if not os.path.exists(self.config_path):
                raise ConfigError(f"配置文件不存在: {self.config_path}")
            
            with open(self.config_path, 'r', encoding='utf-8') as file:
                self.config_data = yaml.safe_load(file)
                
            if not self.config_data:
                raise ConfigError("配置文件为空或格式不正确")
                
            logger.info(f"已成功加载配置文件: {self.config_path}")

            # 读取自定义 API 接入点，环境变量优先
            env_api_base = os.getenv('TELEGRAM_API_BASE')
            # 确保 telegram section 存在再获取 api_base_url
            config_api_base = None
            if 'telegram' in self.config_data and isinstance(self.config_data['telegram'], dict):
                config_api_base = self.config_data['telegram'].get('api_base_url')

            final_api_base_url = None
            if env_api_base:
                final_api_base_url = env_api_base
                logger.info(f"使用环境变量 TELEGRAM_API_BASE 设置 API 接入点: {final_api_base_url}")
            elif config_api_base:
                final_api_base_url = config_api_base
                logger.info(f"使用配置文件 config.yaml 设置 API 接入点: {final_api_base_url}")
            else:
                logger.info("未指定自定义 Telegram API 接入点，将使用官方 API")

            # 将最终确定的 URL 存储回 config_data，确保 telegram section 存在
            if 'telegram' not in self.config_data:
                 # 如果 validate_config 还没运行，这可能需要创建
                 # 但考虑到 validate_config 的存在，这里假设它已存在或将被创建
                 # 为了安全起见，如果不存在，我们创建一个空的
                 self.config_data['telegram'] = {}
            elif not isinstance(self.config_data['telegram'], dict):
                 # 如果 telegram 不是字典，也需要处理，但 validate_config 应该会捕获
                 raise ConfigError("配置中的 'telegram' 部分必须是一个字典")

            self.config_data['telegram']['api_base_url'] = final_api_base_url

        except yaml.YAMLError as e:
            raise ConfigError(f"YAML 解析错误: {e}")
        except Exception as e:
            raise ConfigError(f"加载配置时出错: {e}")
    
    def validate_config(self) -> None:
        """
        验证配置是否包含所有必要的配置项
        
        Raises:
            ConfigError: 当缺少必要配置项时
        """
        required_sections = {
            'telegram': ['api_token', 'authorized_users'],
            'aria2': ['host', 'port', 'secret'],
            'database': ['path'],
        }
        
        for section, fields in required_sections.items():
            if section not in self.config_data:
                raise ConfigError(f"配置缺少必要的部分: {section}")
            
            for field in fields:
                if field not in self.config_data[section]:
                    raise ConfigError(f"配置部分 '{section}' 缺少必要的字段: {field}")
        
        # 验证 authorized_users 是否为非空列表
        if not isinstance(self.config_data['telegram']['authorized_users'], list) or \
           len(self.config_data['telegram']['authorized_users']) == 0:
            raise ConfigError("authorized_users 必须是一个非空的用户 ID 列表")
        
        logger.info("配置验证通过")
    
    def get(self, section: str, key: Optional[str] = None, default: Any = None) -> Any:
        """
        获取配置项
        
        Args:
            section: 配置部分名称
            key: 配置项名称，如果为 None，则返回整个部分
            default: 当配置项不存在时返回的默认值
            
        Returns:
            配置项值或默认值
        """
        if section not in self.config_data:
            return default
        
        if key is None:
            return self.config_data[section]
        
        return self.config_data[section].get(key, default)
    
    @property
    def telegram_token(self) -> str:
        """获取 Telegram Bot Token"""
        return self.get('telegram', 'api_token')
    
    @property
    def authorized_users(self) -> List[int]:
        """获取授权用户 ID 列表"""
        return self.get('telegram', 'authorized_users')

    @property
    def telegram_api_base_url(self) -> Optional[str]:
        """获取自定义 Telegram Bot API 基础 URL"""
        # 直接从 config_data 中获取，因为 load_config 已经处理了优先级
        return self.get('telegram', 'api_base_url')

    @property
    def aria2_host(self) -> str:
        """获取 Aria2 主机地址"""
        return self.get('aria2', 'host')
    
    @property
    def aria2_port(self) -> int:
        """获取 Aria2 端口"""
        return self.get('aria2', 'port')
    
    @property
    def aria2_secret(self) -> str:
        """获取 Aria2 RPC 密钥"""
        return self.get('aria2', 'secret')
    
    @property
    def aria2_url(self) -> str:
        """获取完整的 Aria2 RPC URL"""
        return f"{self.aria2_host}:{self.aria2_port}/jsonrpc"
    
    @property
    def database_path(self) -> str:
        """获取数据库路径"""
        return self.get('database', 'path')
    
    @property
    def max_history(self) -> int:
        """获取最大历史记录数"""
        return self.get('database', 'max_history', 100)
    
    @property
    def items_per_page(self) -> int:
        """获取每页显示的记录数"""
        return self.get('pagination', 'items_per_page', 5)
    
    @property
    def notification_enabled(self) -> bool:
        """获取是否启用通知"""
        return self.get('telegram', 'notification', {}).get('enabled', False)
    
    @property
    def notification_interval(self) -> int:
        """获取通知检查间隔（秒）"""
        return self.get('telegram', 'notification', {}).get('check_interval', 60)
    
    @property
    def notify_users(self) -> List[int]:
        """获取通知接收用户列表，默认为所有授权用户"""
        return self.get('telegram', 'notification', {}).get('notify_users', self.authorized_users)
    
    @property
    def logging_config(self) -> Dict[str, Any]:
        """获取日志配置"""
        return self.get('logging', default={})


# 全局单例配置对象
_config = None

def get_config(config_path: str = "config.yaml") -> Config:
    """
    获取配置单例对象
    
    Args:
        config_path: 配置文件路径，仅在首次调用时生效
        
    Returns:
        Config 实例
    """
    global _config
    if _config is None:
        _config = Config(config_path)
    return _config