/* workflow-editor.js - serialisation helpers for workflow Markdown documents */
(function () {
  function nodeTypeForLegacy(type) {
    if (type === "agent") return "agent.run";
    if (type === "input" || type === "file_input") return "file.input";
    if (type === "output") return "output.results_display";
    if (type === "file_output") return "file.output";
    return type || "agent.run";
  }

  function normaliseNode(node, index) {
    const type = nodeTypeForLegacy(node.type);
    const defaults = window.WorkflowNodeRegistry?.defaultParameters(type) || {};
    const parameters = Object.assign({}, defaults, node.parameters || node.config || {});
    const position = node.position || { x: node.x ?? 80 + index * 280, y: node.y ?? 120 };
    return {
      id: String(node.id || node.step_id || `node_${index + 1}`),
      type,
      name: node.name || node.label || String(node.id || `Node ${index + 1}`),
      typeVersion: node.typeVersion || 1,
      position,
      parameters,
      disabled: Boolean(node.disabled),
      continueOnFail: Boolean(node.continueOnFail || node.continue_on_fail),
    };
  }

  function normaliseEdge(edge, index) {
    return {
      id: String(edge.id || `edge_${index + 1}`),
      source: String(edge.source || edge.from || ""),
      target: String(edge.target || edge.to || ""),
      sourceHandle: String(edge.sourceHandle || edge.source_handle || "out"),
      targetHandle: String(edge.targetHandle || edge.target_handle || "in"),
    };
  }

  function deserializeWorkflowEditor(docOrDefinition, sourceDoc) {
    const doc = sourceDoc || {};
    const steps = doc.nodes || docOrDefinition?.draft_steps || [];
    const edges = doc.edges || docOrDefinition?.metadata?._canvas_edges || [];
    return {
      nodes: steps.map(normaliseNode),
      edges: edges.map(normaliseEdge),
      canvas: doc.canvas || docOrDefinition?.metadata?.canvas || { zoom: 1, scroll: { x: 0, y: 0 }, selectedNodeIds: [] },
      selectedNodeIds: doc.canvas?.selectedNodeIds || [],
    };
  }

  function serializeWorkflowEditor(state, baseDoc) {
    const canvas = Object.assign({ zoom: 1, scroll: { x: 0, y: 0 }, selectedNodeIds: [] }, state.canvas || {});
    canvas.selectedNodeIds = state.selectedNodeIds || canvas.selectedNodeIds || [];
    return Object.assign({}, baseDoc || {}, {
      schema_version: 1,
      nodes: (state.nodes || []).map(normaliseNode),
      edges: (state.edges || []).map(normaliseEdge),
      canvas,
    });
  }

  window.deserializeWorkflowEditor = deserializeWorkflowEditor;
  window.serializeWorkflowEditor = serializeWorkflowEditor;
})();
