# -*- coding: utf-8 -*-
"""
File: dcc_chunking_lab.py
Author: AFeiYA
Date: 2026-09-05
Description: Module 22 实战 —— 游戏管线高级文本切片策略实验室 (Chunking Strategies & Metadata Lab)。
             对比常规切片、递归字符切片 (Recursive)、Markdown 结构切片与 Python 代码 AST 切片，
             并将富集元数据的切片持久化写入 ChromaDB 进行检索验证。
"""

import os
import sys
from typing import Any, Dict, List
import chromadb
from langchain_text_splitters import (
    Language,
    MarkdownHeaderTextSplitter,
    PythonCodeTextSplitter,
    RecursiveCharacterTextSplitter,
)

# 确保 Windows 终端正确输出 UTF-8 字符
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# ==============================================================================
# 1. 模拟长篇真实游戏工作室规范手册 (Markdown + Python 混合长文档)
# ==============================================================================
STUDIO_ART_BIBLE_MD = """# 3A游戏项目《代号：星火》技术美术 (TA) 与资产管线规范手册

## 1. 静态网格体规范 (StaticMesh SOP)
所有导入虚幻5引擎的 3D 模型资产必须严格遵从以下技术指标与管线规则：

### 1.1 Nanite 与三角面预算
对于场景大中型硬表面资产、建筑、岩石与道具，强制在导入时开启 Nanite 网格体虚拟化几何体。
对于半透明网格、植被叶片（Foliage with WPO）或布料模拟模型，严禁开启 Nanite，必须手动制作 3 级传统 LOD。
LOD0 三角面上限：主角色不超过 80,000 面；普通 NPC 不超过 35,000 面；大型建筑不超过 150,000 面。

### 1.2 静态网格体自动化导入代码
管线工具自动化执行网格体导入的标准 Python 脚本范式如下：
```python
import unreal

def import_static_mesh_with_nanite(fbx_file: str, dest_folder: str, asset_name: str) -> unreal.StaticMesh:
    task = unreal.AssetImportTask()
    task.filename = fbx_file
    task.destination_path = dest_folder
    task.destination_name = asset_name
    task.replace_existing = True
    task.automated = True
    task.save = True

    options = unreal.FbxImportUI()
    options.import_mesh = True
    options.static_mesh_import_data.combine_meshes = True
    options.static_mesh_import_data.nanite_settings.enabled = True
    task.options = options

    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    return unreal.EditorAssetLibrary.load_asset(f"{dest_folder}/{asset_name}")
```

## 2. 纹理与材质规范 (Texture & Material SOP)
所有贴图资产必须经由 Substance 自动化烘焙流进入引擎，并在导入时按通道设定压缩格式：

### 2.1 贴图压缩与色彩空间配置
所有命名带有 '_N' 后缀的法线贴图（Normal Map），必须强制关闭 sRGB 色彩空间，并将压缩格式指定为 TC_Normalmap (BC5 算法压缩)。
基础漫反射贴图（_D 后缀）必须开启 sRGB (TC_Default / BC7 压缩)。
复合通道贴图（_ORM 后缀，R通道遮罩，G通道粗糙度，B通道金属度）必须关闭 sRGB 并采用 TC_Masks。

### 2.2 材质实例自动化生成代码
```python
import unreal

def create_and_bind_material_instance(master_mat_path: str, instance_dir: str, mi_name: str) -> unreal.MaterialInstanceConstant:
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.MaterialInstanceConstantFactoryNew()
    mi_asset = asset_tools.create_asset(mi_name, instance_dir, unreal.MaterialInstanceConstant, factory)
    master_mat = unreal.EditorAssetLibrary.load_asset(master_mat_path)
    mi_asset.set_editor_property("parent", master_mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mi_asset)
    return mi_asset
```

## 3. 命名规范与目录结构 (Naming & Hierarchy)
工程内资产目录绝对禁止直接堆放在根目录 /Game/ 下：
- 静态网格体：必须以 'SM_' 开头，归档至 '/Game/Environments/Meshes/'
- 纹理贴图：必须以 'T_' 开头，归档至 '/Game/Textures/'
- 材质实例：必须以 'MI_' 开头，归档至 '/Game/Materials/'
- 特效粒子：必须以 'NS_' (Niagara System) 开头，归档至 '/Game/Effects/'
"""


# ==============================================================================
# 2. 策略实测 1：MarkdownHeaderTextSplitter (结构化层级切片)
# ==============================================================================
def demo_markdown_header_splitter() -> List[Any]:
    """测试 MarkdownHeader 切片器，观察其如何自动捕获大纲标题并注入 Metadata。"""
    print("\n" + "=" * 75)
    print("🔬 [实验 1]：MarkdownHeaderTextSplitter (结构化层级切片)")
    print("=" * 75)

    headers_to_split_on = [
        ("#", "Header_1"),
        ("##", "Header_2"),
        ("###", "Header_3"),
    ]

    markdown_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=headers_to_split_on,
        strip_headers=False  # 保留标题以便大模型直接阅读完整语义
    )

    md_header_splits = markdown_splitter.split_text(STUDIO_ART_BIBLE_MD)
    print(f"📦 成功根据 Markdown 语法树切分为 {len(md_header_splits)} 个独立语义块：\n")

    for idx, doc in enumerate(md_header_splits, 1):
        print(f"--- [Chunk {idx}] ---")
        print(f"🏷️  [元数据面包屑 (Metadata)]: {doc.metadata}")
        preview_text = doc.page_content.strip()[:160].replace("\n", " ")
        print(f"📄 [内容预览 ({len(doc.page_content)} 字符)]: {preview_text}...\n")

    return md_header_splits


# ==============================================================================
# 3. 策略实测 2：RecursiveCharacterTextSplitter (递归字符退避切片)
# ==============================================================================
def demo_recursive_splitter() -> List[Any]:
    """测试递归字符切片器，观察段落/换行退避与滑动重叠窗口 (Overlap)。"""
    print("\n" + "=" * 75)
    print("🔬 [实验 2]：RecursiveCharacterTextSplitter (递归退避 + 15% 重叠率)")
    print("=" * 75)

    recursive_splitter = RecursiveCharacterTextSplitter(
        chunk_size=450,       # 黄金区间：400~600 字符
        chunk_overlap=60,     # ~15% 重叠，避免边界条件丢失
        separators=["\n\n", "\n", " ", ""]
    )

    splits = recursive_splitter.split_text(STUDIO_ART_BIBLE_MD)
    print(f"📦 递归切片器生成了 {len(splits)} 个子块 (Chunk Size: 450, Overlap: 60)：\n")

    for idx, text in enumerate(splits[:3], 1):
        print(f"--- [Chunk {idx} (前 3 块展示)] 长度: {len(text)} ---")
        print(f"{text.strip()[:180]}...\n")

    return splits


# ==============================================================================
# 4. 策略实测 3：PythonCodeTextSplitter (源码 AST 完整性切片)
# ==============================================================================
def demo_python_code_splitter() -> List[Any]:
    """测试针对 Python 代码语法的切片器，确保 def 与 class 绝不被拦腰斩断。"""
    print("\n" + "=" * 75)
    print("🔬 [实验 3]：PythonCodeTextSplitter (Python 语法感知切片)")
    print("=" * 75)

    sample_python_file = """
import unreal
import os

class UE5AssetAutomationTools:
    \"\"\"工作室通用资产自动化操作工具箱\"\"\"
    
    @staticmethod
    def import_static_mesh(fbx_path: str, dest_folder: str, asset_name: str) -> unreal.StaticMesh:
        \"\"\"导入网格体并配置 Nanite\"\"\"
        task = unreal.AssetImportTask()
        task.filename = fbx_path
        task.destination_path = dest_folder
        task.destination_name = asset_name
        task.replace_existing = True
        task.automated = True
        task.save = True

        options = unreal.FbxImportUI()
        options.import_mesh = True
        options.static_mesh_import_data.combine_meshes = True
        options.static_mesh_import_data.nanite_settings.enabled = True
        task.options = options

        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        return unreal.EditorAssetLibrary.load_asset(f"{dest_folder}/{asset_name}")

    @staticmethod
    def configure_normal_texture(texture_path: str) -> None:
        \"\"\"配置法线贴图格式\"\"\"
        tex = unreal.EditorAssetLibrary.load_asset(texture_path)
        if isinstance(tex, unreal.Texture2D):
            tex.set_editor_property("srgb", False)
            tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
            unreal.EditorAssetLibrary.save_loaded_asset(tex)
"""

    # PythonCodeTextSplitter 内部已预设 Python 语法树分隔符 (class/def/缩进)
    python_splitter = PythonCodeTextSplitter(
        chunk_size=400,
        chunk_overlap=40
    )


    code_splits = python_splitter.split_text(sample_python_file)
    print(f"📦 Python 语法切片器成功切出 {len(code_splits)} 个独立代码段落：\n")

    for idx, code_chunk in enumerate(code_splits, 1):
        print(f"--- [代码块 {idx}] ---")
        print(code_chunk.strip())
        print("-" * 50)

    return code_splits


# ==============================================================================
# 5. 实战融合：将富集元数据的切片灌入 ChromaDB 并验证精准检索
# ==============================================================================
def demo_chroma_metadata_search(md_splits: List[Any]) -> None:
    """将带有 Header 层级元数据的切片存入本地 ChromaDB，验证带有元数据的语义召回。"""
    print("\n" + "=" * 75)
    print("🚀 [实战融合]：将富集 Metadata 的 Chunk 存入本地 ChromaDB 并执行精准过滤检索")
    print("=" * 75)

    chroma_dir = os.path.join(os.path.dirname(__file__), "chroma_data")
    client = chromadb.PersistentClient(path=chroma_dir)
    collection = client.get_or_create_collection(
        name="ue5_chunking_lab",
        metadata={"hnsw:space": "cosine"}
    )

    # 准备写入数据
    ids = []
    documents = []
    metadatas = []

    for idx, doc in enumerate(md_splits, 1):
        chunk_id = f"art_bible_chunk_{idx}"
        ids.append(chunk_id)
        documents.append(doc.page_content)
        
        # 补充工业级元数据
        meta = dict(doc.metadata)
        meta["software"] = "UnrealEngine"
        meta["project"] = "Project_Spark"
        meta["engine_version"] = "5.4"
        metadatas.append(meta)

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    print(f"✅ 成功将 {len(ids)} 个带有大纲元数据的切片持久化写入 ChromaDB (./chroma_data)！")

    # 执行测试查询：专门提问一个正文中可能不包含完整词、但标题元数据里有的需求
    test_query = "法线贴图必须怎么配置？sRGB需要关吗？"
    print(f"\n🔍 发起语义测试查询: 「{test_query}」")

    search_res = collection.query(
        query_texts=[test_query],
        n_results=1
    )

    if search_res and search_res["documents"]:
        hit_doc = search_res["documents"][0][0]
        hit_meta = search_res["metadatas"][0][0]
        hit_dist = search_res["distances"][0][0]
        similarity = 1.0 - hit_dist

        print(f"\n🎯 [检索命中结果]:")
        print(f"• 相似度评分: {similarity:.4f} (距离: {hit_dist:.4f})")
        print(f"• 命中面包屑大纲: {hit_meta.get('Header_1')} > {hit_meta.get('Header_2')} > {hit_meta.get('Header_3')}")
        print(f"• 命中正文片段:\n{hit_doc.strip()}")


# ==============================================================================
# 6. 主执行流程
# ==============================================================================
def main() -> None:
    print("🚀 启动 Module 22 文本切片策略与元数据工程实验室")
    
    # 1. 结构化 Markdown 切片实测
    md_splits = demo_markdown_header_splitter()

    # 2. 递归字符切片实测
    demo_recursive_splitter()

    # 3. Python AST 语法感知切片实测
    demo_python_code_splitter()

    # 4. 存入 ChromaDB 并验证元数据增强检索
    demo_chroma_metadata_search(md_splits)

    print("\n" + "=" * 75)
    print("🎉 Module 22 切片实验全部顺利完成！")
    print("=" * 75)


if __name__ == "__main__":
    main()
