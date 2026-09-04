---
title: "MOC: Python 高性能并发与异步编程总览"
tags:
  - MOC
  - Python
  - Concurrency
  - Asyncio
  - Architecture
created: 2026-09-04
---

# 📚 Python 高性能并发与异步编程知识地图 (MOC)

> 本知识图谱基于课程《Full-Stack AI with Python》的 **Module 11** 与 **Module 12** 真实教学字幕精粹提炼，专为**游戏研发管线（Pipeline TD）与 AI Agent 后端系统设计**打造。

---

## 🧭 模块导航 (Vault Links)

1. [[11-MultiThreading-Multiprocessing-GIL|📘 Module 11: 多线程、多进程与 GIL 深度讲义]]
   - 包含：并发 vs 并行理论模型、GIL 底层机理与内存引用计数、`threading.Lock`、`multiprocessing.Process`、跨进程通信 `Queue`/`Value`、DCC 主线程崩溃避坑。
2. [[12-Asyncio-EventLoop-Concurrency|📗 Module 12: Asyncio 异步编程、事件循环与生产级并发]]
   - 包含：协作式事件循环（Event Loop）、协程 `async`/`await`、`asyncio.gather`、混合多线程 `to_thread`、混合多进程 `ProcessPoolExecutor`、Daemon 线程陷阱、死锁防御、FastAPI 映射。

---

## ⚡ 核心速查表：三种并发方案终极横向决选

| 选型维度 | 多线程 (`threading`) | 多进程 (`multiprocessing`) | 异步协程 (`asyncio`) |
| :--- | :--- | :--- | :--- |
| **底层驱动** | 操作系统原生线程 | 操作系统独立进程 | **用户态单线程事件循环** |
| **内存关系** | 同进程共享内存空间 | 独立内存空间（需通过 IPC 通信） | **同线程共享上下文** |
| **受 GIL 影响** | **受严重限制**（单核轮流争抢） | **完全不受限制**（各自独立 GIL） | **不涉及 GIL 竞争**（单线程分时） |
| **开销代价** | 线程栈内存 (~8MB) + 上下文切换 | 进程重量级内存复制 + 启动慢 | **极轻量（微秒级，数万连接无压力）** |
| **最佳适用场景** | 传统带阻塞的外部 SDK 同步 I/O | **CPU 密集型重计算**（烘焙/网格/哈希） | **高并发网络 I/O、API 调用、Agent 编排** |
| **游戏/TA 代表场景** | 后台监听本地 Socket 状态 | 批量资产处理、贴图格式大批转码 | **FastAPI 服务端、多工具并行 Tool Calling** |

---

## 🚀 下一步学习建议
完成以上两个模块后，直接进入：
👉 [[13-Pydantic-Data-Validation|Module 13: Pydantic 强类型数据契约构建]]（定义你的第一个 DCC 操作 Schema）
