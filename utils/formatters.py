def format_progress_bar(progress: float, width: int = 10) -> str:
    """生成进度条，使用更短的宽度适配手机屏幕"""
    if not 0 <= progress <= 100:
        progress = 0
    filled = int(width * progress / 100)
    bar = '█' * filled + '░' * (width - filled)
    return bar

def format_size(size: float) -> str:
    """格式化文件大小"""
    if not size or size < 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def format_time(seconds: int) -> str:
    """格式化时间"""
    if not seconds or seconds < 0 or seconds > 86400 * 365:  # 超过1年或无效值
        return "计算中..."
    if seconds < 60:
        return f"{seconds}秒"
    elif seconds < 3600:
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes}分{seconds}秒"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}时{minutes}分"

def get_seconds_from_timedelta(td) -> int:
    """将timedelta转换为秒数"""
    if not td:
        return 0
    try:
        return int(td.total_seconds())
    except (AttributeError, TypeError):
        return 0 