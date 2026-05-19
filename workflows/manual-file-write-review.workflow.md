# Manual File Write Review Demo

A simple end-to-end workflow demo:
`manual trigger -> file input -> write agent -> review agent -> human review -> final output`.

<!-- hermes-workflow:start -->
```json
{
  "schema_version": 1,
  "id": "manual-file-write-review-demo",
  "name": "Manual File Write Review Demo",
  "description": "Manual trigger flow with file input, writing, AI review, human review, and final output.",
  "default_profile": null,
  "inputs": [
    {
      "key": "topic",
      "type": "text"
    },
    {
      "key": "file_path",
      "type": "text"
    }
  ],
  "nodes": [
    {
      "id": "trigger_1",
      "type": "trigger.manual",
      "name": "Manual Trigger",
      "position": {
        "x": 80,
        "y": 140
      },
      "parameters": {
        "payload": {
          "topic": "{{inputs.topic}}",
          "file_path": "{{inputs.file_path}}"
        }
      }
    },
    {
      "id": "file_1",
      "type": "file.input",
      "name": "File Input",
      "position": {
        "x": 360,
        "y": 140
      },
      "parameters": {
        "path": "{{inputs.file_path}}",
        "file_type": "markdown"
      }
    },
    {
      "id": "write_agent",
      "type": "agent.run",
      "name": "Write Agent",
      "position": {
        "x": 640,
        "y": 140
      },
      "parameters": {
        "agent": "chat",
        "instruction": "Write a polished draft for topic '{{ inputs.topic }}' using the uploaded file context. Return clear, structured markdown."
      }
    },
    {
      "id": "review_agent",
      "type": "agent.run",
      "name": "Review Agent",
      "position": {
        "x": 920,
        "y": 140
      },
      "parameters": {
        "agent": "chat",
        "instruction": "Review the draft for quality, clarity, and factual consistency. Provide a concise reviewer summary and risks."
      }
    },
    {
      "id": "human_review",
      "type": "human.review",
      "name": "Human Review",
      "position": {
        "x": 1200,
        "y": 140
      },
      "parameters": {
        "title": "Human Approval Gate",
        "instructions": "Check writing quality and factual safety. Approve to continue, otherwise deny."
      }
    },
    {
      "id": "final_output",
      "type": "output.results_display",
      "name": "Final Output",
      "position": {
        "x": 1480,
        "y": 140
      },
      "parameters": {
        "destination": "screen",
        "format": "text",
        "template": "{{steps.review_agent.output.message}}"
      }
    }
  ],
  "edges": [
    {
      "id": "e1",
      "source": "trigger_1",
      "target": "file_1",
      "sourceHandle": "out",
      "targetHandle": "in"
    },
    {
      "id": "e2",
      "source": "file_1",
      "target": "write_agent",
      "sourceHandle": "out",
      "targetHandle": "in"
    },
    {
      "id": "e3",
      "source": "write_agent",
      "target": "review_agent",
      "sourceHandle": "out",
      "targetHandle": "in"
    },
    {
      "id": "e4",
      "source": "review_agent",
      "target": "human_review",
      "sourceHandle": "out",
      "targetHandle": "in"
    },
    {
      "id": "e5",
      "source": "human_review",
      "target": "final_output",
      "sourceHandle": "approved",
      "targetHandle": "in"
    }
  ],
  "outputs": [
    {
      "key": "final_message",
      "type": "text",
      "source": "final_output"
    }
  ],
  "canvas": {
    "zoom": 0.88,
    "scroll": {
      "x": -20,
      "y": 10
    },
    "selectedNodeIds": []
  }
}
```
<!-- hermes-workflow:end -->

