/* workflow-registry.js - registry for the vanilla workflow editor */
(function () {
  const parameterTypes = {
    string: "text",
    number: "number",
    boolean: "checkbox",
    select: "select",
    code: "textarea",
    json: "textarea",
    file: "text",
    agent: "select",
    llm: "select",
    mcp: "select",
  };

  const nodes = {
    "trigger.manual": {
      type: "trigger.manual",
      label: "Manual Trigger",
      category: "Triggers",
      accent: "#2f80ed",
      inputs: [],
      outputs: [{ id: "out", label: "Payload", type: "json" }],
      parameters: [{ key: "payload", label: "Payload", type: "json", default: {} }],
    },
    "core.set": {
      type: "core.set",
      label: "Set",
      category: "Core",
      accent: "#27ae60",
      inputs: [{ id: "in", label: "Input", type: "any" }],
      outputs: [{ id: "out", label: "Value", type: "any" }],
      parameters: [
        { key: "key", label: "Key", type: "string", default: "value" },
        { key: "value", label: "Value", type: "string", default: "" },
      ],
    },
    "control.if_else": {
      type: "control.if_else",
      label: "If / Else",
      category: "Control",
      accent: "#f2994a",
      inputs: [{ id: "in", label: "Input", type: "any" }],
      outputs: [{ id: "true", label: "True", type: "flow" }, { id: "false", label: "False", type: "flow" }],
      parameters: [{ key: "condition", label: "Condition", type: "code", default: "" }],
    },
    "control.merge": {
      type: "control.merge",
      label: "Merge",
      category: "Control",
      accent: "#b87333",
      inputs: [{ id: "in", label: "Input", type: "any" }],
      outputs: [{ id: "out", label: "Merged", type: "json" }],
      parameters: [],
    },
    "agent.run": {
      type: "agent.run",
      label: "Run Agent",
      category: "Agents",
      accent: "#9b51e0",
      inputs: [{ id: "in", label: "Input", type: "any" }],
      outputs: [{ id: "out", label: "Message", type: "text" }],
      parameters: [
        { key: "agent", label: "Agent", type: "agent", options: ["chat", "codegen"], default: "chat" },
        { key: "instruction", label: "Instruction", type: "code", default: "" },
      ],
    },
    "file.input": {
      type: "file.input",
      label: "File Input",
      category: "Files",
      accent: "#6fcf97",
      inputs: [{ id: "in", label: "Trigger", type: "flow" }],
      outputs: [{ id: "out", label: "Preview", type: "file" }],
      parameters: [
        { key: "path", label: "Path", type: "file", default: "{{inputs.file_path}}" },
        { key: "file_type", label: "File Type", type: "select", options: ["text", "markdown", "json", "csv"], default: "text" },
      ],
    },
    "file.output": {
      type: "file.output",
      label: "File Output",
      category: "Outputs",
      accent: "#56ccf2",
      inputs: [{ id: "in", label: "Value", type: "any" }],
      outputs: [],
      parameters: [
        { key: "destination", label: "Destination", type: "select", options: ["artifact", "screen"], default: "artifact" },
        { key: "filename", label: "Filename", type: "string", default: "result.txt" },
        { key: "format", label: "Format", type: "select", options: ["text", "json"], default: "text" },
        { key: "template", label: "Template", type: "code", default: "{{last_output.message}}" },
      ],
    },
    "output.results_display": {
      type: "output.results_display",
      label: "Results",
      category: "Outputs",
      accent: "#56ccf2",
      inputs: [{ id: "in", label: "Value", type: "any" }],
      outputs: [],
      parameters: [
        { key: "destination", label: "Destination", type: "select", options: ["screen", "artifact"], default: "screen" },
        { key: "format", label: "Format", type: "select", options: ["text", "json"], default: "text" },
        { key: "template", label: "Template", type: "code", default: "{{last_output.message}}" },
      ],
    },
    "file.operations": {
      type: "file.operations",
      label: "File Operation",
      category: "Files",
      accent: "#6fcf97",
      inputs: [{ id: "in", label: "Input", type: "any" }],
      outputs: [{ id: "out", label: "Result", type: "file" }],
      parameters: [
        { key: "operation", label: "Operation", type: "select", options: ["read", "write", "append"], default: "read" },
        { key: "path", label: "Path", type: "file", default: "" },
      ],
    },
    "utility.http_request": {
      type: "utility.http_request",
      label: "HTTP Request",
      category: "Utilities",
      accent: "#eb5757",
      inputs: [{ id: "in", label: "Input", type: "any" }],
      outputs: [{ id: "out", label: "Response", type: "json" }],
      parameters: [
        { key: "method", label: "Method", type: "select", options: ["GET", "POST", "PUT", "PATCH"], default: "GET" },
        { key: "url", label: "URL", type: "string", default: "" },
      ],
    },
  };

  const extraTemplates = [
    ["llm.generate", "LLM Generate", "LLM"],
    ["llm.summarize", "Summarize", "LLM"],
    ["mcp.tool", "MCP Tool", "MCP"],
    ["data.transform", "Transform", "Data"],
    ["utility.sleep", "Sleep", "Utilities"],
    ["utility.transform", "Transform", "Utilities"],
    ["safety.pass_fail", "Pass / Fail", "Safety"],
  ];
  extraTemplates.forEach(([type, label, category]) => {
    nodes[type] = {
      type,
      label,
      category,
      accent: "#828282",
      inputs: [{ id: "in", label: "Input", type: "any" }],
      outputs: [{ id: "out", label: "Output", type: "any" }],
      parameters: [{ key: "notes", label: "Notes", type: "string", default: "" }],
      implemented: false,
    };
  });

  const templates = [
    { id: "blank", label: "Blank", nodes: [], edges: [] },
    { id: "basic-agent", label: "Basic Agent", nodes: ["trigger.manual", "agent.run", "output.results_display"] },
    { id: "simulated-file-agent", label: "Sim File Agent", nodes: ["trigger.manual", "file.input", "agent.run", "output.results_display"] },
    { id: "branch", label: "Branch", nodes: ["trigger.manual", "control.if_else", "output.results_display"] },
    { id: "http", label: "HTTP", nodes: ["trigger.manual", "utility.http_request", "output.results_display"] },
    { id: "file", label: "File", nodes: ["trigger.manual", "file.input", "agent.run", "file.output"] },
    { id: "set", label: "Set Value", nodes: ["trigger.manual", "core.set", "output.results_display"] },
    { id: "merge", label: "Merge", nodes: ["trigger.manual", "control.merge", "output.results_display"] },
    { id: "llm", label: "LLM Draft", nodes: ["trigger.manual", "llm.generate", "output.results_display"] },
    { id: "mcp", label: "MCP Tool", nodes: ["trigger.manual", "mcp.tool", "output.results_display"] },
    { id: "safety", label: "Safety", nodes: ["trigger.manual", "safety.pass_fail", "output.results_display"] },
    { id: "transform", label: "Transform", nodes: ["trigger.manual", "data.transform", "output.results_display"] },
    { id: "sleep", label: "Delay", nodes: ["trigger.manual", "utility.sleep", "output.results_display"] },
    { id: "summarize", label: "Summarize", nodes: ["trigger.manual", "llm.summarize", "output.results_display"] },
    { id: "agent-file", label: "Agent + File", nodes: ["trigger.manual", "agent.run", "file.operations", "output.results_display"] },
    { id: "http-agent", label: "HTTP + Agent", nodes: ["trigger.manual", "utility.http_request", "agent.run", "output.results_display"] },
  ];

  window.WorkflowNodeRegistry = {
    nodes,
    templates,
    parameterTypes,
    categories: Array.from(new Set(Object.values(nodes).map((node) => node.category))).sort(),
    get(type) {
      return nodes[type] || nodes[type && type.replace(/^agent$/, "agent.run")] || null;
    },
    list() {
      return Object.values(nodes);
    },
    defaultParameters(type) {
      const def = this.get(type);
      const result = {};
      (def?.parameters || []).forEach((param) => { result[param.key] = param.default ?? ""; });
      return result;
    },
  };
})();
