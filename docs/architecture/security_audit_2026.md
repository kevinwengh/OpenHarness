export const meta = {
  name: 'openharness-security-audit',
  description: 'Multi-dimensional security audit of OpenHarness codebase',
  phases: [
    { title: 'Find', detail: 'Parallel agents search for issues across dimensions' },
    { title: 'Verify', detail: 'Adversarial verification of findings' },
    { title: 'Report', detail: 'Synthesize and rank findings' },
  ],
}

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          file: { type: 'string' },
          line: { type: 'integer' },
          severity: { enum: ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'] },
          summary: { type: 'string' },
          code: { type: 'string' },
          input_source: { type: 'string' },
          fix_recommendation: { type: 'string' },
        },
        required: ['file', 'line', 'severity', 'summary', 'code'],
      },
    },
  },
  required: ['findings'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { enum: ['CONFIRMED', 'DISMISSED', 'ESCALATED'] },
    reasoning: { type: 'string' },
    finding: { type: 'object' },
  },
  required: ['verdict', 'reasoning'],
}

const REPORT_SCHEMA = {
  type: 'object',
  properties: {
    executive_summary: { type: 'string' },
    findings_table: { type: 'array', items: { type: 'object' } },
    detailed_findings: { type: 'array', items: { type: 'object' } },
    informational_items: { type: 'array', items: { type: 'object' } },
    overall_risk_assessment: { type: 'string' },
  },
  required: ['executive_summary', 'findings_table', 'detailed_findings', 'informational_items', 'overall_risk_assessment'],
}

// Phase 1 — Parallel finders, each covering a different security dimension
const DIMENSIONS = [
  { key: 'shell-injection', prompt: `Audit the OpenHarness codebase at /home/kevinwen/repos/OpenHarness for SHELL COMMAND INJECTION risks. Focus on:\n- src/openharness/tools/bash.py (BashTool.execute) — how user input reaches subprocess calls\n- src/openharness/hooks/executor.py — shell command hooks with $ARGUMENTS substitution\n- Any place where f-strings, format(), or string concat builds a shell command from user-controlled data\n- subprocess.run / subprocess.Popen / os.system usage patterns\nShow exact code lines, the untrusted input source, and any sanitization that exists (or doesn't).` },
  { key: 'path-traversal', prompt: `Audit the OpenHarness codebase at /home/kevinwen/repos/OpenHarness for FILE PATH TRAVERSAL risks. Focus on:\n- src/openharness/tools/read.py, write.py, edit.py — how file paths are validated before access\n- Any glob/grep tool that takes user-supplied patterns which could escape the working directory\n- The sandbox module at src/openharness/sandbox/ — chroot/container isolation logic\n- Path normalization: does it strip ../ sequences? Does it resolve symlinks? Show exact code with line numbers.` },
  { key: 'credential-exposure', prompt: `Audit the OpenHarness codebase at /home/kevinwen/repos/OpenHarness for CREDENTIAL AND SECRET EXPOSURE risks. Focus on:\n- src/openharness/auth/ — how API keys, tokens, passwords are stored and retrieved\n- src/openharness/api/ — where credentials are passed (headers, env vars, command line)\n- Logging: does anything print or log sensitive values? Search for f"api_key=", f"token=", password=, secret= in format strings\n- Environment variable passing to subprocesses — could secrets leak into child process env?\n- Any credential forwarding between services (e.g., from CLI to backend host)\nShow exact code lines and the exposure vector.` },
  { key: 'permission-bypass', prompt: `Audit the OpenHarness codebase at /home/kevinwen/repos/OpenHarness for PERMISSION MODEL ENFORCEMENT GAPS. Focus on:\n- src/openharness/permissions/ — how permission modes (default/full_auto/plan) are checked\n- Are there tools that bypass permission checks? Search for execute() calls that don't go through the checker.\n- The plan mode: does it actually BLOCK writes or just warn?\n- Path rules and denied commands: can they be circumvented via tool chaining or indirect execution?\n- Plugin hook execution: do plugins get elevated permissions?\nShow exact code with line numbers for each gap.` },
  { key: 'plugin-safety', prompt: `Audit the OpenHarness codebase at /home/kevinwen/repos/OpenHarness for PLUGIN AND HOOK EXECUTION SAFETY. Focus on:\n- src/openharness/plugins/ — how plugins are loaded, validated, and sandboxed\n- Do plugins get access to the full RuntimeBundle (API client, tool registry, permissions)?\n- The hook system: can a malicious or buggy hook crash the main process?\n- src/openharness/mcp/ — MCP server connection: stdio transport risks, what happens if an MCP server sends arbitrary commands\n- Plugin manifests: is there schema validation? Can plugins declare hooks for any event including session_start with dangerous commands?\nShow exact code lines and risk assessment.` },
  { key: 'input-sanitization', prompt: `Audit the OpenHarness codebase at /home/kevinwen/repos/OpenHarness for INPUT SANITIZATION AND PROTOCOL RISK. Focus on:\n- src/openharness/ui/backend_host.py — how incoming OHJSON: protocol messages are parsed and dispatched\n- Are message types validated against the FrontendRequest enum? Can an attacker craft a message with a malformed type field?\n- The ReactBackendHost request queue: is there rate limiting or DoS protection?\n- src/openharness/ui/react_launcher.py — what gets passed to subprocess env vars (OPENHARNESS_FRONTEND_CONFIG)\n- Any deserialization that doesn't use strict typing (json.loads without schema validation?)\nShow exact code lines and risk assessment.` },
]

const results = await parallel(DIMENSIONS.map(d => () =>
  agent(
    `You are a senior security engineer. Audit the OpenHarness codebase at /home/kevinwen/repos/OpenHarness for ${d.key.toUpperCase().replace('-', ' ')} risks.\n\n${d.prompt}\n\nFor each finding, provide:\n1. File path and line numbers\n2. The vulnerable code snippet (exact lines)\n3. The untrusted input source that reaches it\n4. Whether any sanitization currently exists\n5. Severity: CRITICAL / HIGH / MEDIUM / LOW / INFO
6. A brief fix recommendation`,
    { schema: FINDINGS_SCHEMA, phase: 'Find' }
  )
))

const all = results.filter(Boolean).flatMap(r => r.findings)

// Phase 2 — Adversarial verification
const verified = await parallel(all.map(f => () =>
  agent(
    `You are an adversarial security reviewer. Verify this finding:\n\nFile: ${f.file}\nSeverity: ${f.severity}\nSummary: ${f.summary}\nCode: ${f.code}\nInput source: ${f.input_source}\nFix: ${f.fix_recommendation}\n\nDo you agree this is a real vulnerability? Consider:\n- Is the input truly user-controlled, or is it internal/validated?\n- Are there existing mitigations you missed?\n- Could this actually be exploited in practice given the architecture?\n\nRespond with your verdict (CONFIRMED / DISMISSED / ESCALATED) and reasoning.`,
    { schema: VERDICT_SCHEMA, phase: 'Verify' }
  )
))

const confirmed = verified.filter(v => v.verdict === 'CONFIRMED').map(v => ({
  ...v.finding,
  verdict: v.verdict,
}))

// Phase 3 — Synthesize report
const report = await agent(
  `Given these VERIFIED security findings from OpenHarness codebase audit:\n\n${JSON.stringify(confirmed, null, 2)}\n\nProduce a final ranked report with:\n1. Executive summary (2-3 sentences)\n2. Table of confirmed findings: Severity | File:Line | Summary | Exploitability | Fix Priority\n3. For each CRITICAL/HIGH finding: detailed description, attack scenario, and specific remediation code suggestions\n4. Low-severity / informational items grouped separately\n5. Overall risk assessment for a security-conscious maintainer`,
  { schema: REPORT_SCHEMA }
)

return report
