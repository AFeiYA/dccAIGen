# -*- coding: utf-8 -*-
"""End-to-End Integration Test for Multi-Agent Gameplay Blueprint Generation.

Validates the complete Supervisor Orchestration pipeline:
1. Supervisor WBS task decomposition (Asset TA -> Gameplay Logic);
2. Asset TA subagent mesh and collision preparation;
3. Gameplay Logic subagent Blueprint DSL generation & compilation;
4. Level actor placement and final quality synthesis.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

# Ensure UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dcc_agent.config import settings
from dcc_agent.graph.state import AgentPipelineState
from dcc_agent.graph.workflow import create_pipeline_app


async def test_multi_agent_coin_pickup():
    print("\n" + "=" * 75)
    print("🤖 [Multi-Agent Pipeline Test] 开始测试多智能体协同生成金币拾取可玩原型")
    print("=" * 75)

    app = create_pipeline_app(interrupt_gate=True)
    job_id = "JOB_TEST_COIN_PICKUP"
    config = {"configurable": {"thread_id": job_id}}

    prompt = "在当前关卡玩家前方生成一个名为 BP_CoinPickup 的金币拾取交互道具，包含球体碰撞体，角色碰到后打印金币收集成功并销毁自身"

    initial_state: AgentPipelineState = {
        "job_id": job_id,
        "user_query": prompt,
        "target_dcc": "Unreal Engine 5.8",
        "rag_context": "",
        "is_high_risk": False,
        "human_approved": False,
        "ue_mcp_online": False,
        "action_plan": [],
        "current_action": "",
        "action_args": {},
        "generated_code": "",
        "execution_result": {},
        "is_success": False,
        "error_message": "",
        "retry_count": 0,
        "max_retries": settings.max_retries,
        "reflection_notes": "",
        "audit_trail": [],
        "pipeline_mode": "multi_agent",
        "active_subagent": "supervisor",
        "wbs_plan": [],
        "current_wbs_index": 0,
        "subagent_results": {},
        "blueprint_dsl": "",
        "spawned_actors": [],
    }

    print(f"\n▶️  提交任务需求: '{prompt}'")
    print("⏳ 调度 Supervisor 状态机中枢执行流水线...")

    final_state = await app.ainvoke(initial_state, config)

    print("\n" + "-" * 75)
    print("🏁 【多智能体全生命周期协同审计追踪 (Audit Trail)】:")
    for idx, entry in enumerate(final_state.get("audit_trail", []), 1):
        print(f"  {idx}. {entry}")
    print("-" * 75)

    # Assertions
    wbs = final_state.get("wbs_plan", [])
    print(f"\n📋 [验收 1/5] Supervisor WBS 计划拆解项: {len(wbs)} 阶段")
    assert len(wbs) == 2, f"Expected 2-stage WBS, got {len(wbs)}"
    assert wbs[0]["agent"] == "asset_ta", "Stage 1 must be asset_ta"
    assert wbs[1]["agent"] == "gameplay", "Stage 2 must be gameplay"
    print("  ✅ WBS 工序拆解与前置依赖控制校验通过！")

    sub_res = final_state.get("subagent_results", {})
    print("\n📦 [验收 2/5] 子智能体交付结果核验:")
    assert "asset_ta" in sub_res, "Asset TA result missing"
    assert sub_res["asset_ta"]["status"] == "ok", "Asset TA failed"
    print(f"  ✅ Asset TA: 几何网格 '{sub_res['asset_ta']['mesh_path']}' & 碰撞 '{sub_res['asset_ta']['collision_profile']}'")

    assert "gameplay" in sub_res, "Gameplay result missing"
    assert sub_res["gameplay"]["status"] == "ok", "Gameplay failed"
    print(f"  ✅ Gameplay Agent: 实例 '{sub_res['gameplay']['actor_instance']}' 坐标 '{sub_res['gameplay']['location']}'")

    dsl = final_state.get("blueprint_dsl", "")
    print("\n📜 [验收 3/5] UE 5.8 蓝图 DSL 图表编译产物核验:")
    assert len(dsl) > 0, "Blueprint DSL must not be empty"
    assert "BP_CoinPickup" in dsl, "DSL must specify BP_CoinPickup asset"
    assert "SphereCollision" in dsl, "DSL must define SphereCollision"
    assert "Event_OnComponentBeginOverlap" in dsl, "DSL must wire overlap event"
    assert "DestroyActor" in dsl or "K2_DestroyActor" in dsl, "DSL must wire DestroyActor"
    print("  ✅ 蓝图 DSL 语义完整性核验通过（包含完整碰撞检测、字符串打印与销毁链）！")

    spawned = final_state.get("spawned_actors", [])
    print("\n🎮 [验收 4/5] 关卡视口摆放实体核验:")
    assert len(spawned) > 0, "Spawned actors list must not be empty"
    print(f"  ✅ 视口就绪实体: {spawned}")

    print("\n🎯 [验收 5/5] Supervisor 最终审查终态:")
    assert final_state.get("is_success"), "Pipeline must be marked as successful"
    print(f"  ✅ 最终交付结论: {final_state.get('execution_result', {}).get('pipeline_verdict')}")

    print("\n" + "=" * 75)
    print("🎉 [Multi-Agent Pipeline Test] 所有 5 项多智能体协同与实机蓝图测试全部通过！")
    print("=" * 75 + "\n")


if __name__ == "__main__":
    asyncio.run(test_multi_agent_coin_pickup())
