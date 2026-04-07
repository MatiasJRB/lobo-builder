from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import select

from autonomy_hub.adapters.filesystem import discover_git_repositories
from autonomy_hub.config import Settings
from autonomy_hub.db import GraphEdgeRecord, GraphNodeRecord, edge_exists
from autonomy_hub.domain.models import ArtifactPayload, ConfigCatalog, GraphEdgeView, GraphNodeView, GraphSnapshot
from autonomy_hub.services.project_context import discover_repo_instructions


def slugify(value: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in value.lower()).strip("-") or "item"


class GraphService:
    def __init__(self, settings: Settings, session_factory, catalog: ConfigCatalog):
        self.settings = settings
        self.session_factory = session_factory
        self.catalog = catalog

    def seed_static_nodes(self) -> None:
        with self.session_factory() as session:
            self._upsert_node(session, "Environment", "Local Workspace", "local-workspace", metadata={"mode": "local"})

            for profile in self.catalog.agent_profiles.values():
                self._upsert_node(
                    session,
                    "AgentProfile",
                    profile.name,
                    profile.slug,
                    metadata={
                        "role": profile.role,
                        "allowed_tools": profile.allowed_tools,
                        "required_outputs": profile.required_outputs,
                    },
                )

            for policy in self.catalog.policies.values():
                self._upsert_node(
                    session,
                    "CapabilityPolicy",
                    policy.label,
                    policy.slug,
                    metadata=policy.model_dump(),
                )

            session.commit()

    def discover_workspace(
        self,
        path: Optional[Path] = None,
        max_depth: Optional[int] = None,
    ) -> GraphSnapshot:
        target = (path or self.settings.workspace_root).resolve()
        depth = max_depth if max_depth is not None else self.settings.discover_max_depth

        with self.session_factory() as session:
            local_env = self._upsert_node(
                session,
                "Environment",
                "Local Workspace",
                "local-workspace",
                metadata={"path": str(target)},
            )

            for repo in discover_git_repositories(target, max_depth=depth):
                hub_manifest = self.catalog.project_manifests.get(repo.name)
                repo_instructions = discover_repo_instructions(
                    repo.path,
                    hub_manifest.instruction_hints if hub_manifest else None,
                )
                repository = self._upsert_node(
                    session,
                    "Repository",
                    repo.name,
                    slugify(repo.name),
                    metadata={
                        "path": str(repo.path),
                        "surface": repo.surface,
                        "discovered_from": str(target),
                        "has_agents": bool(repo_instructions.agents_paths),
                        "has_skills": bool(repo_instructions.skill_slugs),
                        "instruction_paths": sorted(set(repo_instructions.agents_paths + repo_instructions.skill_paths)),
                        "skill_slugs": repo_instructions.skill_slugs,
                    },
                )

                product = self._upsert_node(
                    session,
                    "Product",
                    repo.family_slug.replace("-", " ").title(),
                    slugify(repo.family_slug),
                )
                project = self._upsert_node(
                    session,
                    "Project",
                    repo.family_slug.replace("-", " ").title(),
                    slugify(repo.family_slug),
                )

                self._upsert_edge(session, product.node_key, "contains_project", project.node_key)
                self._upsert_edge(session, project.node_key, "owns_repository", repository.node_key)
                self._upsert_edge(
                    session,
                    local_env.node_key,
                    "hosts_repository",
                    repository.node_key,
                    metadata={"path": str(repo.path)},
                )

            session.commit()

        return self.snapshot()

    def link_mission(
        self,
        mission_id: str,
        brief: str,
        policy_slug: str,
        linked_products: Iterable[str],
        linked_repositories: Iterable[str],
        linked_documents: Iterable[str],
        artifacts: Iterable[ArtifactPayload],
    ) -> None:
        with self.session_factory() as session:
            mission_node = self._upsert_node(
                session,
                "Mission",
                brief[:80],
                mission_id,
                metadata={"brief": brief},
            )
            policy_node = self._upsert_node(
                session,
                "CapabilityPolicy",
                self.catalog.policies[policy_slug].label,
                policy_slug,
                metadata=self.catalog.policies[policy_slug].model_dump(),
            )
            self._upsert_edge(session, mission_node.node_key, "governed_by", policy_node.node_key)

            for product_name in linked_products:
                product_node = self._upsert_node(
                    session,
                    "Product",
                    product_name,
                    slugify(product_name),
                )
                self._upsert_edge(session, mission_node.node_key, "targets_product", product_node.node_key)

            for repo_reference in linked_repositories:
                repo_node = self._repository_node_from_reference(session, repo_reference)
                self._upsert_edge(session, mission_node.node_key, "targets_repository", repo_node.node_key)

            for document_ref in linked_documents:
                document_node = self._upsert_node(
                    session,
                    "Document",
                    document_ref,
                    slugify(document_ref),
                    metadata={"source": document_ref},
                )
                self._upsert_edge(session, mission_node.node_key, "references_document", document_node.node_key)

            for artifact in artifacts:
                artifact_slug = f"{mission_id}-{slugify(artifact.kind)}-{slugify(artifact.title)}"
                artifact_node = self._upsert_node(
                    session,
                    "Artifact",
                    artifact.title,
                    artifact_slug,
                    metadata={"kind": artifact.kind, **artifact.metadata},
                )
                self._upsert_edge(session, mission_node.node_key, "produces_artifact", artifact_node.node_key)

            session.commit()

    def create_project_shell(
        self,
        mission_id: str,
        project_name: str,
        template_slug: Optional[str],
    ) -> None:
        with self.session_factory() as session:
            product_node = self._upsert_node(
                session,
                "Product",
                project_name,
                slugify(project_name),
                metadata={"status": "project-shell", "created_by_mission": mission_id},
            )
            project_node = self._upsert_node(
                session,
                "Project",
                project_name,
                slugify(project_name),
                metadata={"status": "project-shell", "template_slug": template_slug},
            )
            mission_node = self._upsert_node(session, "Mission", mission_id, mission_id)
            self._upsert_edge(session, mission_node.node_key, "creates_project_shell", project_node.node_key)
            self._upsert_edge(session, product_node.node_key, "contains_project", project_node.node_key)
            session.commit()

    def snapshot(self, limit: int = 80) -> GraphSnapshot:
        with self.session_factory() as session:
            nodes = session.execute(
                select(GraphNodeRecord).order_by(GraphNodeRecord.kind, GraphNodeRecord.name).limit(limit)
            ).scalars()
            edges = session.execute(
                select(GraphEdgeRecord).order_by(GraphEdgeRecord.created_at.desc()).limit(limit)
            ).scalars()

            node_views = [
                GraphNodeView(
                    node_key=node.node_key,
                    kind=node.kind,
                    name=node.name,
                    slug=node.slug,
                    external_id=node.external_id,
                    metadata=node.attributes or {},
                )
                for node in nodes
            ]
            edge_views = [
                GraphEdgeView(
                    source_key=edge.source_key,
                    relation=edge.relation,
                    target_key=edge.target_key,
                    metadata=edge.attributes or {},
                )
                for edge in edges
            ]

        counts = Counter(node.kind for node in node_views)
        return GraphSnapshot(counts=dict(counts), nodes=node_views, edges=edge_views)

    def _repository_node_from_reference(self, session, repo_reference: str) -> GraphNodeRecord:
        path_candidate = Path(repo_reference).expanduser()
        if not path_candidate.is_absolute():
            path_candidate = (self.settings.workspace_root / repo_reference).resolve()

        name = path_candidate.name if path_candidate.exists() else repo_reference
        metadata = {"path": str(path_candidate)} if path_candidate.exists() else {"reference": repo_reference}
        if path_candidate.exists():
            hub_manifest = self.catalog.project_manifests.get(name)
            repo_instructions = discover_repo_instructions(
                path_candidate,
                hub_manifest.instruction_hints if hub_manifest else None,
            )
            metadata.update(
                {
                    "has_agents": bool(repo_instructions.agents_paths),
                    "has_skills": bool(repo_instructions.skill_slugs),
                    "instruction_paths": sorted(set(repo_instructions.agents_paths + repo_instructions.skill_paths)),
                    "skill_slugs": repo_instructions.skill_slugs,
                }
            )
        repo_node = self._upsert_node(
            session,
            "Repository",
            name,
            slugify(name),
            metadata=metadata,
        )

        local_env = self._upsert_node(session, "Environment", "Local Workspace", "local-workspace")
        self._upsert_edge(session, local_env.node_key, "hosts_repository", repo_node.node_key, metadata=metadata)
        return repo_node

    def _upsert_node(
        self,
        session,
        kind: str,
        name: str,
        slug: str,
        metadata: Optional[dict] = None,
        external_id: Optional[str] = None,
    ) -> GraphNodeRecord:
        node_key = f"{kind.lower()}:{slug}"
        existing = session.get(GraphNodeRecord, node_key)
        if existing:
            merged = dict(existing.attributes or {})
            if metadata:
                merged.update(metadata)
            existing.name = name
            existing.external_id = external_id or existing.external_id
            existing.attributes = merged
            return existing

        record = GraphNodeRecord(
            node_key=node_key,
            kind=kind,
            name=name,
            slug=slug,
            external_id=external_id,
            attributes=metadata or {},
        )
        session.add(record)
        return record

    def _upsert_edge(
        self,
        session,
        source_key: str,
        relation: str,
        target_key: str,
        metadata: Optional[dict] = None,
    ) -> None:
        if edge_exists(session, source_key, relation, target_key):
            return
        session.add(
            GraphEdgeRecord(
                source_key=source_key,
                relation=relation,
                target_key=target_key,
                attributes=metadata or {},
            )
        )
