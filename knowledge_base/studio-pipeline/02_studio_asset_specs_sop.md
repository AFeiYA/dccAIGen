# 项目美术资产规格与技术管线标准 (Studio SOP v2.5)

本规范为工作室项目研发的核心美术规约，所有通过自动化 Agent 或美术手动提交的资产均须强制经过本规约合规性审查。

---

## 1. 几何体与网格体技术指标 (Mesh Budget & Nanite)

### 1.1 Nanite 虚拟化几何体开启准则
- **强制开启 Nanite 的资产**：
  - 所有中大型环境场景物件（岩石、山体、断崖、地面硬表面）；
  - 建筑结构体、桥梁、道具、家具；
  - 面数超过 5,000 面的无变形静态模型。
- **严禁开启 Nanite 的资产**：
  - 半透明网格（Translucent Materials）；
  - 具有世界位置偏移（WPO）的细密植被叶片（Foliage）；
  - 布料解算与刚体碎裂物理几何体。
- **非 Nanite 资产的 LOD 规范**：
  - 必须制作至少 3 级 LOD（LOD0: 100%, LOD1: 50%, LOD2: 25%）。

### 1.2 三角面预算上限 (Poly Count Guidelines)
- **主角模型 (Hero Characters)**：LOD0 不超过 85,000 面；
- **普通 NPC (Monsters / NPCs)**：LOD0 不超过 35,000 面；
- **主场景核心建筑 (Landmarks)**：不超过 150,000 面；
- **散布小道具 (Props)**：不超过 4,000 面。

---

## 2. 纹理贴图规范与通道打包 (Texture & Channel Packing)

### 2.1 贴图分辨率限制
- 主角贴图：最高不超过 2048 x 2048；
- 环境建筑贴图：通常为 1024 x 1024 或 2048 x 2048；
- 小道具与装饰物：严格限制在 512 x 512 或 1024 x 1024。

### 2.2 通道打包标准 (PBR ORM Standard)
为节省显存与减少 Sampler 占用，PBR 参数贴图必须采用 3 通道打包为单个 `_ORM` 贴图：
- **R 通道 (Red)**：环境光遮蔽 (Ambient Occlusion, AO)；
- **G 通道 (Green)**：粗糙度 (Roughness)；
- **B 通道 (Blue)**：金属度 (Metallic)。
- **导入属性**：`_ORM` 贴图导入后必须**取消勾选 sRGB**，压缩格式选择 `TC_Masks`。

---

## 3. 项目工程目录分层规范 (Project Spark Directory Hierarchy)

虚幻引擎项目内资产严禁直接堆放在 `/Game/` 根目录下，必须遵照以下标准目录树归档：

- 静态网格体目录：`/Game/Environments/Meshes/`
- 角色模型目录：`/Game/Characters/Meshes/`
- 纹理贴图目录：`/Game/Textures/`
- 材质资产目录：`/Game/Materials/`
- 特效粒子目录：`/Game/Effects/`
- 本地测试沙盒目录：`/Game/Developers/[用户名]/` (所有非正式提交资产仅限放于此处)

---

## 4. 命名纠偏铁律 (Auto-Correction Rule)
如果美术传入的资产未带规范前缀（如将大剑命名为 `Hero_Sword`）：
1. 自动化 Agent **不得直接报错中断任务**；
2. 必须根据资产类型**自动补全前缀**（如自动更名为 `SM_Hero_Sword`）；
3. 将更名日志与归档路径记录并向 TA 输出。
