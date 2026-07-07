from __future__ import annotations

import copy
import json
import urllib.parse
from pathlib import Path
from typing import Any

from .httpclient import poll_promise, promise_id_from_response, request, request_multipart
from .fileio import save_json
from .models import SavantAppApiError, SavantSessionContext


def get_recipe(context: SavantSessionContext, flow_id: str) -> dict[str, Any]:
    recipe = request(context, f"/api/recipes/{flow_id}")
    if not isinstance(recipe, dict):
        raise SavantAppApiError(f"GET /api/recipes/{flow_id} did not return a JSON object.")
    nodes = recipe.get("nodes")
    model_nodes = recipe.get("model", {}).get("nodes") if isinstance(recipe.get("model"), dict) else None
    if not isinstance(nodes, list) and not isinstance(model_nodes, list):
        raise SavantAppApiError(f"GET /api/recipes/{flow_id} did not return a workflow-like recipe.")
    return recipe


def list_folder_recipes(context: SavantSessionContext, folder_id: str) -> dict[str, Any]:
    if not folder_id:
        raise SavantAppApiError("Folder workflow listing requires a folder id.")
    query = urllib.parse.urlencode({"folderId": folder_id})
    response = request(context, f"/api/recipes?{query}")
    if isinstance(response, list):
        return {"slice": [recipe for recipe in response if isinstance(recipe, dict)], "totalCount": len(response)}
    if not isinstance(response, dict):
        raise SavantAppApiError("GET /api/recipes?folderId=... did not return a JSON object.")
    recipes = response.get("slice")
    if recipes is None and isinstance(response.get("recipes"), list):
        recipes = response["recipes"]
    if not isinstance(recipes, list):
        raise SavantAppApiError("GET /api/recipes?folderId=... did not return a recipe array.")
    return {**response, "slice": [recipe for recipe in recipes if isinstance(recipe, dict)]}


def _json_copy(value: Any) -> Any:
    return copy.deepcopy(value)


def import_recipe_json(
    context: SavantSessionContext,
    json_path: Path,
    *,
    folder_id: str | None = None,
    folder_name: str | None = None,
) -> dict[str, Any]:
    if folder_id and folder_name:
        raise SavantAppApiError("Provide folder_id or folder_name, not both.")
    json_path = Path(json_path)
    if not json_path.exists() or not json_path.is_file():
        raise SavantAppApiError(f"Workflow JSON file does not exist: {json_path}")
    content = json_path.read_bytes()
    try:
        workflow = json.loads(content)
    except json.JSONDecodeError as exc:
        raise SavantAppApiError(f"Workflow JSON is not valid JSON: {json_path}") from exc
    if not isinstance(workflow, dict) or not isinstance(workflow.get("name"), str) or not isinstance(workflow.get("nodes"), list):
        raise SavantAppApiError("Workflow JSON must be an object with a string `name` and array `nodes`.")
    fields: dict[str, str] = {}
    if folder_id:
        fields["folderId"] = folder_id
    if folder_name:
        fields["folderName"] = folder_name
    response = request_multipart(
        context,
        "/api/recipes/import",
        fields=fields,
        files={"file": (json_path.name, content, "application/json")},
    )
    if not isinstance(response, dict):
        raise SavantAppApiError("POST /api/recipes/import did not return a JSON object.")
    return response


def _walk_json(value: Any) -> list[Any]:
    values = [value]
    if isinstance(value, dict):
        for child in value.values():
            values.extend(_walk_json(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(_walk_json(child))
    return values


def created_flow_id_from_import(import_response: dict[str, Any], promise_response: dict[str, Any] | None = None) -> str | None:
    candidates = [import_response]
    if promise_response is not None:
        candidates.append(promise_response)
    for value in _walk_json(candidates):
        if not isinstance(value, dict):
            continue
        for key in ("flowId", "recipeId", "analysisId"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        candidate = value.get("id")
        if isinstance(candidate, str) and candidate and (
            "folderId" in value or "numNodes" in value or ("namespace" in value and "name" in value)
        ):
            return candidate
        if value.get("type") == "recipe" and isinstance(candidate, str) and candidate:
            return candidate
    return None


def create_workflow_from_json(
    context: SavantSessionContext,
    json_path: Path,
    *,
    folder_id: str | None,
    poll: bool = True,
) -> dict[str, Any]:
    # folder_id None (or empty) means the Home folder (namespace root); import_recipe_json omits
    # the folderId field in that case so the workflow lands in the Home folder.
    import_response = import_recipe_json(context, json_path, folder_id=folder_id)
    result: dict[str, Any] = {"importResponse": import_response}
    if poll:
        promise_id = promise_id_from_response(import_response)
        promise_response = poll_promise(context, promise_id)
        result["promiseResponse"] = promise_response
    flow_id = created_flow_id_from_import(import_response, result.get("promiseResponse"))
    if flow_id:
        result["flowId"] = flow_id
        result["flowUrl"] = f"{context.origin}/en/app/flow/{flow_id}"
        if context.namespace:
            result["flowUrl"] += f"?rns={urllib.parse.quote(context.namespace)}"
        created = get_recipe(context, flow_id)
        created_folder_id = created.get("folderId") if isinstance(created, dict) else None
        # None and "" both denote the Home folder; normalize before comparing.
        if (created_folder_id or None) != (folder_id or None):
            raise SavantAppApiError(
                f"Workflow creation folder mismatch: requested folder `{folder_id or '(Home folder)'}`, "
                f"but created workflow `{flow_id}` reports folder `{created_folder_id or '(Home folder)'}`."
            )
        result["verifiedFolderId"] = created_folder_id
    return result


def _diff_has_changes(diff: dict[str, Any]) -> bool:
    nodes = diff.get("nodes") if isinstance(diff, dict) else None
    if not isinstance(nodes, dict):
        return bool(diff.get("parametersChanged")) if isinstance(diff, dict) else False
    return bool(nodes.get("added") or nodes.get("removed") or nodes.get("changed") or diff.get("parametersChanged"))

def recipe_nodes(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = recipe.get("nodes")
    if isinstance(nodes, list):
        return nodes
    model = recipe.get("model")
    if isinstance(model, dict) and isinstance(model.get("nodes"), list):
        return model["nodes"]
    return []


def recipe_parameters(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    parameters = recipe.get("parameters")
    if isinstance(parameters, list):
        return parameters
    model = recipe.get("model")
    if isinstance(model, dict) and isinstance(model.get("parameters"), list):
        return model["parameters"]
    return []


def prepare_recipe_for_save(
    recipe: dict[str, Any],
    *,
    nodes: list[dict[str, Any]] | None = None,
    parameters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(recipe, dict):
        raise SavantAppApiError("Recipe save requires a JSON object.")
    next_nodes = recipe_nodes(recipe) if nodes is None else nodes
    next_parameters = recipe_parameters(recipe) if parameters is None else parameters
    if not isinstance(next_nodes, list):
        raise SavantAppApiError("Recipe save requires a nodes array.")
    if not isinstance(next_parameters, list):
        raise SavantAppApiError("Recipe save requires a parameters array.")

    updated = _json_copy(recipe)
    copied_nodes = _json_copy(next_nodes)
    copied_parameters = _json_copy(next_parameters)
    model = updated.get("model") if isinstance(updated.get("model"), dict) else {}
    updated["nodes"] = copied_nodes
    updated["parameters"] = copied_parameters
    updated["model"] = {**model, "nodes": copied_nodes, "parameters": copied_parameters}
    return updated


def save_recipe(context: SavantSessionContext, recipe: dict[str, Any]) -> Any:
    prepared = prepare_recipe_for_save(recipe)
    return request(context, "/api/recipes", method="PUT", body={"recipe": prepared})


def save_metadata(context: SavantSessionContext, flow_id: str, metadata: dict[str, Any]) -> Any:
    # Flow metadata (name, description, tags) is NOT updated by `PUT /api/recipes`
    # (that writes only nodes/parameters). The app updates it through a dedicated
    # endpoint, sending the full flow object. `description` renders as Markdown.
    return request(context, f"/api/recipes/{flow_id}/metadata", method="PUT", body=metadata)


def save_recipe_model(
    context: SavantSessionContext,
    recipe: dict[str, Any],
    *,
    nodes: list[dict[str, Any]] | None = None,
    parameters: list[dict[str, Any]] | None = None,
) -> Any:
    prepared = prepare_recipe_for_save(recipe, nodes=nodes, parameters=parameters)
    return request(context, "/api/recipes", method="PUT", body={"recipe": prepared})


def update_workflow_recipe(
    context: SavantSessionContext,
    flow_id: str,
    edited_recipe: dict[str, Any],
) -> dict[str, Any]:
    """Update an existing workflow recipe in place and verify the target flow changed.

    This is intentionally separate from ``create_workflow_from_json``. Creation-shaped workflow
    JSON files do not carry the live workflow identity fields and must not be sent through the edit
    path; doing so can create a new workflow-like object instead of mutating the requested flow.
    """
    if not flow_id:
        raise SavantAppApiError("Workflow update requires an existing flow id.")
    if not isinstance(edited_recipe, dict):
        raise SavantAppApiError("Workflow update requires a recipe JSON object.")
    edited_id = edited_recipe.get("id")
    if not isinstance(edited_id, str) or not edited_id:
        raise SavantAppApiError(
            "Workflow update requires an edited recipe exported from the existing workflow. "
            "Creation-shaped workflow JSON has no `id`; use create_workflow_from_json for creation "
            "or merge the edit onto the live recipe before updating."
        )
    if edited_id != flow_id:
        raise SavantAppApiError(f"Edited recipe id `{edited_id}` does not match target flow id `{flow_id}`.")

    before = get_recipe(context, flow_id)
    requested_diff = recipe_model_diff(before, edited_recipe)
    if not _diff_has_changes(requested_diff):
        raise SavantAppApiError("Workflow update has no recipe changes to persist.")

    save_response = save_recipe_model(context, edited_recipe)
    response_id = save_response.get("id") if isinstance(save_response, dict) else None
    if isinstance(response_id, str) and response_id and response_id != flow_id:
        raise SavantAppApiError(
            f"Workflow update returned id `{response_id}` instead of target flow id `{flow_id}`; "
            "refusing to treat this as an in-place edit."
        )

    after = get_recipe(context, flow_id)
    persisted_diff = recipe_model_diff(before, after)
    if not _diff_has_changes(persisted_diff):
        raise SavantAppApiError(
            "Workflow update did not persist on the target workflow: requested changes were non-empty, "
            "but read-back of the target workflow was unchanged."
        )
    return {
        "flowId": flow_id,
        "requestedDiff": requested_diff,
        "persistedDiff": persisted_diff,
        "saveResponse": save_response,
    }


def backup_recipe(context: SavantSessionContext, flow_id: str, output_path: Path) -> dict[str, Any]:
    recipe = get_recipe(context, flow_id)
    save_json(recipe, output_path)
    return recipe


def _node_map(recipe: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["id"]: node for node in recipe_nodes(recipe) if isinstance(node, dict) and isinstance(node.get("id"), str)}


def _node_changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    fields = ["name", "type", "config", "position", "canvasConfig", "inlets", "outlets"]
    return [field for field in fields if before.get(field) != after.get(field)]


def recipe_model_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_nodes = _node_map(before)
    after_nodes = _node_map(after)
    before_ids = set(before_nodes)
    after_ids = set(after_nodes)
    changed = []
    for node_id in sorted(before_ids & after_ids):
        fields = _node_changed_fields(before_nodes[node_id], after_nodes[node_id])
        if fields:
            changed.append(
                {
                    "id": node_id,
                    "nameBefore": before_nodes[node_id].get("name"),
                    "nameAfter": after_nodes[node_id].get("name"),
                    "type": after_nodes[node_id].get("type") or before_nodes[node_id].get("type"),
                    "fields": fields,
                }
            )
    return {
        "nodes": {
            "added": sorted(after_ids - before_ids),
            "removed": sorted(before_ids - after_ids),
            "changed": changed,
        },
        "parametersChanged": recipe_parameters(before) != recipe_parameters(after),
    }


def assert_expected_model_diff(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    for key in ("added", "removed"):
        if key in expected:
            actual_values = actual.get("nodes", {}).get(key)
            if actual_values != expected[key]:
                raise SavantAppApiError(f"Unexpected node {key}: expected {expected[key]}, got {actual_values}")
    if "changed" in expected:
        expected_changed = sorted(expected["changed"])
        actual_changed = sorted(item["id"] for item in actual.get("nodes", {}).get("changed", []))
        if actual_changed != expected_changed:
            raise SavantAppApiError(f"Unexpected changed nodes: expected {expected_changed}, got {actual_changed}")
