# 重构计划：拆分 `src/bot.py`

**目标:** 将 `src/bot.py` 拆分成更小、更专注的模块，以提高代码的可读性、可维护性和可测试性。

**1. 分析与拆分原则:**

*   **单一职责原则:** 每个新的模块/文件应该只关注一块特定的功能。
*   **高内聚低耦合:** 相关的功能应该放在一起，模块之间的依赖关系应尽可能减少。
*   **可测试性:** 拆分后的模块应该更容易进行单元测试。

**2. 建议的新文件/目录结构 (在 `src/` 目录下):**

```
src/
├── __init__.py
├── aria2_client.py
├── config.py
├── history.py
├── utils.py
├── auth.py              # 新增：处理授权逻辑
├── bot_app.py           # 新增：Bot 应用核心设置与运行
├── notification_service.py # 新增：通知服务类
├── handlers/            # 新增：存放各类处理器
│   ├── __init__.py
│   ├── command_handlers.py  # 新增：处理 Telegram 命令
│   ├── callback_handlers.py # 新增：处理回调查询
│   └── conversation_handlers.py # 新增：处理会话 (如 clearhistory)
└── state/               # 新增: 管理临时状态
    ├── __init__.py
    └── page_state.py      # 新增: 管理分页状态
```

**3. 模块职责定义:**

*   **`src/bot_app.py`:**
    *   **核心职责:** 初始化 `telegram.ext.Application` 实例，设置基础配置（如 API 端点），注册来自 `handlers` 目录中的所有处理器（命令、回调、会话），启动和停止 Bot 应用。
    *   **持有依赖:** 持有 `Aria2Client` 和 `HistoryManager` 的实例，并将它们传递给需要的处理器（通过 `context.bot_data` 或其他依赖注入机制）。
    *   **可能包含:** `TelegramBot` 类（可能重命名为 `BotApplicationRunner` 或类似），包含 `setup` 和 `run` 方法。
*   **`src/auth.py`:**
    *   **核心职责:** 包含 `check_authorized` 函数，用于验证用户权限。
*   **`src/notification_service.py`:**
    *   **核心职责:** 包含 `NotificationService` 类，负责检查下载任务状态并向指定用户发送通知。
    *   **依赖:** `telegram.ext.Application` (用于发送消息), `HistoryManager` (获取未通知任务), `Config`。
*   **`src/handlers/command_handlers.py`:**
    *   **核心职责:** 包含所有处理 Telegram 命令（如 `/add`, `/status`, `/help` 等）的函数 (`cmd_*`)。
    *   **注册方式:** 这些函数需要被注册到 `Application` 中（在 `bot_app.py` 中完成）。可以考虑使用某种注册机制或直接在 `bot_app.py` 中导入并添加。
    *   **依赖:** `Update`, `ContextTypes`, `Aria2Client`, `HistoryManager`, `utils`, `auth`。
*   **`src/handlers/callback_handlers.py`:**
    *   **核心职责:** 包含处理内联键盘回调查询的函数，如任务操作（暂停、恢复、删除）和分页（历史记录、搜索结果、状态列表）。包含 `handle_callback` 和 `_handle_*_callback` 逻辑。
    *   **注册方式:** 注册为 `CallbackQueryHandler` 到 `Application` (在 `bot_app.py` 中完成)。
    *   **依赖:** `Update`, `ContextTypes`, `Aria2Client`, `HistoryManager`, `utils`, `auth`, `state.page_state`。
*   **`src/handlers/conversation_handlers.py`:**
    *   **核心职责:** 包含 `ConversationHandler` 的定义，例如当前的 `clearhistory` 流程，包括入口点、状态和 fallbacks。
    *   **注册方式:** 注册 `ConversationHandler` 到 `Application` (在 `bot_app.py` 中完成)。
    *   **依赖:** `Update`, `ContextTypes`, `HistoryManager`, `auth`。
*   **`src/state/page_state.py`:**
    *   **核心职责:** 封装和管理分页相关的状态（当前页、总页数、关联数据如搜索关键词或完整任务列表）。替代原 `TelegramBot` 类中的 `self.states` 字典。

**4. 交互与关联:**

*   `main.py` 将会初始化 `Config`, `Aria2Client`, `HistoryManager`。然后创建 `BotApplicationRunner` (来自 `bot_app.py`) 的实例，并将 `Aria2Client` 和 `HistoryManager` 注入。`main.py` 还会负责启动 `BotApplicationRunner` 和 `NotificationService` (如果启用)。
*   `bot_app.py` 会从 `handlers` 目录导入并注册所有处理器。它会将 `Aria2Client` 和 `HistoryManager` 实例放入 `context.bot_data`，供所有处理器访问。
*   `handlers/*.py` 中的处理器函数会从 `context.bot_data` 获取 `Aria2Client` 和 `HistoryManager` 实例，并调用 `utils.py`, `auth.py` 中的辅助函数。
*   `NotificationService` 会被 `main.py` 定期调用其 `check_and_notify` 方法。

**5. Mermaid 图示 (简化结构):**

```mermaid
graph TD
    subgraph main.py
        direction LR
        M_Init[初始化 Config, Aria2Client, HistoryManager] --> M_CreateBot[创建 BotApplicationRunner]
        M_CreateBot --> M_InjectDeps[注入 Aria2Client, HistoryManager]
        M_InjectDeps --> M_RunBot[运行 BotApplicationRunner.run()]
        M_Init --> M_CreateNotify[创建 NotificationService]
        M_CreateNotify --> M_RunNotify[定期调用 check_and_notify()]
    end

    subgraph src/bot_app.py [BotApplicationRunner]
        direction LR
        B_InitApp[初始化 Application] --> B_RegisterHandlers[注册 Handlers]
        B_RegisterHandlers --> B_SetBotData[设置 context.bot_data (Aria2, History)]
        B_SetBotData --> B_Run[提供 run() 方法]
    end

    subgraph src/handlers
        direction TB
        H_Commands[command_handlers.py] --> H_Deps1[依赖: Aria2, History, Utils, Auth]
        H_Callbacks[callback_handlers.py] --> H_Deps2[依赖: Aria2, History, Utils, Auth, State]
        H_Conversations[conversation_handlers.py] --> H_Deps3[依赖: History, Auth]
    end

    subgraph src/notification_service.py
        direction LR
        N_Service[NotificationService] --> N_Deps[依赖: Application, History, Config]
    end

    subgraph src/auth.py
        A_Auth[check_authorized()]
    end

    subgraph src/utils.py
        U_Utils[辅助函数]
    end

    subgraph src/aria2_client.py
        AC_Client[Aria2Client]
    end

    subgraph src/history.py
        HM_Manager[HistoryManager]
    end

    subgraph src/state/page_state.py
        S_State[分页状态管理]
    end

    M_CreateBot --> B_InitApp
    B_RegisterHandlers --> H_Commands
    B_RegisterHandlers --> H_Callbacks
    B_RegisterHandlers --> H_Conversations
    H_Commands --> A_Auth
    H_Callbacks --> A_Auth
    H_Conversations --> A_Auth
    H_Commands --> U_Utils
    H_Callbacks --> U_Utils
    H_Commands --> AC_Client
    H_Callbacks --> AC_Client
    H_Commands --> HM_Manager
    H_Callbacks --> HM_Manager
    H_Conversations --> HM_Manager
    M_CreateNotify --> N_Service
    N_Service --> HM_Manager
    H_Callbacks --> S_State

    classDef default fill:#f9f,stroke:#333,stroke-width:2px;
    classDef subgraphStyle fill:#eee,stroke:#aaa,stroke-width:1px,rx:5,ry:5;
    class main.py,src/bot_app.py,src/handlers,src/notification_service.py,src/auth.py,src/utils.py,src/aria2_client.py,src/history.py,src/state/page_state.py subgraphStyle;

```

**6. 优势:**

*   **提高可读性:** 每个文件专注于特定功能，更容易理解代码意图。
*   **提高可维护性:** 修改特定功能时，只需关注相关文件，减少对其他部分的影响。
*   **提高可测试性:** 可以更容易地对单个处理器函数或服务类进行单元测试。
*   **更好的组织:** 文件结构更清晰，便于新开发者快速上手。