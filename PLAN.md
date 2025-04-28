# Aria2 Telegram Bot - 开发计划

## 1. 项目目标

开发一个功能全面的异步 Telegram 机器人，使用 `python-telegram-bot` (v22+) 和 `aria2p`，通过 Aria2 JSON-RPC 接口管理下载任务，并提供配置管理、访问控制、任务历史记录（SQLite）、分页显示和下载完成/失败通知功能。

## 2. 技术选型

*   **核心库:** `python-telegram-bot[ext]` (v22+)
*   **Aria2 交互:** `aria2p`
*   **配置:** `PyYAML` 用于解析 `config.yaml`
*   **历史记录:** `sqlite3` (标准库)
*   **异步任务调度 (通知):** `apscheduler`
*   **日志:** `logging` (标准库)

## 3. 项目结构 (建议)

```mermaid
graph TD
    subgraph "Root Directory (aria2-bot)"
        A[main.py] -- Runs --> B;
        C[config.yaml] -- Loaded by --> D;
        E[requirements.txt];
        F[README.md];
        G[bot_data/] -- Contains --> H(history.db);
        I[src/] -- Contains --> J & K & L & M & N;
    end

    subgraph "src/ (Source Code)"
        J(config.py) -- Manages --> C;
        K(aria2_client.py) -- Interacts with Aria2 --> O(Aria2 RPC);
        L(history.py) -- Manages --> H;
        M(bot.py) -- Core Bot Logic --> J & K & L & N;
        N(utils.py) -- Helpers (Formatting, Pagination, etc.);
    end

    B(Telegram Bot Application) -- Uses --> M;

    style H fill:#f9f,stroke:#333,stroke-width:2px
    style C fill:#ccf,stroke:#333,stroke-width:2px
```

*   `main.py`: 程序入口，初始化配置、日志、Aria2 客户端、历史数据库、调度器，并启动 Telegram Bot Application。
*   `config.yaml`: 存储所有配置信息（Bot Token, Aria2 连接参数, 授权 ID 列表, 数据库路径, 通知设置等）。
*   `requirements.txt`: 列出所有 Python 依赖。
*   `README.md`: 项目说明、安装、配置和使用指南。
*   `bot_data/`: 存放持久化数据，如 SQLite 数据库。
*   `src/config.py`: 加载、验证和提供对 `config.yaml` 配置的访问。
*   `src/aria2_client.py`: 封装 `aria2p` 的异步调用，处理 Aria2 连接和 RPC 交互，定义相关异常。
*   `src/history.py`: 使用 `sqlite3` 管理 `history.db`，提供添加、查询（带分页）、清理历史记录的异步接口，以及数据库初始化和表结构定义。
*   `src/bot.py`: 包含 Telegram Bot 的核心逻辑：
    *   命令处理器 (`CommandHandler`) 实现 `/add`, `/status`, `/pause`, `/unpause`, `/remove`, `/pauseall`, `/unpauseall`, `/history`, `/clearhistory`, `/help`, `/globalstatus`。
    *   回调查询处理器 (`CallbackQueryHandler`) 处理内联键盘按钮（任务操作、分页）。
    *   访问控制逻辑（检查用户/群组 ID）。
    *   错误处理器 (`ErrorHandler`)。
    *   集成 `apscheduler` 实现下载完成/失败通知的调度任务。
*   `src/utils.py`: 包含辅助函数，如消息格式化（MarkdownV2/HTML）、分页逻辑实现、GID 验证等。

## 4. 开发阶段与任务分解

*   **阶段 1: 基础设置与配置**
    *   [ ] 创建项目目录结构。
    *   [ ] 初始化 Git 仓库 (可选)。
    *   [ ] 编写 `requirements.txt` 并安装依赖。
    *   [ ] 设计 `config.yaml` 结构，包含所有必要字段。
    *   [ ] 实现 `src/config.py`，加载并验证配置。
    *   [ ] 设置基础日志记录 (`logging` in `main.py`)。

*   **阶段 2: Aria2 客户端封装**
    *   [ ] 在 `src/aria2_client.py` 中初始化 `aria2p.API`。
    *   [ ] 封装常用的 Aria2 RPC 调用为异步函数（如 `add_download`, `get_task_status`, `get_active_tasks`, `pause_task`, `remove_task`, etc.）。
    *   [ ] 定义并处理 Aria2 连接和调用相关的异常。

*   **阶段 3: 历史记录管理 (SQLite)**
    *   [ ] 在 `src/history.py` 中定义 SQLite 数据库表结构 (`tasks`: gid, filename, status, timestamp, size, error_msg)。
    *   [ ] 实现数据库初始化函数。
    *   [ ] 实现添加历史记录的异步函数。
    *   [ ] 实现查询历史记录的异步函数（支持分页，每页 5 条）。
    *   [ ] 实现清理历史记录的异步函数。
    *   [ ] 实现自动修剪旧记录的逻辑（例如，只保留最新的 100 条）。

*   **阶段 4: Telegram Bot 核心与命令实现**
    *   [ ] 在 `src/bot.py` 中初始化 `telegram.ext.Application`。
    *   [ ] 实现访问控制检查逻辑。
    *   [ ] 实现 `/start` 和 `/help` 命令处理器。
    *   [ ] 实现 `/add` 命令处理器，调用 `aria2_client`。
    *   [ ] 实现 `/status` (带 GID) 命令处理器，调用 `aria2_client`，格式化输出，添加内联键盘。
    *   [ ] 实现 `/pause`, `/unpause`, `/remove` 命令处理器，调用 `aria2_client`。
    *   [ ] 实现 `/pauseall`, `/unpauseall` 命令处理器，调用 `aria2_client`。
    *   [ ] 实现 `/globalstatus` 命令处理器，调用 `aria2_client`。
    *   [ ] 实现 `/history` 命令处理器，调用 `history` 模块，实现分页逻辑（可能需要 `ConversationHandler` 或状态管理），添加分页按钮。
    *   [ ] 实现 `/clearhistory` 命令处理器，添加确认步骤，调用 `history` 模块。
    *   [ ] 实现 `CallbackQueryHandler` 处理内联按钮点击（任务操作、分页）。
    *   [ ] 实现基础的 `ErrorHandler`。

*   **阶段 5: 下载通知功能**
    *   [ ] 在 `src/bot.py` 或 `main.py` 中初始化 `apscheduler.AsyncIOScheduler`。
    *   [ ] 设计一个检查下载状态的异步任务函数。
    *   [ ] 该任务函数调用 `aria2_client.tellStopped` 获取最近停止的任务。
    *   [ ] 对比 `history.db`，识别新完成或出错的任务。
    *   [ ] 对于新任务，调用 `aria2_client.tellStatus` 获取详情，添加到 `history.db`。
    *   [ ] 向配置中指定的用户发送格式化的通知消息。
    *   [ ] 添加逻辑防止重复通知（例如，在 history 表中增加 `notified` 字段）。
    *   [ ] 在 `main.py` 中调度此任务定期执行（例如，每 30-60 秒）。

*   **阶段 6: 完善与测试**
    *   [ ] 完善错误处理，覆盖更多边界情况。
    *   [ ] 优化日志记录，添加更多有用的信息。
    *   [ ] 编写 `README.md`。
    *   [ ] 进行全面的功能测试和集成测试。
    *   [ ] 代码审查和重构 (可选)。

## 5. 下一步行动

*   **确认计划:** (已完成)
*   **保存计划:** (已完成)
*   **开始实施:** 确认计划保存后，切换到 "Code" 模式开始实施。