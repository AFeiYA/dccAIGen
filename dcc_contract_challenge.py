"""
dcc_contract_challenge.py - 游戏管线与 TA 工具链 Pydantic 数据契约实战

涵盖知识点：
1. BaseModel & Field 约束 (Literal, ge, le, min_length)
2. 嵌套模型 (Vector3D, Transform)
3. @field_validator: 资产前缀清洗与格式约束 (SM_, T_, M_)
4. @model_validator: 跨字段互斥与软件特性合法性检查
5. @computed_field: 引擎引用路径自动推导
6. 导出 model_json_schema() 供大模型 Structured Outputs 使用
"""

import sys
from typing import Literal, Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator, computed_field, ValidationError
import json

# 解决 Windows 默认控制台编码问题
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


# ==============================================================================
# 1. 基础物理与变换模型 (Nested Model)
# ==============================================================================
class Vector3D(BaseModel):
    """三维向量，用于控制 DCC 中的位置、旋转与缩放"""
    x: float = Field(default=0.0, description="X 轴坐标")
    y: float = Field(default=0.0, description="Y 轴坐标")
    z: float = Field(default=0.0, description="Z 轴坐标")


class Transform(BaseModel):
    """场景空间变换属性"""
    translation: Vector3D = Field(default_factory=Vector3D, description="位移")
    rotation: Vector3D = Field(default_factory=Vector3D, description="欧拉旋转 (度)")
    scale: Vector3D = Field(
        default_factory=lambda: Vector3D(x=1.0, y=1.0, z=1.0), description="缩放比例"
    )

    @field_validator("scale")
    @classmethod
    def validate_scale(cls, v: Vector3D) -> Vector3D:
        if v.x == 0 or v.y == 0 or v.z == 0:
            raise ValueError("缩放分量不能为 0，否则会导致模型退化！")
        return v


# ==============================================================================
# 2. 核心管线资产操作契约 (GameAssetSchema)
# ==============================================================================
class GameAssetSchema(BaseModel):
    """
    大模型向 DCC 软件下发资产创建与导入指令的核心契约
    """
    software: Literal["Houdini", "UnrealEngine", "Maya"] = Field(
        ..., description="目标运行的 DCC 软件平台"
    )
    asset_type: Literal["StaticMesh", "Texture", "Material"] = Field(
        ..., description="游戏资产分类"
    )
    asset_name: str = Field(
        ..., min_length=3, max_length=50, description="资产唯一命名，需遵循命名规范"
    )
    format: str = Field(
        ..., description="资产文件格式，如 fbx, usd, png, tga, bgeo"
    )
    
    # 选填参数
    lod_level: int = Field(default=0, ge=0, le=4, description="LOD 等级 (0~4)")
    max_resolution: Optional[int] = Field(
        default=None, description="贴图最大分辨率 (仅贴图资产可用，如 1024, 2048, 4096)"
    )
    transform: Transform = Field(default_factory=Transform, description="场景空间变换")
    custom_attributes: Dict[str, Any] = Field(default_factory=dict, description="额外自定义参数")

    # --------------------------------------------------------------------------
    # 单字段校验：资产命名强制遵循工作室前缀规范
    # --------------------------------------------------------------------------
    @field_validator("asset_name")
    @classmethod
    def validate_naming_convention(cls, v: str) -> str:
        v = v.strip()
        if " " in v:
            raise ValueError(f"资产命名不得包含空格: '{v}'")
        return v

    @field_validator("format")
    @classmethod
    def normalize_format(cls, v: str) -> str:
        return v.strip().lower().lstrip(".")

    # --------------------------------------------------------------------------
    # 跨字段联合校验 (@model_validator)
    # --------------------------------------------------------------------------
    @model_validator(mode="after")
    def validate_cross_rules(self):
        # 规则 A：根据资产类别校验前缀
        prefix_mapping = {
            "StaticMesh": "SM_",
            "Texture": "T_",
            "Material": "M_",
        }
        required_prefix = prefix_mapping.get(self.asset_type)
        if required_prefix and not self.asset_name.startswith(required_prefix):
            raise ValueError(
                f"命名规范违规: {self.asset_type} 类别的资产名必须以 '{required_prefix}' 开头，当前为 '{self.asset_name}'！"
            )

        # 规则 B：静态网格体不得设置贴图分辨率
        if self.asset_type == "StaticMesh" and self.max_resolution is not None:
            raise ValueError("参数互斥: 静态网格体 (StaticMesh) 不得设置 max_resolution 分辨率参数！")

        # 规则 C：贴图资产必须提供分辨率
        if self.asset_type == "Texture" and self.max_resolution is None:
            raise ValueError("参数缺失: 贴图资产 (Texture) 必须指定 max_resolution 分辨率 (如 2048)！")

        # 规则 D：软件格式支持度检查 (Houdini 专有格式不能在 UE5 平台下发)
        if self.software == "UnrealEngine" and self.format in ["bgeo", "vdb"]:
            raise ValueError(f"格式不支持: Unreal Engine 原生管线不支持直接加载 .{self.format} 格式，请导出为 fbx 或 usd！")

        return self

    # --------------------------------------------------------------------------
    # 计算属性：动态生成虚幻引擎与 Houdini 内部路径
    # --------------------------------------------------------------------------
    @computed_field
    @property
    def virtual_engine_path(self) -> str:
        """自动推导符合游戏引擎资产包结构的虚幻路径"""
        if self.software == "UnrealEngine":
            category_folders = {
                "StaticMesh": "Meshes",
                "Texture": "Textures",
                "Material": "Materials"
            }
            folder = category_folders.get(self.asset_type, "Common")
            return f"/Game/Art/{folder}/{self.asset_name}.{self.asset_name}"
        elif self.software == "Houdini":
            return f"/obj/GEO_{self.asset_name}"
        else:
            return f"|root|{self.asset_name}"


# ==============================================================================
# 3. 验收测试执行入口
# ==============================================================================
def run_tests():
    print("=" * 70)
    print("[START] 开始运行 Pydantic 游戏管线数据契约自动化测试")
    print("=" * 70)

    # --------------------------------------------------------------------------
    # 测试用例 1：合法标准数据（Happy Path）
    # --------------------------------------------------------------------------
    print("\n[测试用例 1] 传入合法的静态模型资产数据...")
    valid_data = {
        "software": "UnrealEngine",
        "asset_type": "StaticMesh",
        "asset_name": "SM_Rock_Large_01",
        "format": "FBX",  # 测试大小写自动清洗为 fbx
        "lod_level": 2,
        "transform": {
            "translation": {"x": 100.0, "y": 0.0, "z": 50.0},
            "scale": {"x": 1.5, "y": 1.5, "z": 1.5}
        }
    }
    
    try:
        model = GameAssetSchema(**valid_data)
        print("[PASS] 解析成功！")
        print(f"• 资产名称: {model.asset_name}")
        print(f"• 格式已清洗为: {model.format}")
        print(f"• 计算字段 (虚幻资产路径): {model.virtual_engine_path}")
        print(f"• 导出的干净 JSON:\n{model.model_dump_json(indent=2)}")
    except ValidationError as e:
        print(f"[FAIL] 预期成功但发生报错: {e}")

    # --------------------------------------------------------------------------
    # 测试用例 2：违反命名规范拦截 (缺少 SM_ 前缀)
    # --------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("[测试用例 2] 模拟大模型输出不规范命名 (缺少 SM_ 前缀)...")
    invalid_name_data = {
        "software": "UnrealEngine",
        "asset_type": "StaticMesh",
        "asset_name": "rock_large_01",  # 缺少 SM_ 前缀！
        "format": "fbx"
    }
    try:
        GameAssetSchema(**invalid_name_data)
        print("[FAIL] 拦截失败：不规范命名居然通过了！")
    except ValidationError as e:
        print("[PASS] 成功拦截非法命名！捕获预期异常：")
        print(f"   >>> {e.errors()[0]['msg']}")

    # --------------------------------------------------------------------------
    # 测试用例 3：跨字段参数冲突拦截 (模型带了分辨率参数)
    # --------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("[测试用例 3] 模拟跨字段逻辑互斥 (StaticMesh 试图设置 max_resolution)...")
    invalid_conflict_data = {
        "software": "UnrealEngine",
        "asset_type": "StaticMesh",
        "asset_name": "SM_Chest_Treasure",
        "format": "fbx",
        "max_resolution": 2048  # 模型不该有分辨率！
    }
    try:
        GameAssetSchema(**invalid_conflict_data)
        print("[FAIL] 拦截失败：互斥参数居然通过了！")
    except ValidationError as e:
        print("[PASS] 成功拦截互斥参数！捕获预期异常：")
        print(f"   >>> {e.errors()[0]['msg']}")

    # --------------------------------------------------------------------------
    # 测试用例 4：软件与格式不兼容拦截 (UE5 下发 bgeo 格式)
    # --------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("[测试用例 4] 模拟格式与平台不兼容 (UE5 尝试接收 bgeo)...")
    invalid_format_data = {
        "software": "UnrealEngine",
        "asset_type": "StaticMesh",
        "asset_name": "SM_Smoke_Mesh",
        "format": "bgeo"  # UE5 不支持 bgeo
    }
    try:
        GameAssetSchema(**invalid_format_data)
        print("[FAIL] 拦截失败：不兼容格式居然通过了！")
    except ValidationError as e:
        print("[PASS] 成功拦截格式平台不兼容！捕获预期异常：")
        print(f"   >>> {e.errors()[0]['msg']}")

    # --------------------------------------------------------------------------
    # 测试用例 5：生成供大模型 (Ollama / OpenAI) 使用的 JSON Schema 契约
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
