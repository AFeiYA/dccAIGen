---
title: "Module 13: Pydantic 强类型数据契约与参数校验完全指南"
tags:
  - Python
  - Pydantic
  - DataValidation
  - StructuredOutputs
  - ToolCalling
  - GamePipeline
  - TechArt
created: 2026-09-04
module: 13
aliases:
  - Pydantic完全指南
  - 强类型数据契约
  - 结构化输出
  - Schema定义
status: in-progress
---

# Module 13: Pydantic V2 核心讲义与实战手册

> [!summary] 核心学习目标 (Learning Objectives)
> 1. **为什么 Pydantic 是现代 AI 与 Web 的基石**：搞清楚动态类型 Python 在生产环境中如何通过 Pydantic 获得 Rust 级别（pydantic-core）的高性能数据校验。
> 2. **精通基础类型与 Field 约束**：使用 `Field(...)` 添加业务级约束（最小值、最大值、字符串长度、正则正则模式、字段注释）。
> 3. **熟练运用两级校验器**：
>    - `@field_validator`：针对单个字段的值进行深度清洗与校验；
>    - `@model_validator`：跨字段联合校验（如：如果软件是 UE5，则节点属性必须符合 Unreal 规则）。
> 4. **掌握计算字段与嵌套模型**：
>    - `@computed_field`：动态计算属性并支持直接序列化入 JSON；
>    - **嵌套模型 (Nested Models)** 与 **自引用模型 (Self-referencing Models)**：定义层级树状结构（场景节点树）。
> 5. **终极交付——大模型结构化输出 (Structured Outputs)**：
>    - 掌握 `model_dump()` 与 `model_dump_json()`；
>    - 掌握 `Model.model_json_schema()`，这是喂给 OpenAI / Ollama 实现 **100% 格式不崩塌的 Function Calling** 的终极武器！

---

## 1. 为什么 Pydantic 改变了 Python 生态？

传统的 Python 字典（`dict`）在做管线工具和传递参数时存在巨大隐患：
- 字段名写错（如 `pos_x` 错写成 `posX`）不会报错，直到运行时崩溃；
- 类型不可控：模型可能把数值 `3.14` 当成字符串 `"3.14"` 返回；
- 缺少自动清洗（Coercion）与自解释文档。

> [!tip] Pydantic 的定位：Parse, don't validate!
> Pydantic 的底层核心是 **Rust 编写的 `pydantic-core`**，速度极快。它不仅负责校验（报错），更核心的是**数据解析与强制转换（Type Coercion）**。传入字符串 `"123"`，它会自动转为整型 `123`！

---

## 2. 基础模型与 Field 约束定义

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal

class DCCNodeBase(BaseModel):
    # Literal 限制取值范围只能是这三者之一
    software: Literal["Houdini", "UnrealEngine", "Maya"] = Field(
        ..., description="目标运行的 DCC 软件名称"
    )
    node_name: str = Field(
        ..., min_length=2, max_length=50, description="场景节点唯一标识名称"
    )
    subdivision_level: int = Field(
        default=0, ge=0, le=5, description="细分级别 (0 到 5 之间)"
    )
    is_active: bool = Field(default=True, description="是否启用该节点")
    comment: Optional[str] = Field(default=None, description="可选注释信息")
```

---

## 3. 单字段校验 (`@field_validator`) 与多字段联合校验 (`@model_validator`)

### 3.1 字段级校验：清洗与格式强制
例如在游戏管线中，资产命名必须全小写，且不能包含空格：

```python
from pydantic import BaseModel, field_validator

class AssetExportRequest(BaseModel):
    asset_name: str
    export_format: str

    @field_validator("asset_name")
    @classmethod
    def validate_asset_name(cls, v: str) -> str:
        v = v.strip().lower()
        if " " in v:
            raise ValueError("资产名称中不得包含空格！")
        return v

    @field_validator("export_format")
    @classmethod
    def check_supported_format(cls, v: str) -> str:
        allowed = ["fbx", "usd", "abc", "obj"]
        if v.lower() not in allowed:
            raise ValueError(f"不支持的导出格式 {v}，仅支持 {allowed}")
        return v.lower()
```

### 3.2 模型级校验：跨字段逻辑互斥与联动
例如：如果导出格式是 `fbx`，则不能勾选“导出为体积点云”选项：

```python
from pydantic import BaseModel, model_validator

class ComplexPipelineTask(BaseModel):
    format: str
    include_volumes: bool

    @model_validator(mode="after")
    def check_cross_fields(self):
        if self.format == "fbx" and self.include_volumes:
            raise ValueError("FBX 格式不支持直接导出体积(Volume)数据，请使用 VDB 或 USD 格式！")
        return self
```

---

## 4. 计算属性 (`@computed_field`)

有时候某些字段并不需要外部传入，而是**由已有字段自动计算合成**出来的，同时我们又希望它能**出现在导出的 JSON 里**：

```python
from pydantic import BaseModel, computed_field

class UE5MaterialConfig(BaseModel):
    category: str  # 例如: "Character"
    mat_name: str  # 例如: "M_Skin_01"

    @computed_field
    @property
    def unreal_package_path(self) -> str:
        """自动推导完整的 UE5 虚幻引擎资产引用路径"""
        return f"/Game/Materials/{self.category}/{self.mat_name}.{self.mat_name}"
```

---

## 5. 复杂层级：嵌套模型 (Nested Models) 与 节点树自引用

游戏 DCC 场景是典型的**层级树状结构**（Parent -> Children）。Pydantic 完全原生支持嵌套定义与自引用：

```python
from __future__ import annotations  # 支持类型自引用
from pydantic import BaseModel, Field
from typing import List, Optional

class Vector3D(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

class SceneNode(BaseModel):
    name: str
    type: str
    transform: Vector3D = Field(default_factory=Vector3D)
    children: List[SceneNode] = Field(default_factory=list, description="子节点列表")
```

---

## 6. 核心输出：序列化与与大模型对接（JSON Schema）

大模型之所以能做到**“100% 听话地输出我们想要的数据结构”**，秘诀就在于这行代码：

```python
# 1. 导出为 Python 字典
data_dict = node.model_dump()

# 2. 导出为标准 JSON 字符串
json_str = node.model_dump_json(indent=2)

# 3. 终极武器：导出给 OpenAI / Ollama 的 Schema 契约！
schema_for_llm = SceneNode.model_json_schema()
```

将 `schema_for_llm` 注入 Prompt 或直接传入 OpenAI 的 `response_format={"type": "json_object"}`，大模型便绝对不可能给出多余的废话或缺失字段！

---

## 7. 关联双向链接 (Obsidian Links)
- [[12-Asyncio-EventLoop-Concurrency|上一章：Module 12 Asyncio 异步高并发]]
- [[00-Index-Concurrency-and-Async|MOC 并发与异步知识索引]]
- [[DCC-Node-Contract-Design|DCC 节点数据契约实战]]
