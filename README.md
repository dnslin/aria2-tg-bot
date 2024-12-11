# Aria2 Telegram Bot

这是一个基于 Telegram Bot 的下载工具，支持 HTTP、磁力链接和种子文件下载。

## 环境要求

- Python 3.13
- aria2 (需要单独安装)

## 安装步骤

1. 安装 aria2:
```bash
wget -N git.io/aria2.sh && chmod +x aria2.sh && bash aria2.sh
```

2. 创建虚拟环境:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
.\venv\Scripts\activate  # Windows
```

3. 安装依赖:
```bash
pip install -r requirements.txt
```

4. 配置环境变量:
创建 `.env` 文件并添加以下内容：
```
TELEGRAM_BOT_TOKEN=你的bot token
TELEGRAM_API_BASE=https://tg.dnsl.in/  # 可选，自定义Telegram API地址
ARIA2_HOST=http://localhost
ARIA2_PORT=6800
ARIA2_SECRET=你的aria2密钥
```

5. 运行机器人:
```bash
python bot.py
```

## 功能

- 支持 HTTP/HTTPS 链接下载
- 支持磁力链接下载
- 支持种子文件下载
- 实时显示下载进度
- 下载完成通知
- 支持自定义 Telegram API 代理地址 