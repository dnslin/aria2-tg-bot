# Aria2 Bot 用户体验优化计划

**核心目标：**

1.  **实时进度展示**：用户添加任务后，在回复的消息中动态更新下载进度、速度、ETA 等信息。
2.  **便捷任务交互**：用户添加任务后，在回复的消息中直接提供内联按钮（暂停、恢复、删除）进行操作，无需手动输入 GID。

**详细计划：**

1.  **引入任务监控器 (`TaskMonitor`)**:
    *   **目的**: 跟踪需要实时更新进度的活动任务及其对应的 Telegram 消息。
    *   **实现方式**: 创建一个新的模块（例如 `src/task_monitor.py`）或在 `bot_app.py` 中实现。
    *   **核心组件**:
        *   一个存储结构（推荐使用 `application.bot_data` 中的字典）来保存活动监控任务，键可以是 `(chat_id, message_id)`，值可以是 `gid` 或包含 `gid` 和其他状态的字典。例如：`bot_data['active_monitors'] = {(chat_id, message_id): gid, ...}`。
        *   一个后台 `asyncio` 任务（在 `main.py` 或 `bot_app.py` 中启动），该任务每隔 5 秒执行一次更新检查。

2.  **修改 `cmd_add` 处理器 (`src/handlers/command_handlers.py`)**:
    *   在 `aria2_client.add_download(url)` 成功并获取 `gid` 后：
        *   调用 `aria2_client.get_download(gid)` 获取初始任务信息。
        *   调用 `utils.format_task_info_html(task_info)` 格式化初始状态文本。
        *   调用 `utils.create_task_control_keyboard(gid)` 创建内联按钮。
        *   使用 `message.edit_text` 更新 "正在添加..." 的消息，显示初始状态文本和内联按钮。
        *   **新增**: 将 `(chat_id, message_id, gid)` 注册到 `TaskMonitor` 中，启动该任务的实时更新。`message_id` 可以从 `message.message_id` 获取，`chat_id` 从 `update.effective_chat.id` 获取。

3.  **实现 `TaskMonitor` 的更新逻辑**:
    *   后台任务每 5 秒执行以下操作：
        *   获取 `bot_data['active_monitors']` 中的所有监控项。
        *   **并发查询**: 使用 `asyncio.gather` 或类似机制并发地为所有需要监控的 `gid` 调用 `aria2_client.get_download(gid)`。
        *   **处理结果**:
            *   **任务进行中 (active/paused)**:
                *   获取最新的 `task_info`。
                *   调用 `utils.format_task_info_html(task_info)` 生成新的消息文本。
                *   **优化**: 比较新旧文本，仅在文本内容实际改变时才调用 `application.bot.edit_message_text` 更新消息，以减少不必要的 API 调用和避免 Telegram 的 "Message is not modified" 错误。
                *   更新时需传入 `chat_id`, `message_id`, 新文本, 以及 `reply_markup=utils.create_task_control_keyboard(gid)` 来保持按钮。
                *   **错误处理**: 捕获 `telegram.error.RetryAfter` 并等待指定时间；捕获 `telegram.error.BadRequest` (例如消息被删除或无法编辑)，记录日志并从监控器中移除该任务。
            *   **任务结束 (complete/error/removed)**:
                *   获取最终的 `task_info`。
                *   调用 `utils.format_task_info_html(task_info)` 生成最终状态文本。
                *   调用 `application.bot.edit_message_text` 做最后一次更新，显示最终状态，并将 `reply_markup` 设置为 `None` 或空的 `InlineKeyboardMarkup()` 以移除按钮。
                *   从 `bot_data['active_monitors']` 中移除该任务的监控项。

4.  **修改回调处理器 (`src/handlers/callback_handlers.py`)**:
    *   在 `_handle_remove_callback` 函数中，当任务被成功移除后，除了更新消息文本，还需要确保从 `bot_data['active_monitors']` 中移除对应的监控项。
    *   `_handle_pause_callback` 和 `_handle_resume_callback` 不需要修改监控状态，因为监控器会在下次轮询时获取到新的状态并更新消息。

5.  **状态持久化 (可选但推荐)**:
    *   当前的 `bot_data` 是内存中的。如果 Bot 重启，所有监控状态都会丢失。
    *   可以考虑在 Bot 启动时，从 Aria2 获取所有活动任务，并尝试找到可能与之关联的消息（这比较困难，可能需要额外的持久化存储）。
    *   或者，在 Bot 关闭时，将 `active_monitors` 的状态保存到文件或数据库中，并在启动时加载。

**流程图 (Mermaid):**

```mermaid
sequenceDiagram
    participant User
    participant TelegramBot
    participant CommandHandler (cmd_add)
    participant Aria2Client
    participant TaskMonitor
    participant Utils
    participant CallbackHandler

    User->>TelegramBot: /add <url>
    TelegramBot->>CommandHandler: handle /add
    CommandHandler->>TelegramBot: Send "Adding..." (message_id: M1, chat_id: C1)
    CommandHandler->>Aria2Client: add_download(url)
    Aria2Client-->>CommandHandler: return gid
    CommandHandler->>Aria2Client: get_download(gid) (initial status)
    Aria2Client-->>CommandHandler: return task_info
    CommandHandler->>Utils: format_task_info_html(task_info)
    Utils-->>CommandHandler: return formatted_text
    CommandHandler->>Utils: create_task_control_keyboard(gid)
    Utils-->>CommandHandler: return keyboard
    CommandHandler->>TelegramBot: edit_message_text(C1, M1, formatted_text, keyboard)
    CommandHandler->>TaskMonitor: Register task (C1, M1, gid)

    activate TaskMonitor
    loop Every 5 seconds
        TaskMonitor->>TaskMonitor: Get monitored tasks [(C1, M1, G1), ...]
        TaskMonitor->>Aria2Client: get_download(G1) (concurrently for all GIDs)
        Aria2Client-->>TaskMonitor: return task_info_updated
        alt Task is active/paused
            TaskMonitor->>Utils: format_task_info_html(task_info_updated)
            Utils-->>TaskMonitor: return new_formatted_text
            TaskMonitor->>TaskMonitor: Compare new_formatted_text with previous
            opt Text Changed
                 TaskMonitor->>Utils: create_task_control_keyboard(G1)
                 Utils-->>TaskMonitor: return keyboard
                 TaskMonitor->>TelegramBot: edit_message_text(C1, M1, new_formatted_text, keyboard)
            end
        else Task is finished (complete/error/removed)
            TaskMonitor->>Utils: format_task_info_html(task_info_updated)
            Utils-->>TaskMonitor: return final_text
            TaskMonitor->>TelegramBot: edit_message_text(C1, M1, final_text, reply_markup=None) # Remove keyboard
            TaskMonitor->>TaskMonitor: Unregister task (C1, M1, G1)
        end
    end
    deactivate TaskMonitor

    User->>TelegramBot: Click "Remove" button on M1 (callback_data: remove:G1)
    TelegramBot->>CallbackHandler: handle callback(remove:G1)
    CallbackHandler->>Aria2Client: remove_download(G1)
    Aria2Client-->>CallbackHandler: return success
    CallbackHandler->>TelegramBot: edit_message_text(C1, M1, "Task removed...", reply_markup=None)
    CallbackHandler->>TaskMonitor: Unregister task (C1, M1, G1) # Ensure monitor stops