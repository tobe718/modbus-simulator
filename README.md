# Modbus Slave 模拟器

基于 **Python + PySide6 + pymodbus** 的 Modbus Slave 模拟器，支持在一个 GUI 内同时运行多个 slave、自定义寄存器布局、模拟响应延迟、并以可过滤的结构化日志观察收发行为。

## 功能特性

- 支持 4 类寄存器配置：
  - `0xxxx` Coils（线圈）
  - `1xxxx` Discrete Inputs（离散输入）
  - `3xxxx` Input Registers（输入寄存器）
  - `4xxxx` Holding Registers（保持寄存器）
- 每一类寄存器的**数量**可独立配置，寄存器初值可在表格中直接编辑
- 支持**多 slave**，每个 slave 绑定不同 TCP 端口，端口从 `起始端口 (offset)` 依次递增
- 支持**响应延迟**（毫秒），每个 slave 独立设置
- 协议帧格式可在 **Modbus TCP** 与 **Modbus RTU over TCP** 间全局切换
- 集成结构化日志窗体：
  - 等级：`DEBUG / INFO / WARNING / ERROR`
  - 每条日志带 `slave=<id>` 与 `port=<port>` 上下文
  - 支持按等级与 slave 过滤、染色、清空与导出

## 安装

建议使用 Python 3.10+：

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

## 运行

```bash
python run.py
```

或者作为模块运行：

```bash
python -m src.main
```

## 使用说明

1. 在左侧 **全局配置** 面板中：
   - 选择协议帧格式（默认 Modbus TCP）
   - 设置 `起始端口` 与 `Slave 数量`
   - 设置四类寄存器的默认数量、默认响应延迟
   - 点击 **应用配置**，右侧将生成对应数量的 Slave 配置页
2. 切到右侧每个 Slave 标签页，按需覆盖该 slave 的 `Unit ID`、`响应延迟` 以及四类寄存器的数量和初值
3. 点击 **启动全部**，模拟器会为每个 slave 在独立线程里创建 TCP 监听
4. 下方日志窗体可按等级 / 按 slave 过滤；点击 **导出...** 将当前缓存日志保存到文件
5. 点击 **停止全部** 结束监听，即可再次修改配置

## 项目结构

```
modbus-simulator/
├── requirements.txt
├── README.md
├── run.py
└── src/
    ├── main.py                     # 应用入口
    ├── core/
    │   ├── slave_config.py         # SlaveConfig / FramerMode / RegisterType
    │   ├── log_bus.py              # 日志总线 (QtLogHandler, LoggerAdapter)
    │   ├── delayed_datastore.py    # 带延迟与日志的 DataBlock
    │   └── server_manager.py       # 多线程 + asyncio 启停 slaves
    └── gui/
        ├── main_window.py          # 主窗口
        ├── global_config.py        # 全局配置面板
        ├── slave_tab.py            # 单 slave 配置页（寄存器表格）
        └── log_panel.py            # 日志显示窗体
```

## 设计要点

- **并发模型**：每个 slave 运行在独立的 `threading.Thread` 中，线程内用自己的 `asyncio` 事件循环驱动 `pymodbus.server.ModbusTcpServer`。这样 slave A 的 `time.sleep(delay)` 不会影响 slave B。
- **延迟注入**：通过 `DelayedDataBlock` 覆盖 `getValues` / `setValues`，在数据存取路径注入 `time.sleep`，对 Modbus 所有读写功能码生效。
- **RTU over TCP**：仅改变 pymodbus 的 framer（`FramerType.RTU`），底层仍是 TCP 套接字。客户端必须发送带 CRC16 的 RTU 帧，普通 Modbus TCP 客户端不兼容。
- **日志系统**：统一写入 Python `logging`，通过自定义 `QtLogHandler` 将记录以结构化对象跨线程派发到 UI。`LoggerAdapter` 自动在每条日志中注入 `slave_id` / `port` / `category`。

## 注意事项

- Windows 下绑定 502 等低端口需要管理员权限，默认起始端口为 `5020`
- `RTU over TCP` 不是 Modbus 官方标准，常见于嵌入式网关的遗留部署
- 大量寄存器（> 几千）时请降低日志等级至 `INFO` 及以上，避免 UI 刷新压力
