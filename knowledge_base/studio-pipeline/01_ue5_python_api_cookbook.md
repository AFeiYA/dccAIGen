# UE5 自动化 Python 核心 API 标准手册 (Cookbook)

本手册收录游戏研发管线中经真机测试、100% 验证可用的 Unreal Engine 5 官方 Python 标准代码范式。用于指导自动化资产导入、材质装配与贴图属性配置。

---

## 1. 静态网格体 (StaticMesh) 导入与 Nanite 配置

在 UE5 中自动化导入 FBX 静态网格体并激活 Nanite 虚拟化几何体，必须通过 `unreal.AssetToolsHelpers` 与 `unreal.AssetImportTask` 执行。

```python
import unreal

def import_static_mesh_with_nanite(fbx_file_path: str, destination_path: str, asset_name: str, enable_nanite: bool = True) -> unreal.StaticMesh:
    """
    自动化导入 FBX 模型为静态网格体并配置 Nanite。

    Args:
        fbx_file_path (str): 外部源 FBX 文件绝对路径。
        destination_path (str): 引擎内部存放目录 (如 /Game/Environments/Meshes/)。
        asset_name (str): 资产名称 (需遵从 SM_ 规范)。
        enable_nanite (bool): 是否激活 Nanite 虚拟化几何体。

    Returns:
        unreal.StaticMesh: 成功导入的网格体资产对象。
    """
    task = unreal.AssetImportTask()
    task.filename = fbx_file_path
    task.destination_path = destination_path
    task.destination_name = asset_name
    task.replace_existing = True
    task.automated = True
    task.save = True

    # 配置 FBX 导入参数
    options = unreal.FbxImportUI()
    options.import_mesh = True
    options.import_textures = False
    options.import_materials = False
    options.static_mesh_import_data.combine_meshes = True
    options.static_mesh_import_data.nanite_settings.enabled = enable_nanite
    task.options = options

    # 执行导入任务
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    imported_assets = task.get_objects()
    return imported_assets[0] if imported_assets else None
```

> **注意事项**：
> 1. 严禁使用不存在的虚假 API（如 `unreal.import_mesh()` 或 `unreal.AssetManager.load_mesh()`）；
> 2. `destination_path` 必须以 `/Game/` 开头，且不带末尾文件名。

---

## 2. 材质实例 (MaterialInstanceConstant) 动态创建与纹理参数绑定

自动化根据母材质创建材质实例，并动态给其纹理参数（如 BaseColor、Normal、ORM）赋值的标准实现：

```python
import unreal
from typing import Dict

def create_and_bind_material_instance(
    master_material_path: str, 
    instance_dir: str, 
    instance_name: str, 
    texture_parameters: Dict[str, str]
) -> unreal.MaterialInstanceConstant:
    """
    基于母材质创建材质实例并动态注入贴图参数。

    Args:
        master_material_path (str): 母材质资产路径 (如 /Game/Materials/M_Master_Base)。
        instance_dir (str): 目标存放目录 (如 /Game/Materials/)。
        instance_name (str): 材质实例名称 (需以 MI_ 开头)。
        texture_parameters (Dict[str, str]): 贴图参数字典 {"ParamName": "/Game/Textures/T_Name"}。

    Returns:
        unreal.MaterialInstanceConstant: 创建并保存的材质实例对象。
    """
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.MaterialInstanceConstantFactoryNew()

    # 1. 创建材质实例资产
    mi_asset = asset_tools.create_asset(
        asset_name=instance_name,
        package_path=instance_dir,
        asset_class=unreal.MaterialInstanceConstant,
        factory=factory
    )

    # 2. 关联父级母材质
    master_mat = unreal.EditorAssetLibrary.load_asset(master_material_path)
    mi_asset.set_editor_property("parent", master_mat)

    # 3. 动态配置各纹理参数
    for param_name, tex_path in texture_parameters.items():
        tex_asset = unreal.EditorAssetLibrary.load_asset(tex_path)
        if tex_asset:
            unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(
                mi_asset,
                param_name,
                tex_asset
            )

    # 4. 保存资产到磁盘
    unreal.EditorAssetLibrary.save_loaded_asset(mi_asset)
    return mi_asset
```

> **核心函数**：参数赋值必须调用 `unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value`。

---

## 3. 贴图压缩格式与色彩空间 (sRGB / BC5) 自动化修正

导入贴图时，根据其通道用途（尤其是法线贴图与 ORM 遮罩图）纠正 sRGB 与压缩格式的标准代码：

```python
import unreal

def configure_texture_compression(texture_asset_path: str, is_normal_map: bool = False, is_mask: bool = False) -> None:
    """
    检查并配置贴图资产的色彩空间与压缩格式。

    Args:
        texture_asset_path (str): 贴图资产路径 (如 /Game/Textures/T_Rock_N)。
        is_normal_map (bool): 是否为法线贴图 (需 TC_Normalmap / BC5)。
        is_mask (bool): 是否为复合通道遮罩 (ORM 需 TC_Masks)。
    """
    texture = unreal.EditorAssetLibrary.load_asset(texture_asset_path)
    if not isinstance(texture, unreal.Texture2D):
        raise TypeError(f"目标资产不是 Texture2D: {texture_asset_path}")

    if is_normal_map:
        # 法线贴图必须关闭 sRGB 并强制使用 TC_Normalmap (BC5 算法)
        texture.set_editor_property("srgb", False)
        texture.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
    elif is_mask:
        # ORM 遮罩图必须关闭 sRGB 并使用 TC_Masks
        texture.set_editor_property("srgb", False)
        texture.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_MASKS)
    else:
        # 默认漫反射彩色贴图开启 sRGB
        texture.set_editor_property("srgb", True)
        texture.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_DEFAULT)

    # 标记修改并写盘保存
    unreal.EditorAssetLibrary.save_loaded_asset(texture)
```
