from pathlib import Path
from typing import Any

import yaml
from fastapi.routing import APIRoute

from naiad.main import app

HTTP_METHODS = {"get", "put", "post", "delete", "patch"}
ROUTE_HTTP_METHODS = {method.upper() for method in HTTP_METHODS}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_static_openapi() -> dict[str, Any]:
    with (_repo_root() / "docs" / "openapi.yaml").open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    assert isinstance(doc, dict)
    return doc


def _documented_operations(doc: dict[str, Any]) -> set[tuple[str, str]]:
    paths = doc.get("paths")
    assert isinstance(paths, dict)
    operations: set[tuple[str, str]] = set()
    for path, path_item in paths.items():
        assert isinstance(path, str)
        assert isinstance(path_item, dict)
        for method in HTTP_METHODS:
            if method in path_item:
                operations.add((method.upper(), path))
    return operations


def _app_operations() -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.include_in_schema:
            continue
        path = route.path_format
        if not path.startswith("/api/"):
            continue
        contract_path = path.removeprefix("/api")
        methods = {method for method in route.methods if method in ROUTE_HTTP_METHODS}
        for method in methods:
            operations.add((method, contract_path))
    return operations


def test_static_openapi_documents_all_backend_routes() -> None:
    doc = _load_static_openapi()

    documented = _documented_operations(doc)
    actual = _app_operations()

    assert documented == actual


def _iter_refs(value: object) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            refs.append(ref)
        for child in value.values():
            refs.extend(_iter_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(_iter_refs(child))
    return refs


def test_static_openapi_schema_refs_resolve() -> None:
    doc = _load_static_openapi()
    schemas = doc.get("components", {}).get("schemas", {})
    assert isinstance(schemas, dict)

    missing = sorted(
        ref
        for ref in _iter_refs(doc)
        if ref.startswith("#/components/schemas/") and ref.rsplit("/", 1)[-1] not in schemas
    )

    assert missing == []
