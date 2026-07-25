# AI Smart Glass

基于 ESP32 与 Qt/C++ 的 AI 智能眼镜桌面客户端。

---

## 系统架构

```
ESP32 (眼镜) ──BLE──→ Python 桥接 ──WebSocket──→ Qt 桌面端
 拍照/录音              ble_bridge.py             照片显示/AI分析/截图保存
```

---

## 功能

- 🔗 **BLE 蓝牙直连**：无需浏览器，Qt 自动连接眼镜
- 📸 **实时预览**：照片自动显示在 Qt 桌面窗口
- 💾 **一键截图**：随时保存当前画面
- 🤖 **AI 识图**：Ollama 本地视觉模型 + DeepSeek 云端问答
- 📁 **照片管理**：截图统一保存至 `photos/` 目录

---

## 硬件要求

| 组件 | 型号 |
|------|------|
| 主控 | Seeed Studio XIAO ESP32S3 Sense |
| 电池 | EEMB LP502030 3.7V 250mAh |
| 支架 | 3D 打印眼镜支架 |

---

## 快速开始

### 1. 安装依赖

- Python 3.11+ + `bleak` `websockets`
- Qt 6.8+ (MinGW 64-bit + Qt Connectivity 模块)
- Ollama (本地 AI 视觉模型)

```bash
pip install bleak websockets
ollama pull moondream:1.8b-v2-fp16
```

### 2. 烧录固件

用 Arduino IDE 打开 `firmware/firmware.ino`，设置 **PSRAM: OPI PSRAM**，上传至 XIAO ESP32S3。

### 3. 运行 Qt 桌面端

Qt Creator 打开 `QtGlassDemo/QtGlassDemo.pro` → 编译运行。

Qt 会自动拉起 BLE 桥接，连接眼镜后即可显示照片。

---

## 项目结构

```
├── firmware/                # ESP32 固件 (Arduino)
│   ├── firmware.ino
│   └── readme.md
├── sources/                 # Web 端源码 (React Native / 调试用)
│   ├── agent/               # AI 代理
│   ├── app/                 # 界面组件
│   └── modules/             # AI 模块 (Ollama/DeepSeek/OpenAI)
├── QtGlassDemo/             # Qt 桌面端 (主力)
│   ├── mainwindow.h/cpp     # 主窗口 + WebSocket 服务器
│   ├── ble_bridge.py        # BLE 蓝牙桥接 (Python)
│   ├── scan_test.py         # BLE 扫描测试工具
│   └── ble_test.py          # BLE 连接测试工具
└── photos/                  # 截图保存目录
```

---

## 团队协作

```bash
git clone git@github.com:openglass-team/ai-smartGlass.git
git checkout -b feature/你的模块名
```

分支命名：`feature/firmware` `feature/ai` `feature/qt` `feature/hardware`

---

## License

MIT
