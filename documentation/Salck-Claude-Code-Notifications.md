# Collections App - Claude Code Instructions

## Project Overview
[your project description]

## Development Guidelines
[your development guidelines]

## Slack Notifications

Stay in touch with me about progress and blockers using the Slack notification script.

### When to Notify

**Questions (--type question):**
- Design decisions: "Should I use SQLite or PostgreSQL for local development?"
- API design: "RESTful endpoints or GraphQL for this feature?"
- Library choices: "Use library X or Y for image processing?"

**Errors (--type error):**
- Build failures you can't auto-resolve
- Missing credentials or environment setup
- Dependency conflicts

**Success (--type task_complete):**
- Major feature completed and tested
- All CI/CD pipeline passing
- Deployment successful

### Script Location

The notification script is at `~/bin/notify_slack` or use:
```bash
python /path/to/notify_slack.py "message" --type question --task "current task"
```

### Response Time

I typically respond within [your timeframe]. If blocked, try to:
1. Document the blocker clearly in the notification
2. Continue with other independent tasks
3. Leave detailed notes for when I respond