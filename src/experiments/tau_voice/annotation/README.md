# Annotation Pipeline

Export simulation results to standalone HTML pages for expert qualitative error analysis.

## Quick Start

```bash
# Export failed simulations
uv run python src/experiments/tau_voice/annotation/export_html.py \
  --batch-name round1_retail \
  --results data/simulations/my_experiment/results.json \
  --filter-reward "< 1"

# Open in browser
open data/annotations/round1_retail/index.html
```

## Filtering

```bash
--filter-reward "< 1"          # by reward (supports <, <=, >, >=, ==, !=)
--filter-tasks 9,16,31         # by task ID
--filter-trials 0,1            # by trial number
--max-items 50                 # cap number of exports
--domain airline               # override auto-detected domain
```

Run `--help` for full CLI reference.

## Output

```
html_export/
├── index.html              # Landing page with progress tracking
├── task_9_sim_f61e6c15/
│   ├── index.html           # Annotation page
│   └── audio.wav            # Audio (if available)
└── ...
```

## Annotator Workflow

1. Open `index.html` in a browser
2. Click a simulation to open its annotation page
3. Review the conversation, listen to audio, check the LLM judge review
4. Fill in the annotation form (error source, error type, notes)
5. Mark as Complete
6. When finished, click "Export All to CSV" on the index page

Annotations are saved in browser localStorage. Export to CSV regularly as a backup.
