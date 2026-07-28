`corpus/` holds the private, gitignored posting corpus, and only this README is tracked. Each posting is a plain text or markdown file in this directory. `golden.json` maps a posting filename to the human-validated verdict per demand and drives `pytest -m provider`.

```json
{
  "senior-ai-engineer.md": {
    "RAG": "strong",
    "Kubernetes": "gap"
  }
}
```
