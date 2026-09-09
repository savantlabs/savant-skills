from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

from .fileio import save_json, workspace_tmp
from .httpclient import request
from .models import SavantAppApiError, SavantSessionContext
from .recipe_input import load_recipe
from .session import discover_session, parse_savant_url


def _source_nodes(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = recipe.get("nodes")
    if not isinstance(nodes, list):
        return []
    return [node for node in nodes if isinstance(node, dict) and node.get("type") == "source"]


def _dataset_id_from_source_node(node: dict[str, Any]) -> str | None:
    config = node.get("config")
    if not isinstance(config, dict):
        return None
    dataset_id = config.get("id")
    return dataset_id if isinstance(dataset_id, str) and dataset_id else None


def workflow_source_dataset_ids(recipe: dict[str, Any]) -> list[dict[str, str | None]]:
    """Return source-node bindings from a workflow recipe, preserving step context for the manifest."""
    result: list[dict[str, str | None]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for node in _source_nodes(recipe):
        dataset_id = _dataset_id_from_source_node(node)
        key = (str(node.get("id") or ""), dataset_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "nodeId": str(node.get("id") or "") or None,
                "nodeName": str(node.get("name") or "") or None,
                "datasetId": dataset_id,
            }
        )
    return result


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "-", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "download"


def _unique_path(output_dir: Path, filename: str, discriminator: str | None = None) -> Path:
    filename = _safe_filename(filename)
    candidate = output_dir / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    if discriminator:
        candidate = output_dir / f"{stem} ({_safe_filename(discriminator)}){suffix}"
        if not candidate.exists():
            return candidate
    index = 2
    while True:
        candidate = output_dir / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _signed_url_from_response(response: Any, *, file_id: str) -> str:
    if isinstance(response, str) and response:
        return response
    if isinstance(response, dict):
        for key in ("signedUrl", "url", "downloadUrl", "href", "link"):
            value = response.get(key)
            if isinstance(value, str) and value:
                return value
    raise SavantAppApiError(f"Signed URL response for file `{file_id}` did not include a downloadable URL.")


def _download_url(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=90) as response:
        return response.read()


def _source_detail_file_id(detail: dict[str, Any]) -> str | None:
    file_id = detail.get("fileId")
    if isinstance(file_id, str) and file_id:
        return file_id
    config = detail.get("config")
    if isinstance(config, dict):
        file_id = config.get("fileId")
        if isinstance(file_id, str) and file_id:
            return file_id
    return None


def _source_detail_tab_name(detail: dict[str, Any]) -> str | None:
    config = detail.get("config")
    if not isinstance(config, dict):
        return None
    tab_name = config.get("tabName") or config.get("table")
    return tab_name if isinstance(tab_name, str) and tab_name else None


def download_dataset_files(
    context: SavantSessionContext,
    dataset_refs: list[dict[str, str | None]],
    output_dir: Path,
) -> dict[str, Any]:
    """Download uploaded-file-backed datasets and return a manifest.

    Dataset/source records from system connections generally have no `fileId`; those are not
    downloadable as uploaded files and are recorded as skipped instead of treated as errors.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for ref in dataset_refs:
        dataset_id = ref.get("datasetId")
        entry: dict[str, Any] = {**ref, "status": "skipped"}
        if not dataset_id:
            entry["reason"] = "Source step is not bound to a dataset id."
            entries.append(entry)
            continue

        detail = request(context, f"/api/sources/{dataset_id}")
        if not isinstance(detail, dict):
            entry["reason"] = "Source detail did not return an object."
            entries.append(entry)
            continue

        file_id = _source_detail_file_id(detail)
        config = detail.get("config") if isinstance(detail.get("config"), dict) else {}
        entry.update(
            {
                "datasetName": detail.get("name"),
                "connector": detail.get("connector") or config.get("connector"),
                "fileId": file_id,
                "tabName": _source_detail_tab_name(detail),
            }
        )
        if not file_id:
            entry["reason"] = "Dataset is not backed by an uploaded file."
            entries.append(entry)
            continue

        file_meta = request(context, f"/api/upload/files/{file_id}")
        if not isinstance(file_meta, dict):
            entry["reason"] = "Uploaded file metadata did not return an object."
            entries.append(entry)
            continue

        file_name = file_meta.get("fileName")
        if not isinstance(file_name, str) or not file_name:
            file_name = f"{file_id}.bin"
        signed = request(context, f"/api/upload/files/{file_id}/signed-url")
        url = _signed_url_from_response(signed, file_id=file_id)
        local_path = _unique_path(output_dir, file_name, dataset_id)
        local_path.write_bytes(_download_url(url))
        entry.update(
            {
                "status": "downloaded",
                "fileName": file_name,
                "fileStatus": file_meta.get("fileStatus"),
                "localPath": str(local_path),
                "bytes": local_path.stat().st_size,
            }
        )
        entries.append(entry)

    downloaded = [entry for entry in entries if entry.get("status") == "downloaded"]
    skipped = [entry for entry in entries if entry.get("status") != "downloaded"]
    return {
        "namespace": context.namespace,
        "outputDir": str(output_dir),
        "downloadedCount": len(downloaded),
        "skippedCount": len(skipped),
        "datasets": entries,
    }


def _default_output_dir(label: str) -> Path:
    return workspace_tmp("savant-dataset-downloads", _safe_filename(label))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download uploaded files behind Savant datasets.")
    parser.add_argument(
        "url",
        help=(
            "Savant flow URL to download all source datasets in the workflow, or any Savant URL "
            "with --dataset-id to download specific datasets in that workspace."
        ),
    )
    parser.add_argument("--dataset-id", action="append", default=[], help="Dataset/source id to download. Can be repeated.")
    parser.add_argument("--source-id", action="append", default=[], help="Alias for --dataset-id. Can be repeated.")
    parser.add_argument("--workflow-json", type=Path,
                        help="The flow's recipe, fetched with the MCP `fetch` tool on "
                             "savant://workflow/{flowId}. Required for a flow URL; not needed when "
                             "datasets are named with --dataset-id.")
    parser.add_argument("--output-dir", type=Path, help="Directory for downloaded files and manifest.")
    parser.add_argument("--manifest-path", type=Path, help="Optional manifest JSON path. Defaults to <output-dir>/manifest.json.")
    parser.add_argument("--stdout", action="store_true", help="Print the manifest JSON after writing it.")
    parser.add_argument("--quiet", action="store_true", help="Only print the manifest path.")
    args = parser.parse_args(argv)

    parsed = parse_savant_url(args.url)
    context = discover_session(parsed.namespace, origin=parsed.origin)

    dataset_ids = [*args.dataset_id, *args.source_id]
    refs: list[dict[str, str | None]]
    label = parsed.flow_id or parsed.namespace or "datasets"
    if dataset_ids:
        refs = [{"nodeId": None, "nodeName": None, "datasetId": dataset_id} for dataset_id in dataset_ids]
        label = dataset_ids[0] if len(dataset_ids) == 1 else "datasets"
    elif parsed.kind == "flow" and parsed.flow_id:
        if args.workflow_json is None:
            raise SavantAppApiError(
                "Downloading a flow's source datasets needs the flow's recipe. Fetch it with the "
                "MCP `fetch` tool on savant://workflow/{flowId}, write it to a JSON file, and pass "
                "--workflow-json <path>. Or name the datasets directly with --dataset-id."
            )
        refs = workflow_source_dataset_ids(load_recipe(args.workflow_json))
        if not refs:
            raise SavantAppApiError("Workflow does not contain source dataset steps.")
    else:
        raise SavantAppApiError("Pass --dataset-id for non-flow URLs.")

    output_dir = args.output_dir or _default_output_dir(label)
    manifest = download_dataset_files(context, refs, output_dir)
    manifest_path = args.manifest_path or (output_dir / "manifest.json")
    save_json(manifest, manifest_path)

    if args.stdout:
        print(json.dumps(manifest, indent=2))
    elif args.quiet:
        print(manifest_path)
    else:
        print(
            f"Downloaded {manifest['downloadedCount']} dataset file(s); "
            f"skipped {manifest['skippedCount']}; wrote manifest to {manifest_path}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SavantAppApiError as exc:
        print(f"savant dataset download: {exc}")
        raise SystemExit(2)
