# -*- coding: utf-8 -*-
"""
File: dcc_rag_pipeline.py
Author: AFeiYA
Date: 2026-09-04
Description: Module 21 生产级落地 —— 基于 ChromaDB 向量库 + OpenAI SDK 流式协议 + Mac Ollama 26B
             的游戏管线 RAG 检索增强系统。彻底解决长推理超时与 DCC 私有 API 幻觉。
"""

import os
import sys
import time
from typing import Any, Dict, List, Optional
import chromadb
from openai import OpenAI

# 确保 Windows 终端正确输出 UTF-8 字符
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# ==============================================================================
# 0. 配置参数
# ==============================================================================
MAC_IP = "192.168.1.222"
OLLAMA_OPENAI_URL = f"http://{MAC_IP}:11434/v1"
# 选用 26B 旗舰模型，支持深度逻辑推导与代码生成
MODEL_NAME = "gemma4:26b-mlx"
CHROMA_PERSIST_DIR = os.path.join(os.path.dirname(__file__), "chroma_data")
COLLECTION_NAME = "ue5_pipeline_knowledge"


# ==============================================================================
# 1. 知识库定义：工作室真实 UE5 Python 官方标准 API 与规约
# ==============================================================================
KNOWLEDGE_DOCS = [
    {
        "id": "ue5_api_static_mesh_import",
        "title": "UE5 Python: 静态网格体 (StaticMesh) 导入与 Nanite 开启标准 API",
        "content": """[UE5 官方标准代码范式 - 静态网格体 FBX 导入]
在 Unreal Engine 5 中自动化导入 FBX 并设置 Nanite 的标准 Python 流程：
```python
import unreal

def import_static_mesh(fbx_file_path: str, destination_path: str, enable_nanite: bool = True) -> unreal.StaticMesh:
    task = unreal.AssetImportTask()
    task.filename = fbx_file_path
    task.destination_path = destination_path
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

    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    imported_assets = task.get_objects()
    return imported_assets[0] if imported_assets else None
```
注意：严禁调用不存在的 unreal.import_mesh() 或 unreal.AssetManager.load_mesh()，必须通过 unreal.AssetToolsHelpers 与 AssetImportTask 执行导入。""",
        "metadata": {
            "software": "UnrealEngine",
            "category": "API_Reference",
            "module": "StaticMesh",
            "engine_version": "5.4"
        }
    },
    {
        "id": "ue5_api_material_instance_create",
        "title": "UE5 Python: 动态创建材质实例并绑定贴图参数",
        "content": """[UE5 官方标准代码范式 - 材质实例 MaterialInstanceConstant 创建与参数绑定]
```python
import unreal

def create_material_instance(master_material_path: str, instance_path: str, instance_name: str, texture_params: dict) -> unreal.MaterialInstanceConstant:
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.MaterialInstanceConstantFactoryNew()
    
    # 1. 创建材质实例资产
    material_instance = asset_tools.create_asset(
        asset_name=instance_name,
        package_path=instance_path,
        asset_class=unreal.MaterialInstanceConstant,
        factory=factory
    )
    
    # 2. 绑定母材质 (Master Material)
    master_mat = unreal.EditorAssetLibrary.load_asset(master_material_path)
    material_instance.set_editor_property("parent", master_mat)
    
    # 3. 动态更新纹理参数 (Texture Parameter)
    for param_name, tex_path in texture_params.items():
        tex_asset = unreal.EditorAssetLibrary.load_asset(tex_path)
        if tex_asset:
            unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(
                material_instance, 
                param_name, 
                tex_asset
            )
            
    unreal.EditorAssetLibrary.save_loaded_asset(material_instance)
    return material_instance
```
关键点：贴图参数赋值必须使用 unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value()。""",
        "metadata": {
            "software": "UnrealEngine",
            "category": "API_Reference",
            "module": "Material",
            "engine_version": "5.4"
        }
    },
    {
        "id": "ue5_api_texture_compression_setup",
        "title": "UE5 Python: 贴图压缩格式与 sRGB 设置 (Normal Map / BC5)",
        "content": """[UE5 官方标准代码范式 - 贴图压缩格式配置]
```python
import unreal

def configure_normal_map_texture(texture_asset_path: str) -> None:
    texture = unreal.EditorAssetLibrary.load_asset(texture_asset_path)
    if not isinstance(texture, unreal.Texture2D):
        raise TypeError("目标资产不是 Texture2D")

    # 法线贴图必须禁用 sRGB 并设为 TC_Normalmap (BC5 格式)
    texture.set_editor_property("srgb", False)
    texture.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
    
    # 标记修改并保存
    unreal.EditorAssetLibrary.save_loaded_asset(texture)
```
注意：如果资产名称包含 '_N' 或以 'T_' 开头且为法线贴图，必须严格执行此设置。""",
        "metadata": {
            "software": "UnrealEngine",
            "category": "API_Reference",
            "module": "Texture",
            "engine_version": "5.4"
        }
    },
    {
        "id": "studio_pipeline_naming_sop",
        "title": "项目美术管线规范: 资产命名与路径目录映射标准",
        "content": """[项目美术管线规范 SOP v2.5]
1. 静态网格体 (StaticMesh):
   - 命名必须以 'SM_' 开头，例如 'SM_Rock_Large_01'
   - 存放目录必须为: '/Game/Environments/Meshes/'
2. 纹理贴图 (Texture):
   - 命名必须以 'T_' 开头，漫反射加后缀 '_D'，法线贴图加后缀 '_N'，粗糙度度/金属度加后缀 '_ORM'
   - 存放目录必须为: '/Game/Textures/'
3. 材质资产 (Material):
   - 母材质以 'M_' 开头，材质实例以 'MI_' 开头
   - 存放目录必须为: '/Game/Materials/'
4. 导入时若发现未按前缀命名，自动化工具必须自动为其纠正前缀后再存入对应目录。""",
        "metadata": {
            "software": "UnrealEngine",
            "category": "Pipeline_SOP",
            "module": "Naming_Convention",
            "engine_version": "Universal"
        }
    }
]


# ==============================================================================
# 2. ChromaDB 向量数据库封装管理
# ==============================================================================
class DCCKnowledgeBase:
    """管理本地轻量向量数据库 ChromaDB 的初始化、文档索引与语义检索。"""

    def __init__(self, persist_directory: str = CHROMA_PERSIST_DIR) -> None:
        self.persist_dir = persist_directory
        self.client = chromadb.PersistentClient(path=self.persist_dir)
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        self._seed_knowledge_if_empty()

    def _seed_knowledge_if_empty(self) -> None:
        """如果集合为空，则灌入初始管线知识与官方 API。"""
        current_count = self.collection.count()
        if current_count == 0:
            print(f"📦 知识库为空，正在向 ChromaDB 灌入 {len(KNOWLEDGE_DOCS)} 条专业 DCC API 知识...")
            ids = [doc["id"] for doc in KNOWLEDGE_DOCS]
            documents = [doc["content"] for doc in KNOWLEDGE_DOCS]
            metadatas = [doc["metadata"] for doc in KNOWLEDGE_DOCS]

            self.collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )
            print("✅ 知识库索引构建完成！")
        else:
            print(f"📚 本地 ChromaDB 已加载！当前收录知识条目数: {current_count}")

    def query_relevant_knowledge(self, query: str, top_k: int = 2, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """在向量数据库中进行语义相似度搜索。"""
        where_filter = {"category": category} if category else None

        results = self.collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where_filter
        )

        retrieved_items = []
        if results and results.get("documents"):
            docs = results["documents"][0]
            metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
            distances = results["distances"][0] if results.get("distances") else [0.0] * len(docs)
            ids = results["ids"][0] if results.get("ids") else [""] * len(docs)

            for doc_id, doc, meta, dist in zip(ids, docs, metas, distances):
                # 余弦距离转相似度评分 (Cosine Similarity = 1 - Cosine Distance)
                similarity = 1.0 - dist
                retrieved_items.append({
                    "id": doc_id,
                    "content": doc,
                    "metadata": meta,
                    "similarity": similarity
                })

        return retrieved_items


# ==============================================================================
# 3. 基于 OpenAI SDK 的流式 RAG 推理客户端 (支持 Thinking + Code)
# ==============================================================================
class DCCAgentRAGClient:
    """封装与本地 Mac Ollama 通信的流式客户端，杜绝 30s 阻塞超时。"""

    def __init__(self, base_url: str = OLLAMA_OPENAI_URL, model_name: str = MODEL_NAME) -> None:
        self.client = OpenAI(
            base_url=base_url,
            api_key="ollama",  # 本地 Ollama 无需真实 key
            timeout=180.0       # 允许总耗时宽限到 180s，流式读取永不超时
        )
        self.model = model_name

    def stream_generate_code(self, system_instruction: str, user_prompt: str) -> None:
        """流式调用并实时打印模型的思维链 (Thinking) 与交付代码 (Code)。"""
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt}
            ],
            stream=True,
            temperature=0.1,
            max_tokens=1500
        )

        has_printed_think_header = False
        has_printed_code_header = False

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            # 提取思维链推导 (Gemma / DeepSeek / Qwen 思考协议)
            reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None) or ""
            if reasoning:
                if not has_printed_think_header:
                    print("\n🧠 [模型深度思考推导 (Thinking Chain)]:")
                    has_printed_think_header = True
                print(reasoning, end="", flush=True)

            # 提取最终交付代码
            content = delta.content or ""
            if content:
                if not has_printed_code_header:
                    print("\n\n⚡ [模型最终交付代码 (Executable Script)]:\n" + "-" * 75)
                    has_printed_code_header = True
                print(content, end="", flush=True)


# ==============================================================================
# 4. 全链路 RAG 调度器
# ==============================================================================
def run_dcc_rag_copilot(user_query: str, kb: DCCKnowledgeBase, agent: DCCAgentRAGClient) -> None:
    """端到端闭环：自然语言 -> ChromaDB 检索 -> 组装上下文 -> 流式大模型生成。"""
    print("\n" + "=" * 75)
    print(f"💬 [TA 用户提问]: 「{user_query}」")
    print("=" * 75)

    # 1. 向量相似度检索 (Retrieval)
    t0 = time.time()
    retrieved_docs = kb.query_relevant_knowledge(user_query, top_k=2)
    retrieval_time = (time.time() - t0) * 1000

    print(f"🔍 [向量检索完成] 耗时: {retrieval_time:.2f}ms | 命中 {len(retrieved_docs)} 条相关知识：")
    context_str = ""
    for idx, item in enumerate(retrieved_docs, 1):
        sim = item["similarity"]
        meta = item["metadata"]
        print(f"   [{idx}] ID: {item['id']} | 相似度: {sim:.4f} | 模块: {meta.get('module')} | 版本: {meta.get('engine_version')}")
        context_str += f"\n--- 参考知识 [{idx}] ({item['id']}) ---\n{item['content']}\n"

    # 2. 增强提示词组装 (Augmentation)
    system_instruction = """你是一名资深游戏管线技术美术 (Lead Unreal Engine Pipeline TA)。
你的职责是依据【参考官方 API 与规范手册】，为用户编写工业级、精准无幻觉的 UE5 Python 自动化脚本。

【铁律规范】：
1. 必须 100% 依据参考上下文中的类和函数编写（如 unreal.AssetImportTask, unreal.AssetToolsHelpers），严禁捏造虚假 API；
2. 严格执行项目命名与路径规约（静态网格体必须以 SM_ 开头，存放于 /Game/Environments/Meshes/ 等）；
3. 编写完整的参数类型注解与工业级错误处理机制。"""

    user_augmented_prompt = f"""【参考官方 API 与规范手册】：
{context_str}

【用户具体需求】：
{user_query}

请为我编写符合上述所有规约的完整 Python 脚本："""

    # 3. 流式生成 (Generation)
    print(f"\n📡 正在流式请求 Mac Ollama ({agent.model}) 推理中枢...")
    start_gen = time.time()
    agent.stream_generate_code(system_instruction, user_augmented_prompt)
    total_time = time.time() - start_gen

    print("\n" + "-" * 75)
    print(f"✅ [端到端流式生成交付完毕] (总耗时: {total_time:.2f} 秒 | 0 超时风险)")
    print("=" * 75)


# ==============================================================================
# 5. 主执行入口
# ==============================================================================
def main() -> None:
    print("🚀 启动 DCC 本地向量知识库 RAG 检索增强系统 (ChromaDB + OpenAI 流式 SDK)")
    kb = DCCKnowledgeBase()
    agent = DCCAgentRAGClient()

    # 测试任务：导入静态网格体并开启 Nanite，同时检验模型是否自动执行前缀纠正
    q1 = "请写一个 UE5 Python 脚本，将外部 'D:/Models/Hero_Sword.fbx' 导入到工程规范目录下，名字就叫 Hero_Sword，开启 Nanite"
    run_dcc_rag_copilot(q1, kb, agent)


if __name__ == "__main__":
    main()
