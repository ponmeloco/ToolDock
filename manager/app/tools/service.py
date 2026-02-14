from __future__ import annotations

from typing import Any

from app.config import ManagerSettings
from app.core_client import CoreClient
from app.tools.builder import BuilderTools
from app.tools.dependencies import DependencyTools
from app.tools.installer import InstallerTools
from app.tools.introspect import IntrospectTools
from app.tools.namespaces import NamespaceTools
from app.tools.secrets import SecretTools
from app.tools.tool_files import ToolFileTools


class ManagerToolService:
    def __init__(self, settings: ManagerSettings, started_at: float):
        self._core = CoreClient(settings)
        self._namespaces = NamespaceTools(settings)
        self._tool_files = ToolFileTools(settings)
        self._dependencies = DependencyTools(settings)
        self._secrets = SecretTools(settings)
        self._builder = BuilderTools(settings)
        self._installer = InstallerTools(settings)
        self._introspect = IntrospectTools(settings, started_at)

    def list_tool_descriptors(self) -> list[dict[str, Any]]:
        namespace = _string_schema(
            description="Namespace name.",
            pattern=r"^[a-z0-9][a-z0-9-]*$",
        )
        filename = _string_schema(
            description="Python filename inside namespace (must end with .py).",
            pattern=r"^[^/]+\.py$",
        )
        return [
            {
                "name": "a_first_call_instructions",
                "description": "Read this first: manager workflow and parameter guide for all tools.",
                "input_schema": _object_schema(),
            },
            {
                "name": "list_namespaces",
                "description": "List installed namespaces.",
                "input_schema": _object_schema(),
            },
            {
                "name": "create_namespace",
                "description": "Create a namespace.",
                "input_schema": _object_schema(required={"name": namespace}),
            },
            {
                "name": "delete_namespace",
                "description": "Delete a namespace.",
                "input_schema": _object_schema(required={"name": namespace}),
            },
            {
                "name": "reload_core",
                "description": "Reload core registry and workers.",
                "input_schema": _object_schema(),
            },
            {
                "name": "list_tools",
                "description": "List tools in namespace.",
                "input_schema": _object_schema(required={"namespace": namespace}),
            },
            {
                "name": "get_tool_source",
                "description": "Read Python tool file source.",
                "input_schema": _object_schema(required={"namespace": namespace, "filename": filename}),
            },
            {
                "name": "get_tool_template",
                "description": "Get recommended starter template for writing tool code.",
                "input_schema": _object_schema(
                    optional={
                        "template_name": _string_schema(
                            description="Template variant, default fastmcp-basic.",
                        )
                    },
                ),
            },
            {
                "name": "write_tool",
                "description": "Write and validate a Python tool file.",
                "input_schema": _object_schema(
                    required={
                        "namespace": namespace,
                        "filename": filename,
                        "code": _string_schema(description="Full Python source code."),
                    },
                ),
            },
            {
                "name": "delete_tool",
                "description": "Delete a Python tool file.",
                "input_schema": _object_schema(required={"namespace": namespace, "filename": filename}),
            },
            {
                "name": "install_requirements",
                "description": "Install namespace requirements into venv.",
                "input_schema": _object_schema(required={"namespace": namespace}),
            },
            {
                "name": "add_requirement",
                "description": "Add package to requirements and install.",
                "input_schema": _object_schema(
                    required={
                        "namespace": namespace,
                        "package": _string_schema(description="Package specifier, e.g. requests==2.32.3."),
                    },
                ),
            },
            {
                "name": "list_requirements",
                "description": "List requirements.txt packages.",
                "input_schema": _object_schema(required={"namespace": namespace}),
            },
            {
                "name": "prepare_secret",
                "description": "Create secret placeholder metadata.",
                "input_schema": _object_schema(
                    required={"key": _string_schema(description="Secret key name.")},
                    optional={"namespace": namespace},
                ),
            },
            {
                "name": "list_secrets",
                "description": "List secret status without values.",
                "input_schema": _object_schema(optional={"namespace": namespace}),
            },
            {
                "name": "remove_secret",
                "description": "Remove secret entry.",
                "input_schema": _object_schema(
                    required={"key": _string_schema(description="Secret key name.")},
                    optional={"namespace": namespace},
                ),
            },
            {
                "name": "check_secrets",
                "description": "Check namespace secret readiness.",
                "input_schema": _object_schema(required={"namespace": namespace}),
            },
            {
                "name": "analyze_repo",
                "description": "Clone and analyze repository.",
                "input_schema": _object_schema(
                    required={"repo_url": _string_schema(description="Git repository URL.")},
                ),
            },
            {
                "name": "read_repo_file",
                "description": "Read file from analyzed repository.",
                "input_schema": _object_schema(
                    required={
                        "repo_url": _string_schema(description="Git repository URL."),
                        "path": _string_schema(description="Path inside repository."),
                    },
                ),
            },
            {
                "name": "generate_tool",
                "description": "Alias to write_tool for generated code.",
                "input_schema": _object_schema(
                    required={
                        "namespace": namespace,
                        "filename": filename,
                        "code": _string_schema(description="Generated Python source code."),
                    },
                ),
            },
            {
                "name": "test_tool",
                "description": "Invoke tool through core for validation.",
                "input_schema": _object_schema(
                    required={
                        "namespace": namespace,
                        "tool_name": _string_schema(description="Tool function name."),
                    },
                    optional={
                        "input": {
                            "type": "object",
                            "description": "Input arguments passed to the tool.",
                            "additionalProperties": True,
                        },
                    },
                ),
            },
            {
                "name": "install_pip_packages",
                "description": "Install manager-side analysis packages.",
                "input_schema": _object_schema(
                    required={
                        "packages": {
                            "type": "array",
                            "description": "PIP package specifiers.",
                            "items": {"type": "string"},
                            "minItems": 1,
                        },
                    },
                ),
            },
            {
                "name": "search_registry",
                "description": "Search curated MCP registry.",
                "input_schema": _object_schema(
                    required={"query": _string_schema(description="Search query.")},
                ),
            },
            {
                "name": "install_from_registry",
                "description": "Analyze package from registry source.",
                "input_schema": _object_schema(
                    required={
                        "package": _string_schema(description="Registry package identifier."),
                        "namespace": namespace,
                    },
                ),
            },
            {
                "name": "install_from_repo",
                "description": "Analyze direct git repository.",
                "input_schema": _object_schema(
                    required={
                        "repo_url": _string_schema(description="Git repository URL."),
                        "namespace": namespace,
                    },
                ),
            },
            {
                "name": "health",
                "description": "Manager + core health.",
                "input_schema": _object_schema(),
            },
            {
                "name": "server_config",
                "description": "Manager runtime config (non-sensitive).",
                "input_schema": _object_schema(),
            },
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "a_first_call_instructions":
            return self._first_call_instructions()
        if name == "list_namespaces":
            return self._namespaces.list_namespaces()
        if name == "create_namespace":
            return self._namespaces.create_namespace(name=str(arguments["name"]))
        if name == "delete_namespace":
            return self._namespaces.delete_namespace(name=str(arguments["name"]))
        if name == "reload_core":
            return await self._core.reload_core()

        if name == "list_tools":
            return self._tool_files.list_tools(namespace=str(arguments["namespace"]))
        if name == "get_tool_source":
            return self._tool_files.get_tool_source(namespace=str(arguments["namespace"]), filename=str(arguments["filename"]))
        if name == "get_tool_template":
            return self._tool_files.get_tool_template(template_name=str(arguments.get("template_name") or "fastmcp-basic"))
        if name == "write_tool":
            return self._tool_files.write_tool(
                namespace=str(arguments["namespace"]),
                filename=str(arguments["filename"]),
                code=str(arguments["code"]),
            )
        if name == "delete_tool":
            return self._tool_files.delete_tool(namespace=str(arguments["namespace"]), filename=str(arguments["filename"]))

        if name == "install_requirements":
            return self._dependencies.install_requirements(namespace=str(arguments["namespace"]))
        if name == "add_requirement":
            return self._dependencies.add_requirement(namespace=str(arguments["namespace"]), package=str(arguments["package"]))
        if name == "list_requirements":
            return self._dependencies.list_requirements(namespace=str(arguments["namespace"]))

        if name == "prepare_secret":
            return self._secrets.prepare_secret(key=str(arguments["key"]), namespace=arguments.get("namespace"))
        if name == "list_secrets":
            return self._secrets.list_secrets(namespace=arguments.get("namespace"))
        if name == "remove_secret":
            return self._secrets.remove_secret(key=str(arguments["key"]), namespace=arguments.get("namespace"))
        if name == "check_secrets":
            return self._secrets.check_secrets(namespace=str(arguments["namespace"]))

        if name == "analyze_repo":
            return self._builder.analyze_repo(repo_url=str(arguments["repo_url"]))
        if name == "read_repo_file":
            return self._builder.read_repo_file(repo_url=str(arguments["repo_url"]), path=str(arguments["path"]))
        if name == "generate_tool":
            return self._builder.generate_tool(
                namespace=str(arguments["namespace"]),
                filename=str(arguments["filename"]),
                code=str(arguments["code"]),
            )
        if name == "test_tool":
            return await self._builder.test_tool(
                namespace=str(arguments["namespace"]),
                tool_name=str(arguments["tool_name"]),
                input=arguments.get("input") or {},
            )
        if name == "install_pip_packages":
            return self._builder.install_pip_packages(packages=list(arguments.get("packages") or []))

        if name == "search_registry":
            return self._installer.search_registry(query=str(arguments["query"]))
        if name == "install_from_registry":
            return self._installer.install_from_registry(
                package=str(arguments["package"]),
                namespace=str(arguments["namespace"]),
            )
        if name == "install_from_repo":
            return self._installer.install_from_repo(
                repo_url=str(arguments["repo_url"]),
                namespace=str(arguments["namespace"]),
            )

        if name == "health":
            return await self._introspect.health()
        if name == "server_config":
            return self._introspect.server_config()

        raise KeyError(name)

    def _first_call_instructions(self) -> dict[str, Any]:
        tools: list[dict[str, Any]] = []
        for descriptor in self.list_tool_descriptors():
            tool_name = str(descriptor.get("name") or "")
            if tool_name == "a_first_call_instructions":
                continue
            tools.append(_descriptor_usage(descriptor))

        return {
            "tool": "a_first_call_instructions",
            "purpose": "Call this once per session before using manager tools.",
            "workflow": [
                "1) Call list_namespaces.",
                "2) Create or choose a namespace.",
                "3) Call get_tool_template and mirror its structure.",
                "4) Write or update tool files.",
                "5) Install requirements and prepare secrets.",
                "6) Reload core and run test_tool.",
            ],
            "rules": [
                "Always provide every required parameter exactly as listed.",
                "Use get_tool_template before first write in a new namespace.",
                "Use namespace-scoped operations unless a tool is explicitly global.",
                "Use health and server_config for diagnostics.",
            ],
            "tools": tools,
        }


def _object_schema(
    *,
    required: dict[str, dict[str, Any]] | None = None,
    optional: dict[str, dict[str, Any]] | None = None,
    additional_properties: bool = False,
) -> dict[str, Any]:
    properties: dict[str, dict[str, Any]] = {}
    required_keys: list[str] = []

    if required:
        for key, schema in required.items():
            properties[key] = schema
            required_keys.append(key)

    if optional:
        properties.update(optional)

    payload: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional_properties,
    }
    if required_keys:
        payload["required"] = required_keys
    return payload


def _string_schema(*, description: str | None = None, pattern: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "string"}
    if description:
        payload["description"] = description
    if pattern:
        payload["pattern"] = pattern
    return payload


def _descriptor_usage(descriptor: dict[str, Any]) -> dict[str, Any]:
    schema = descriptor.get("input_schema")
    if not isinstance(schema, dict):
        schema = {}

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        properties = {}

    required_raw = schema.get("required")
    required: list[str] = []
    if isinstance(required_raw, list):
        required = [str(item) for item in required_raw]

    optional = [key for key in properties.keys() if key not in required]
    parameters: list[dict[str, Any]] = []
    for key, field_schema in properties.items():
        field_description = ""
        if isinstance(field_schema, dict):
            raw = field_schema.get("description")
            if isinstance(raw, str):
                field_description = raw
        parameters.append(
            {
                "name": key,
                "required": key in required,
                "description": field_description,
            }
        )

    return {
        "name": str(descriptor.get("name") or ""),
        "description": str(descriptor.get("description") or ""),
        "required_parameters": required,
        "optional_parameters": optional,
        "parameters": parameters,
    }
