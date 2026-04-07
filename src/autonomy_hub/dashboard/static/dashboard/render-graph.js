import {
  escapeHtml,
  formatList,
  renderPanelState,
  truncate,
} from "./shared.js";

const NODE_PRIORITY = {
  Mission: 0,
  Repository: 1,
  Product: 2,
  Document: 3,
  Artifact: 4,
  Environment: 5,
  CapabilityPolicy: 6,
};

function sortNodes(nodes) {
  return [...nodes].sort((left, right) => {
    const leftRank = NODE_PRIORITY[left.kind] ?? 99;
    const rightRank = NODE_PRIORITY[right.kind] ?? 99;
    if (leftRank !== rightRank) {
      return leftRank - rightRank;
    }
    return left.name.localeCompare(right.name);
  });
}

function renderGraphList(title, items, kind, remaining) {
  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <p class="eyebrow">${escapeHtml(kind === "nodes" ? "Nodos" : "Relaciones")}</p>
          <h2>${escapeHtml(title)}</h2>
        </div>
      </div>
      <div class="graph-list">
        ${
          items.length
            ? items.join("")
            : `<p class="empty-copy">No hay ${escapeHtml(kind === "nodes" ? "nodos" : "relaciones")} visibles.</p>`
        }
      </div>
      ${
        remaining > 0
          ? `
            <button
              type="button"
              class="ghost show-more-button"
              data-show-more="${escapeHtml(kind)}"
              data-focus-id="show-more:${escapeHtml(kind)}"
            >
              ${escapeHtml(`Mostrar ${remaining} más`)}
            </button>
          `
          : ""
      }
    </section>
  `;
}

export function renderGraphPanel({
  mission,
  graph,
  graphError,
  visibleGraphNodes,
  visibleGraphEdges,
}) {
  if (!mission) {
    return renderPanelState(
      "empty",
      "Sin misión enfocada",
      "Seleccioná una misión para bajar a productos, repos, documentos y relaciones."
    );
  }

  if (graphError && !graph) {
    return renderPanelState(
      "warning",
      "El grafo no se pudo refrescar",
      graphError,
      '<div class="button-row"><button type="button" data-manual-refresh class="secondary" data-focus-id="manual-refresh">Actualizar</button></div>'
    );
  }

  if (!graph?.nodes?.length) {
    return renderPanelState(
      "empty",
      "Contexto vacío",
      "La misión no tiene nodos relacionados visibles en el grafo local todavía."
    );
  }

  const nodeMap = new Map(graph.nodes.map((node) => [node.node_key, node]));
  const sortedNodes = sortNodes(graph.nodes);
  const visibleNodes = sortedNodes.slice(0, visibleGraphNodes);
  const visibleEdges = graph.edges.slice(0, visibleGraphEdges);
  const nodesRemaining = Math.max(0, sortedNodes.length - visibleGraphNodes);
  const edgesRemaining = Math.max(0, graph.edges.length - visibleGraphEdges);

  const nodeItems = visibleNodes.map((node) => {
    return `
      <article class="graph-row">
        <strong>${escapeHtml(node.kind)}</strong>
        <span>${escapeHtml(truncate(node.name, 84))}</span>
      </article>
    `;
  });

  const edgeItems = visibleEdges.map((edge) => {
    const source = nodeMap.get(edge.source_key)?.name || edge.source_key;
    const target = nodeMap.get(edge.target_key)?.name || edge.target_key;
    return `
      <article class="graph-row">
        <strong>${escapeHtml(edge.relation)}</strong>
        <span>${escapeHtml(`${truncate(source, 42)} → ${truncate(target, 42)}`)}</span>
      </article>
    `;
  });

  return `
    <div class="section-stack">
      ${
        graphError
          ? `
            <article class="inline-alert tone-warning">
              <strong>Grafo parcialmente degradado</strong>
              <p>${escapeHtml(graphError)}</p>
            </article>
          `
          : ""
      }

      <section class="panel">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Graph Overview</p>
            <h2>Contexto útil de la misión</h2>
          </div>
          <p class="body-muted">Grafo global filtrado localmente por la misión seleccionada.</p>
        </div>

        <div class="signal-grid">
          <article class="signal-card">
            <span>Nodos visibles</span>
            <strong>${escapeHtml(graph.nodes.length)}</strong>
          </article>
          <article class="signal-card">
            <span>Relaciones</span>
            <strong>${escapeHtml(graph.edges.length)}</strong>
          </article>
          <article class="signal-card">
            <span>Repos</span>
            <strong class="is-code" translate="no">${escapeHtml(formatList(mission.linked_repositories, "greenfield"))}</strong>
          </article>
          <article class="signal-card">
            <span>Productos</span>
            <strong>${escapeHtml(formatList(mission.linked_products, "sin productos"))}</strong>
          </article>
          <article class="signal-card is-wide">
            <span>Distribución del contexto</span>
            <strong>${escapeHtml(
              Object.entries(graph.counts)
                .sort((left, right) => left[0].localeCompare(right[0]))
                .map(([key, value]) => `${key}: ${value}`)
                .join(" · ")
            )}</strong>
          </article>
        </div>
      </section>

      <div class="panel-grid panel-grid-2">
        ${renderGraphList("Nodos priorizados", nodeItems, "nodes", nodesRemaining)}
        ${renderGraphList(
          "Relaciones visibles",
          edgeItems,
          "edges",
          edgesRemaining
        )}
      </div>
    </div>
  `;
}
