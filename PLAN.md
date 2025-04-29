# Aria2 Bot 进度与文件信息问题排查计划

## 1. 问题分析

*   **问题 1: 进度条始终显示 0.0%**
    *   **代码流程**: `task_monitor.py` -> `aria2_client.get_download()` -> `aria2p` 获取进度 -> `utils.format_task_info_html()` -> `utils.format_progress()` 显示。
    *   **可能原因**:
        *   Aria2 RPC 返回的原始进度信息长时间为 0 (常见于磁力链接初始阶段)。
        *   `aria2p` 库解析或计算 `download.progress` 时出错。
        *   代码逻辑错误 (初步检查未发现)。

*   **问题 2: 文件信息显示 "文件: - N/A"**
    *   **代码流程**: `aria2_client.get_download()` -> 遍历 `download.files` -> `getattr(f, 'name', 'N/A')` / `getattr(f, 'path', 'N/A')` -> `utils.format_task_info_html()` -> `file_info.get('name', file_info.get('path', '未知'))` -> 显示。
    *   **可能原因**:
        *   Aria2 RPC 返回的 `files` 列表为空或文件对象缺少 `path`/`name` 属性 (常见于磁力链接未完成元数据下载)。
        *   `aria2p` 库解析 `files` 结构时出错。
        *   代码中使用 `getattr` 默认返回 'N/A'，最终导致显示 "- N/A"。

*   **问题 3: PIL 生成进度条图片方案评估**
    *   **结论**: 技术可行但效率低、资源消耗大、用户体验差，**强烈不推荐**。

## 2. 诊断与排查计划

```mermaid
graph TD
    A[开始排查] --> B{问题是进度0%还是文件N/A?};
    B -- 进度0% --> C[检查 Aria2 RPC 输出];
    B -- 文件N/A --> D[检查 Aria2 RPC 输出];

    C --> E{直接调用 aria2.tellStatus 查看 progress 相关字段};
    D --> F{直接调用 aria2.tellStatus 查看 files 字段};

    E --> G{字段值是否正常?};
    F --> H{files 字段是否有有效信息?};

    G -- 否 --> I[检查 Aria2 服务/任务本身];
    G -- 是 --> J[增加 aria2_client.py 日志];

    H -- 否 --> K[检查 Aria2 服务/任务本身 (元数据?)]
    H -- 是 --> L[增加 aria2_client.py 日志];

    J --> M{检查 aria2p 获取的原始值};
    L --> N{检查 aria2p 获取的原始 files 对象属性};

    M --> O[更新 aria2p 库];
    N --> P[更新 aria2p 库];

    I --> Q[解决 Aria2 问题];
    K --> R[等待元数据或解决 Aria2 问题];
    O --> S[测试问题是否解决];
    P --> T[测试问题是否解决];
    Q --> S;
    R --> T;

    S -- 是 --> U[结束];
    T -- 是 --> U;
    S -- 否 --> V[进一步分析 utils.py 格式化逻辑];
    T -- 否 --> W[进一步分析 utils.py 文件名处理逻辑];
    V --> U;
    W --> U;

```

**具体步骤:**

1.  **直接查询 Aria2 RPC**: 使用 `curl` 或类似工具调用 `aria2.tellStatus`，检查目标 GID 的 `completedLength`, `totalLength` 和 `files` 字段的原始值。
2.  **增加详细日志**:
    *   在 `src/aria2_client.py` 的 `get_download` 中记录 `aria2p` 返回的原始 `download` 对象属性（进度相关）和文件对象属性 (`vars(f)`)。
    *   在 `src/task_monitor.py` 的 `_monitor_loop` 中记录传递给 `format_task_info_html` 的 `task_info` 字典。
3.  **更新依赖库**: 尝试 `pip install --upgrade aria2p`。
4.  **代码健壮性改进 (可选)**: 优化 `utils.py` 中对 0 进度、无文件信息等特殊情况的处理和显示。

## 3. 推荐方案总结

*   **主要排查方向**: Aria2 RPC 原始输出和 `aria2p` 库行为。
*   **解决方案**: 根据排查结果修复 Aria2 问题、等待任务进行、更新 `aria2p` 或调整 `utils.py` 格式化逻辑。
*   **PIL 方案**: 放弃。