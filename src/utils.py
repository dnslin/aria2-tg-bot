"""
工具函数模块 - 提供各种辅助功能：消息格式化、分页、GID 验证等
"""

import re
import math
import logging
from typing import List, Dict, Any, Optional, Tuple, Union
import html
from datetime import timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

# GID 格式正则表达式（Aria2 的 GID 通常是 16 个十六进制字符）
GID_PATTERN = re.compile(r'^[0-9a-f]{16}$')

def validate_gid(gid: str) -> bool:
    """
    验证 GID 格式是否正确
    
    Args:
        gid: 要验证的 GID 字符串
        
    Returns:
        是否符合 GID 格式
    """
    return bool(GID_PATTERN.match(gid))

def format_size(size_bytes: int) -> str:
    """
    将字节大小格式化为易读的字符串 (KB, MB, GB)
    
    Args:
        size_bytes: 字节大小
        
    Returns:
        格式化后的字符串
    """
    if size_bytes < 0:
        return "未知大小"
    
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

def format_speed(speed_bytes_per_sec: int) -> str:
    """
    将速度格式化为易读的字符串 (KB/s, MB/s, GB/s)
    
    Args:
        speed_bytes_per_sec: 每秒字节速度
        
    Returns:
        格式化后的字符串
    """
    if speed_bytes_per_sec < 0:
        return "未知速度"
        
    return f"{format_size(speed_bytes_per_sec)}/s"

def format_eta(seconds: float) -> str:
    """
    将剩余时间格式化为易读的字符串
    
    Args:
        seconds: 剩余秒数
        
    Returns:
        格式化后的字符串
    """
    if seconds < 0 or seconds > 365 * 24 * 3600:
        return "未知时间"
        
    td = timedelta(seconds=seconds)
    
    if td.days > 0:
        return f"{td.days}天 {td.seconds//3600}小时"
    elif td.seconds >= 3600:
        hours = td.seconds // 3600
        minutes = (td.seconds % 3600) // 60
        return f"{hours}小时 {minutes}分钟"
    elif td.seconds >= 60:
        minutes = td.seconds // 60
        secs = td.seconds % 60
        return f"{minutes}分钟 {secs}秒"
    else:
        return f"{td.seconds}秒"

def format_progress(progress: float) -> str:
    """
    将进度百分比格式化为进度条字符串
    
    Args:
        progress: 进度百分比 (0-100)
        
    Returns:
        格式化后的进度条
    """
    if progress < 0 or progress > 100:
        progress = 0
        
    done_count = int(progress / 10)
    todo_count = 10 - done_count
    
    return f"{'■' * done_count}{'□' * todo_count} {progress:.1f}%"

def truncate_filename(filename: str, max_length: int = 30) -> str:
    """
    截断文件名到指定长度（中间使用 ... 表示）
    
    Args:
        filename: 原始文件名
        max_length: 最大长度，默认为 30
        
    Returns:
        截断后的文件名
    """
    if len(filename) <= max_length:
        return filename
        
    half = (max_length - 3) // 2
    return filename[:half] + "..." + filename[-half:]

def escape_html(text: str) -> str:
    """
    转义 HTML 特殊字符
    
    Args:
        text: 原始文本
        
    Returns:
        转义后的文本
    """
    return html.escape(text)

def escape_markdown(text: str) -> str:
    """
    转义 Markdown V2 特殊字符
    
    Args:
        text: 原始文本
        
    Returns:
        转义后的文本
    """
    # 需要转义的字符: '_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!'
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join([f'\\{c}' if c in escape_chars else c for c in text])

def format_task_info_html(task_info: Dict[str, Any]) -> str:
    """
    格式化任务信息（HTML 格式）
    
    Args:
        task_info: 任务信息字典
        
    Returns:
        格式化后的任务信息 HTML 文本
    """
    status_map = {
        'active': '下载中',
        'waiting': '等待中',
        'paused': '已暂停',
        'error': '出错',
        'complete': '已完成',
        'removed': '已删除'
    }
    
    status = status_map.get(task_info['status'], task_info['status'])
    
    # 计算进度和 ETA
    progress = task_info.get('progress', 0)
    eta = ""
    if 'eta_seconds' in task_info and task_info['eta_seconds'] > 0:
        eta = f"预计剩余: {format_eta(task_info['eta_seconds'])}"
    
    # 构建详细信息
    details = [
        f"<b>文件名:</b> {escape_html(task_info.get('name', '未知'))}",
        f"<b>状态:</b> {status}",
        f"<b>大小:</b> {format_size(task_info.get('total_length', 0))}"
    ]
    
    if progress > 0:
        details.append(f"<b>进度:</b> {format_progress(progress)}")
    
    if task_info.get('download_speed', 0) > 0:
        details.append(f"<b>下载速度:</b> {format_speed(task_info['download_speed'])}")
        
    if task_info.get('upload_speed', 0) > 0:
        details.append(f"<b>上传速度:</b> {format_speed(task_info['upload_speed'])}")
    
    if eta:
        details.append(f"<b>{eta}</b>")
    
    if 'error_message' in task_info and task_info['error_message']:
        details.append(f"<b>错误信息:</b> {escape_html(task_info['error_message'])}")
    
    # 构建文件列表
    if 'files' in task_info and task_info['files']:
        file_list = []
        for i, file_info in enumerate(task_info['files'], 1):
            if i > 5:  # 最多显示 5 个文件
                file_list.append(f"...共 {len(task_info['files'])} 个文件")
                break
            file_name = file_info.get('name', file_info.get('path', '未知'))
            file_list.append(f"- {escape_html(truncate_filename(file_name))}")
        
        if file_list:
            details.append("<b>文件:</b>")
            details.extend(file_list)
    
    return "\n".join(details)

def format_task_list_html(tasks: List[Dict[str, Any]], 
                         show_gid: bool = True, 
                         show_progress: bool = True,
                         max_length: int = 30) -> str:
    """
    格式化任务列表（HTML 格式）
    
    Args:
        tasks: 任务信息字典列表
        show_gid: 是否显示 GID，默认为 True
        show_progress: 是否显示进度，默认为 True
        max_length: 文件名最大显示长度，默认为 30
        
    Returns:
        格式化后的任务列表 HTML 文本
    """
    status_map = {
        'active': '下载中',
        'waiting': '等待中',
        'paused': '已暂停',
        'error': '出错',
        'complete': '已完成',
        'removed': '已删除'
    }
    
    if not tasks:
        return "没有任务"
        
    lines = []
    
    for i, task in enumerate(tasks, 1):
        status = status_map.get(task['status'], task['status'])
        name = truncate_filename(task.get('name', '未知'), max_length)
        
        line = [f"{i}. <b>{escape_html(name)}</b>"]
        
        if show_gid:
            line.append(f"[<code>{task['gid']}</code>]")
        
        line.append(f"({status})")
        
        if show_progress and 'progress' in task:
            line.append(f"{task['progress']:.1f}%")
            
        lines.append(" ".join(line))
    
    return "\n".join(lines)

def format_history_list_html(histories: List[Dict[str, Any]], max_length: int = 30) -> str:
    """
    格式化历史记录列表（HTML 格式）
    
    Args:
        histories: 历史记录字典列表
        max_length: 文件名最大显示长度，默认为 30
        
    Returns:
        格式化后的历史记录列表 HTML 文本
    """
    status_map = {
        'completed': '已完成',
        'error': '出错',
        'removed': '已删除'
    }
    
    if not histories:
        return "没有历史记录"
        
    lines = []
    
    for i, history in enumerate(histories, 1):
        status = status_map.get(history['status'], history['status'])
        name = truncate_filename(history.get('name', '未知'), max_length)
        gid = history.get('gid', '未知')
        datetime_str = history.get('datetime', '')
        
        line = [f"{i}. <b>{escape_html(name)}</b>"]
        line.append(f"[<code>{gid}</code>]")
        line.append(f"({status})")
        
        if datetime_str:
            line.append(f"- {datetime_str}")
            
        if history.get('status') == 'error' and history.get('error_message'):
            error_msg = truncate_filename(history['error_message'], 50)
            line.append(f"\n   <i>错误: {escape_html(error_msg)}</i>")
            
        lines.append(" ".join(line))
    
    return "\n".join(lines)

def create_pagination_keyboard(
    current_page: int, 
    total_pages: int, 
    callback_prefix: str,
    show_first_last: bool = True
) -> InlineKeyboardMarkup:
    """
    创建分页按钮
    
    Args:
        current_page: 当前页码
        total_pages: 总页数
        callback_prefix: 回调数据前缀
        show_first_last: 是否显示第一页/最后一页按钮
        
    Returns:
        InlineKeyboardMarkup 对象
    """
    keyboard = []
    buttons = []
    
    # 显示当前页码信息
    page_info = f"第 {current_page}/{total_pages} 页"
    buttons.append(InlineKeyboardButton(page_info, callback_data="page_info"))
    
    # 如果只有一页，不显示翻页按钮
    if total_pages <= 1:
        keyboard.append(buttons)
        return InlineKeyboardMarkup(keyboard)
    
    # 清空按钮重新排列
    buttons = []
    
    # 首页按钮
    if show_first_last and current_page > 2:
        buttons.append(InlineKeyboardButton("« 首页", callback_data=f"{callback_prefix}:1"))
    
    # 上一页按钮
    if current_page > 1:
        buttons.append(InlineKeyboardButton("< 上一页", callback_data=f"{callback_prefix}:{current_page - 1}"))
    
    # 页码信息
    buttons.append(InlineKeyboardButton(f"{current_page}/{total_pages}", callback_data="page_info"))
    
    # 下一页按钮
    if current_page < total_pages:
        buttons.append(InlineKeyboardButton("下一页 >", callback_data=f"{callback_prefix}:{current_page + 1}"))
    
    # 末页按钮
    if show_first_last and current_page < total_pages - 1:
        buttons.append(InlineKeyboardButton("末页 »", callback_data=f"{callback_prefix}:{total_pages}"))
    
    keyboard.append(buttons)
    return InlineKeyboardMarkup(keyboard)

def create_task_control_keyboard(gid: str) -> InlineKeyboardMarkup:
    """
    创建任务控制按钮
    
    Args:
        gid: 任务 GID
        
    Returns:
        InlineKeyboardMarkup 对象
    """
    keyboard = [
        [
            InlineKeyboardButton("⏸ 暂停", callback_data=f"pause:{gid}"),
            InlineKeyboardButton("▶️ 继续", callback_data=f"resume:{gid}"),
            InlineKeyboardButton("❌ 删除", callback_data=f"remove:{gid}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def calculate_total_pages(total_items: int, items_per_page: int) -> int:
    """
    计算总页数
    
    Args:
        total_items: 总项目数
        items_per_page: 每页项目数
        
    Returns:
        总页数
    """
    return max(1, math.ceil(total_items / items_per_page))

def parse_callback_data(callback_data: str) -> Tuple[str, str]:
    """
    解析回调数据
    
    Args:
        callback_data: 回调数据字符串 (格式: "action:value")
        
    Returns:
        (action, value) 元组
    """
    parts = callback_data.split(":", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], ""