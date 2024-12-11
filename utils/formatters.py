def format_progress_bar(progress: float, width: int = 10) -> str:
    """格式化进度条"""
    filled = int(width * progress / 100)
    empty = width - filled
    return "█" * filled + "░" * empty

def format_size(size: int) -> str:
    """格式化文件大小"""
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size/1024:.1f}KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size/1024/1024:.1f}MB"
    else:
        return f"{size/1024/1024/1024:.1f}GB"

def format_time(seconds: int) -> str:
    """格式化时间"""
    if hasattr(seconds, 'total_seconds'):
        # 如果是 timedelta 对象，转换为秒
        seconds = int(seconds.total_seconds())
        
    if seconds < 60:
        return f"{seconds}秒"
    elif seconds < 3600:
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes}分{seconds}秒"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        return f"{hours}时{minutes}分{seconds}秒"

def get_seconds_from_timedelta(td) -> int:
    """将timedelta转换为秒数"""
    if not td:
        return 0
    try:
        return int(td.total_seconds())
    except (AttributeError, TypeError):
        return 0 