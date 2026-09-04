# -*- coding: utf-8 -*-
"""
File: dcc_contract_challenge.py
Author: AFeiYA
Date: 2026-09-04
Description: 游戏研发管线与 TA 工具链 Pydantic 强类型数据契约实战模块。
License: MIT
"""

# ==============================================================================
# 1. 标准库导入 (Standard Libraries)
# ==============================================================================
import json
import sys
from typing import Any, Dict, List, Literal, Optional

# ==============================================================================
# 2. 第三方库导入 (Third-party Libraries)
# ==============================================================================
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    computed_field,
    field_validator,
    model_validator,
)

# 确保 Windows 默认终端控制台能够正确输出 UTF-8 字符
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# ==============================================================================
# 3. 管线常量定义 (Pipeline Constants)
# ==============================================================================
DCC_SOFTWARE_TYPES = Literal["Houdini", "UnrealEngine", "Maya"]
GAME_ASSET_TYPES = Literal["StaticMesh", "Texture", "Material"]

ASSET_PREFIX_MAPPING: Dict[str, str] = {
    "StaticMesh": "SM_",
    "Texture": "T_",
    "Material": "M_",
}

UE_CATEGORY_FOLDERS: Dict[str, str] = {
    "StaticMesh": "Meshes",
    "Texture": "Textures",
    "Material": "Materials",
}


# ==============================================================================
# 4. 空间与几何变换契约模型 (Spatial & Transform Models)
# ==============================================================================
class Vector3D(BaseModel):
    """三维向量，用于控制 DCC 软件中的位置、旋转与缩放。"""

    x: float = Field(default=0.0, description="X 轴空间坐标")
    y: float = Field(default=0.0, description="Y 轴空间坐标")
    z: float = Field(default=0.0, description="Z 轴空间坐标")


class Transform(BaseModel):
    """场景空间变换属性集合。"""

    translation: Vector3D = Field(default_factory=Vector3D, description="空间位移")
    rotation: Vector3D = Field(default_factory=Vector3D, description="欧拉旋转角 (度)")
    scale: Vector3D = Field(
        default_factory=lambda: Vector3D(x=1.0, y=1.0, z=1.0),
        description="三轴缩放比例 (默认 1.0)",
    )

    @field_validator("scale")
    @classmethod
    def validate_scale_non_zero(cls, value: Vector3D) -> Vector3D:
        """校验缩放分量不得为 0，防止模型在渲染管线中发生奇异退化。"""
        if value.x == 0.0 or value.y == 0.0 or value.z == 0.0:
            raise ValueError("缩放分量 (Scale) 不得为 0，否则会导致几何体退化！")
        return value


# ==============================================================================
# 5. 核心管线资产操作契约 (GameAssetSchema)
# ==============================================================================
class GameAssetSchema(BaseModel):
    """大模型向 DCC 软件下发资产创建、属性修改与导入指令的核心契约模型。"""

    software: DCC_SOFTWARE_TYPES = Field(
        ..., description="目标运行的 DCC 软件平台 (Houdini/UnrealEngine/Maya)"
    )
    asset_type: GAME_ASSET_TYPES = Field(
        ..., description="游戏资产类型 (StaticMesh/Texture/Material)"
    )
    asset_name: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="资产唯一命名，需遵循工作室前缀命名规范",
    )
    format: str = Field(
        ..., description="资产文件格式，如 fbx, usd, png, tga, bgeo"
    )

    # 可选管线配置字段
    lod_level: int = Field(
        default=0, ge=0, le=4, description="LOD 细节层次级别 (范围 0~4)"
    )
    max_resolution: Optional[int] = Field(
        default=None, description="贴图最大分辨率限制 (仅贴图资产可用，如 1024, 2048, 4096)"
    )
    transform: Transform = Field(
        default_factory=Transform, description="资产场景空间变换参数"
    )
    custom_attributes: Dict[str, Any] = Field(
        default_factory=dict, description="额外自定义元数据字典"
    )

    # --------------------------------------------------------------------------
    # 单字段校验器 (@field_validator)
    # --------------------------------------------------------------------------
    @field_validator("asset_name")
    @classmethod
    def validate_asset_name(cls, value: str) -> str:
        """清洗资产命名并剔除空格。"""
        cleaned_value = value.strip()
        if " " in cleaned_value:
            raise ValueError(f"资产名称不得包含空格: '{cleaned_value}'")
        return cleaned_value

    @field_validator("format")
    @classmethod
    def normalize_format(cls, value: str) -> str:
        """归一化文件格式扩展名 (转为小写并剔除点号)。"""
        return value.strip().lower().lstrip(".")

    # --------------------------------------------------------------------------
    # 跨字段联合校验器 (@model_validator)
    # --------------------------------------------------------------------------
    @model_validator(mode="after")
    def validate_cross_field_rules(self) -> "GameAssetSchema":
        """跨字段联合业务规则校验。"""
        # 规则 1：前缀强约束校验
        expected_prefix = ASSET_PREFIX_MAPPING.get(self.asset_type)
        if expected_prefix and not self.asset_name.startswith(expected_prefix):
            raise ValueError(
                f"命名规范违规: {self.asset_type} 类别的资产名称必须以 '{expected_prefix}' 开头，当前输入为 '{self.asset_name}'！"
            )

        # 规则 2：参数适用范围互斥校验
        if self.asset_type == "StaticMesh" and self.max_resolution is not None:
            raise ValueError("参数互斥: 静态网格体 (StaticMesh) 不得配置 max_resolution 贴图分辨率参数！")

        if self.asset_type == "Texture" and self.max_resolution is None:
            raise ValueError("参数缺失: 贴图资产 (Texture) 必须指定 max_resolution 分辨率 (如 2048)！")

        # 规则 3：DCC 软件平台特性兼容校验
        if self.software == "UnrealEngine" and self.format in ["bgeo", "vdb"]:
            raise ValueError(
                f"平台不支持: Unreal Engine 原生管线不支持直接加载 .{self.format} 格式，请在 Houdini 中烘焙为 fbx 或 usd！"
            )

        return self

    # --------------------------------------------------------------------------
    # 动态派生计算字段 (@computed_field)
    # --------------------------------------------------------------------------
    @computed_field
    @property
    def virtual_engine_path(self) -> str:
        """根据资产类型与命名，动态推导符合游戏引擎包结构的标准虚拟路径。"""
        if self.software == "UnrealEngine":
            folder_name = UE_CATEGORY_FOLDERS.get(self.asset_type, "Common")
            return f"/Game/Art/{folder_name}/{self.asset_name}.{self.asset_name}"
        elif self.software == "Houdini":
            return f"/obj/GEO_{self.asset_name}"
        return f"|root|{self.asset_name}"


# ==============================================================================
# 6. 单元测试驱动执行入口 (Test Runner)
# ==============================================================================
def run_tests() -> None:
    """运行数据契约单元测试用例。"""
    print("=" * 70)
    print("[START] 开始运行 Pydantic 游戏管线数据契约自动化测试")
    print("=" * 70)

    # --------------------------------------------------------------------------
    # 测试用例 1：合法标准数据 (Happy Path)
    # --------------------------------------------------------------------------
    print("\n[测试用例 1] 传入合法的静态模型资产数据...")
    valid_payload = {
        "software": "UnrealEngine",
        "asset_type": "StaticMesh",
        "asset_name": "SM_Rock_Large_01",
        "format": "FBX",  # 验证大写自动转为小写 fbx
        "lod_level": 2,
        "transform": {
            "translation": {"x": 100.0, "y": 0.0, "z": 50.0},
            "scale": {"x": 1.5, "y": 1.5, "z": 1.5},
        },
    }

    try:
        model = GameAssetSchema(**valid_payload)
        print("[PASS] 解析成功！")
        print(f"• 资产名称: {model.asset_name}")
        print(f"• 格式归一化: {model.format}")
        print(f"• 计算字段 (虚幻资产路径): {model.virtual_engine_path}")
        print(f"• 导出的标准 JSON:\n{model.model_dump_json(indent=2)}")
    except ValidationError as err:
        print(f"[FAIL] 预期成功但发生报错: {err}")

    # --------------------------------------------------------------------------
    # 测试用例 2：违反命名规范拦截 (缺少 SM_ 前缀)
    # --------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("[测试用例 2] 模拟大模型输出不规范命名 (缺少 SM_ 前缀)...")
    invalid_name_payload = {
        "software": "UnrealEngine",
        "asset_type": "StaticMesh",
        "asset_name": "rock_large_01",  # 缺少 SM_ 前缀
        "format": "fbx",
    }
    try:
        GameAssetSchema(**invalid_name_payload)
        print("[FAIL] 拦截失败：不规范命名居然通过了！")
    except ValidationError as err:
        print("[PASS] 成功拦截非法命名！捕获预期异常：")
        print(f"   >>> {err.errors()[0]['msg']}")

    # --------------------------------------------------------------------------
    # 测试用例 3：跨字段参数冲突拦截 (模型带了分辨率参数)
    # --------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("[测试用例 3] 模拟跨字段逻辑互斥 (StaticMesh 试图配置 max_resolution)...")
    invalid_conflict_payload = {
        "software": "UnrealEngine",
        "asset_type": "StaticMesh",
        "asset_name": "SM_Chest_Treasure",
        "format": "fbx",
        "max_resolution": 2048,  # 模型不该有分辨率
    }
    try:
        GameAssetSchema(**invalid_conflict_payload)
        print("[FAIL] 拦截失败：互斥参数居然通过了！")
    except ValidationError as err:
        print("[PASS] 成功拦截互斥参数！捕获预期异常：")
        print(f"   >>> {err.errors()[0]['msg']}")

    # --------------------------------------------------------------------------
    # 测试用例 4：软件与格式不兼容拦截 (UE5 下发 bgeo 格式)
    # --------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("[测试用例 4] 模拟格式与平台不兼容 (UE5 尝试接收 bgeo)...")
    invalid_format_payload = {
        "software": "UnrealEngine",
        "asset_type": "StaticMesh",
        "asset_name": "SM_Smoke_Mesh",
        "format": "bgeo",  # UE5 原生不支持 bgeo
    }
    try:
        GameAssetSchema(**invalid_format_payload)
        print("[FAIL] 拦截失败：不兼容格式居然通过了！")
    except ValidationError as err:
        print("[PASS] 成功拦截格式平台不兼容！捕获预期异常：")
        print(f"   >>> {err.errors()[0]['msg']}")

    # --------------------------------------------------------------------------
    # 测试用例 5：生成供大模型使用的 JSON Schema 契约
    # --------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("[SCHEMA] 生成准备喂给 Ollama / OpenAI 的 JSON Schema 契约:")
    schema = GameAssetSchema.model_json_schema()
    properties = list(schema.get("properties", {}).keys())
    required_fields = schema.get("required", [])
    print(f"• 包含字段: {properties}")
    print(f"• 强约束必填项 (Required): {required_fields}")
    print("=" * 70)
    print("[SUCCESS] 数据契约全套防线已就绪，可随时交付给本地 Ollama 大模型！")


if __name__ == "__main__":
    run_tests()
