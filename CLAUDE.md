# CLAUDE.md

## Development Philosophy
IMPORTANT: Library-first development. Use foundational libraries and their proven methods before writing custom code. If custom code is required, explain why and get user approval before proceeding.

## Foundational Libraries
- langchain
- langsmith
- langgraph
- fastapi
- uvicorn
- boto3

## Workflow Rules
- Test during development AND at feature completion — tests must exercise actual code paths
- Use up to 3 sub-agents to parallelize tasks (coding, testing, documentation, etc)
- Use `./claude-temp/` for intermediate/debugging files; clean up on completion
- Update `./documentation/` upon feature completion
- Use MCP server `context7` when planning to verify current library best practices
- Plans must take a holistic view to ensure alignment with project goals and architecture

## On Completion
- Summarize any deviations from the approved plan
- Confirm documentation updated
- Confirm temp files cleaned

## Project Overview
This is the `collections-local` project.

## Development Commands
No build system or package manager has been configured yet. Update this section once the project structure is established.
