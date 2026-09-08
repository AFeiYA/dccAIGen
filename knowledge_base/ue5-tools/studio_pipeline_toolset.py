# -*- coding: utf-8 -*-
"""Studio Pipeline Toolset for Unreal Engine 5.8 Model Context Protocol (MCP).

This script defines an official Unreal MCP Toolset using Unreal Engine 5.8's
native Toolset Registry architecture. When placed in the UE project's Content/Python
directory (or loaded via Unreal Python environment), Unreal MCP automatically registers
these tools and exposes them to external AI Agents over the local MCP connection.
"""

from __future__ import annotations

import io
import sys
import traceback
from typing import Any

# Notice: unreal and toolset_registry are provided natively inside Unreal Engine Editor
try:
    import unreal
    import toolset_registry
    HAS_UNREAL = True
except ImportError:
    HAS_UNREAL = False


if HAS_UNREAL:

    @unreal.uclass()
    class StudioPipelineToolset(unreal.ToolsetDefinition):
        """Studio Pipeline TA Toolset for Unreal Engine 5.8.

        Provides specialized Technical Artist tools for level inspection,
        asset naming convention audit according to Studio SOP, viewport actor manipulation,
        and safe Python code execution on the Game Thread.
        """

        @toolset_registry.tool_call
        @staticmethod
        def get_editor_world_status() -> dict[str, Any]:
            """Retrieves the current Unreal Editor level status and active world metadata.

            Returns:
                A dictionary containing level path, actor count, and editor state.
            """
            editor_subsystem = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
            current_world = editor_subsystem.get_editor_world() if editor_subsystem else None
            world_name = current_world.get_name() if current_world else "Unknown"

            all_actors = unreal.EditorLevelLibrary.get_all_level_actors() if hasattr(unreal, "EditorLevelLibrary") else []

            return {
                "current_world": world_name,
                "total_actors_in_level": len(all_actors),
                "is_editor_game_world": current_world.is_game_world() if current_world else False,
            }

        @toolset_registry.tool_call
        @staticmethod
        def get_selected_actors_info() -> list[dict[str, Any]]:
            """Inspects all currently selected actors in the Unreal Editor viewport.

            Returns:
                A list of dictionaries with actor name, label, class name, location, and rotation.
            """
            selected_actors = unreal.EditorLevelLibrary.get_selected_level_actors()
            results = []

            for actor in selected_actors:
                loc = actor.get_actor_location()
                rot = actor.get_actor_rotation()
                results.append({
                    "name": actor.get_name(),
                    "label": actor.get_actor_label(),
                    "class": actor.get_class().get_name(),
                    "location": {"x": round(loc.x, 2), "y": round(loc.y, 2), "z": round(loc.z, 2)},
                    "rotation": {"pitch": round(rot.pitch, 2), "yaw": round(rot.yaw, 2), "roll": round(rot.roll, 2)},
                })
            return results

        @toolset_registry.tool_call
        @staticmethod
        def audit_actors_naming(class_filter: str = "") -> dict[str, Any]:
            """Audits all actors in the active level against Studio SOP naming conventions.

            According to the studio style guide:
            - StaticMeshActor must start with 'SM_'
            - Blueprint / Character must start with 'BP_'
            - Directional / Point / Spot Light must start with 'LGT_'
            - CameraActor must start with 'CAM_'

            Args:
                class_filter: Optional filter by actor class name (e.g. 'StaticMeshActor').

            Returns:
                A report listing compliant actors, non-compliant actors, and suggested fixes.
            """
            all_actors = unreal.EditorLevelLibrary.get_all_level_actors()
            compliant: list[str] = []
            violations: list[dict[str, str]] = []

            prefix_rules = {
                "StaticMeshActor": "SM_",
                "PointLight": "LGT_Point_",
                "DirectionalLight": "LGT_Sun_",
                "SpotLight": "LGT_Spot_",
                "CameraActor": "CAM_",
                "CineCameraActor": "CAM_Cine_",
            }

            for actor in all_actors:
                cls_name = actor.get_class().get_name()
                if class_filter and class_filter.lower() not in cls_name.lower():
                    continue

                label = actor.get_actor_label()
                expected_prefix = prefix_rules.get(cls_name)

                if expected_prefix:
                    if not label.startswith(expected_prefix):
                        suggested_name = f"{expected_prefix}{label}"
                        violations.append({
                            "actor_label": label,
                            "class": cls_name,
                            "expected_prefix": expected_prefix,
                            "suggested_fix": suggested_name,
                        })
                    else:
                        compliant.append(label)

            return {
                "total_audited": len(compliant) + len(violations),
                "compliant_count": len(compliant),
                "violations_count": len(violations),
                "violations": violations,
            }

        @toolset_registry.tool_call
        @staticmethod
        def spawn_pipeline_actor(
            asset_path: str = "/Engine/BasicShapes/Cube",
            actor_label: str = "SM_PipelineTestAsset",
            location_x: float = 0.0,
            location_y: float = 0.0,
            location_z: float = 0.0,
        ) -> dict[str, Any]:
            """Spawns an actor in the current level with specified asset and location.

            Args:
                asset_path: Asset path in Content Browser (e.g. /Engine/BasicShapes/Cube).
                actor_label: Desired display label for the spawned actor.
                location_x: X coordinate in Unreal world units (cm).
                location_y: Y coordinate in Unreal world units (cm).
                location_z: Z coordinate in Unreal world units (cm).

            Returns:
                A dictionary with details of the spawned actor.
            """
            asset = unreal.EditorAssetLibrary.load_asset(asset_path)
            if not asset:
                return {
                    "success": False,
                    "error": f"Failed to load asset at path: {asset_path}",
                }

            loc = unreal.Vector(location_x, location_y, location_z)
            rot = unreal.Rotator(0.0, 0.0, 0.0)

            # Spawn actor using EditorLevelLibrary
            actor = unreal.EditorLevelLibrary.spawn_actor_from_object(asset, loc, rot)
            if not actor:
                return {
                    "success": False,
                    "error": "Failed to spawn actor from asset object.",
                }

            actor.set_actor_label(actor_label)

            return {
                "success": True,
                "actor_name": actor.get_name(),
                "actor_label": actor.get_actor_label(),
                "class": actor.get_class().get_name(),
                "location": {"x": location_x, "y": location_y, "z": location_z},
            }

        @toolset_registry.tool_call
        @staticmethod
        def execute_editor_python(code: str) -> dict[str, Any]:
            """Safely executes custom Python code inside Unreal Engine on the Game Thread.

            Args:
                code: Valid Python script to execute within Unreal Python environment.

            Returns:
                Execution results including stdout, stderr, and success status.
            """
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            redirected_stdout = io.StringIO()
            redirected_stderr = io.StringIO()

            try:
                sys.stdout = redirected_stdout
                sys.stderr = redirected_stderr
                exec_scope: dict[str, Any] = {"unreal": unreal}
                exec(code, exec_scope)
                return {
                    "success": True,
                    "stdout": redirected_stdout.getvalue(),
                    "stderr": redirected_stderr.getvalue(),
                }
            except Exception as exc:
                return {
                    "success": False,
                    "stdout": redirected_stdout.getvalue(),
                    "stderr": redirected_stderr.getvalue(),
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

else:
    # Standalone mock/fallback for testing outside Unreal Editor
    class StudioPipelineToolset:
        """Fallback mock for StudioPipelineToolset outside Unreal Engine."""
        pass
