# Using tmux for Long-Running Analysis

## Why tmux?
tmux allows processes to continue running even if you disconnect from the codespace. This is perfect for long-running image analysis tasks.

## Quick Start

### 1. Start a new tmux session
```bash
tmux new -s analysis
```

### 2. Start the API server in the first pane
```bash
cd /workspaces/collections-local
uvicorn main:app --reload
```

### 3. Split the window to create a second pane
Press: `Ctrl+b` then `%` (creates vertical split)
Or: `Ctrl+b` then `"` (creates horizontal split)

### 4. Navigate to the second pane
Press: `Ctrl+b` then `→` (or `←`, `↑`, `↓` to move between panes)

### 5. Run the analysis script in the second pane
```bash
cd /workspaces/collections-local
python testing/resume_batch_analyze.py
```

### 6. Detach from the session (leave it running)
Press: `Ctrl+b` then `d`

Your processes continue running in the background!

## Reconnecting

### List all tmux sessions
```bash
tmux ls
```

### Reattach to your session
```bash
tmux attach -t analysis
```

Or simply:
```bash
tmux a
```

## Useful tmux Commands

| Action | Command |
|--------|---------|
| Create new session | `tmux new -s <name>` |
| List sessions | `tmux ls` |
| Attach to session | `tmux attach -t <name>` |
| Detach from session | `Ctrl+b` then `d` |
| Kill session | `tmux kill-session -t <name>` |
| Split horizontal | `Ctrl+b` then `"` |
| Split vertical | `Ctrl+b` then `%` |
| Navigate panes | `Ctrl+b` then arrow keys |
| Close current pane | `Ctrl+d` or type `exit` |
| Scroll in pane | `Ctrl+b` then `[` (q to exit scroll mode) |

## Resume Script Features

The `resume_batch_analyze.py` script:
- ✅ Automatically detects which analyses are missing
- ✅ Only runs analyses that haven't been completed
- ✅ Can be stopped and restarted safely
- ✅ Shows progress for each model configuration

## Example Workflow

```bash
# Start tmux session
tmux new -s analysis

# Start API (in first pane)
uvicorn main:app

# Split window (Ctrl+b then ")
# In second pane:
python testing/resume_batch_analyze.py

# Detach safely (Ctrl+b then d)
# Come back later with:
tmux attach -t analysis
```
