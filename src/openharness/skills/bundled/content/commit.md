# commit

Create clean, well-structured git commits.

## When to use

Use when the user asks to commit changes, create a PR, or prepare code for review.

## Workflow

1. Run `git status` and `git diff` to understand all changes
2. Analyze changes: categorize as feature, fix, refactor, docs, test, etc.
3. Draft a detailed, meaningful commit message that follows the repository's `AGENTS.md` policy:
   - Subject: `<type>(<optional-scope>): <imperative summary>`, specific and under 72 characters
   - Body (required): explain motivation, behavioral or contract impact, and important design,
     safety, compatibility, generated-asset, or trade-off considerations
   - Final `Validation:` section (required): list only checks actually run and their outcome, or
     state `Validation: Not run (<reason>)`
4. Stage only relevant files — never stage .env, credentials, or large binaries
5. Re-read the staged diff and create the commit

## Rules

- Prefer specific `git add <file>` over `git add -A`
- Never create a vague or subject-only commit; do not merely restate the changed file list
- Keep unrelated logical changes in separate commits
- Never fabricate validation results
- Never use `--no-verify` unless explicitly asked
- Never amend published commits unless explicitly asked
- If a pre-commit hook fails, fix the issue and create a NEW commit (don't --amend)
- Include `Co-Authored-By` if pair programming
- Preserve original authorship when integrating external work and explain agent-resolved conflicts
  in the merge commit body
