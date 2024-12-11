from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from utils.formatters import format_size

def get_control_buttons(gid: str, is_paused: bool = False) -> InlineKeyboardMarkup:
    """获取单个下载任务的控制按钮"""
    row1 = []
    if is_paused:
        row1.append(InlineKeyboardButton("▶️ 继续", callback_data=f"resume_{gid}"))
    else:
        row1.append(InlineKeyboardButton("⏸ 暂停", callback_data=f"pause_{gid}"))
    
    row1.extend([
        InlineKeyboardButton("⏹ 停止", callback_data=f"stop_{gid}"),
        InlineKeyboardButton("🔄 重试", callback_data=f"retry_{gid}")
    ])
    
    row2 = [
        InlineKeyboardButton("🗑️ 删除", callback_data=f"delete_{gid}"),
        InlineKeyboardButton("📋 任务列表", callback_data="show_tasks")
    ]
    
    return InlineKeyboardMarkup([row1, row2])

def get_task_list_buttons() -> InlineKeyboardMarkup:
    """获取任务列表管理按钮"""
    keyboard = [
        [
            InlineKeyboardButton("⏬ 下载中", callback_data="list_active"),
            InlineKeyboardButton("⏳ 等待中", callback_data="list_waiting"),
            InlineKeyboardButton("✅ 已完成", callback_data="list_completed")
        ],
        [
            InlineKeyboardButton("⏸ 已暂停", callback_data="list_paused"),
            InlineKeyboardButton("❌ 已停止", callback_data="list_stopped")
        ],
        [
            InlineKeyboardButton("🗑️ 清空已完成", callback_data="clear_completed"),
            InlineKeyboardButton("🗑️ 清空已停止", callback_data="clear_stopped")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def format_task_list(tasks, max_tasks=10) -> str:
    """格式化任务列表，限制显示数量"""
    if not tasks:
        return "没有任务"
    
    # 限制显示的任务数量
    tasks = tasks[:max_tasks]
    
    task_lines = []
    for i, d in enumerate(tasks, 1):
        # 文件名显示在单独的一行，最多显示50个字符
        name = d.name[:50] + "..." if len(d.name) > 50 else d.name
        
        # 状态信息
        status_info = []
        if hasattr(d, 'progress'):
            status_info.append(f"{d.progress:.1f}%")
        if hasattr(d, 'download_speed') and d.download_speed > 0:
            status_info.append(f"{format_size(d.download_speed)}/s")
        if hasattr(d, 'total_length'):
            status_info.append(format_size(d.total_length))
            
        status_line = " | ".join(filter(None, status_info))
        
        # 组合任务信息
        task_lines.append(f"{i}. {name}\n   {status_line}")
    
    task_text = "\n\n".join(task_lines)
    
    # 添加任务总数信息
    total_tasks = len(tasks)
    if len(tasks) == max_tasks:
        task_text += f"\n\n共有更多任务，仅显示前 {max_tasks} 个"
    else:
        task_text += f"\n\n共有 {total_tasks} 个任务"
    
    return task_text 