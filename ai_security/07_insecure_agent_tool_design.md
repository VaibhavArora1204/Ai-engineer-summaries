# 07 — Insecure Agent Tool Design

## Why Agents Convert Every Other Attack Into Real-World Damage

```
Without agents:
  Prompt injection → wrong text in a response.
  Jailbreak → harmful text in a response.
  Impact: bad output. No real-world consequences beyond the screen.

With agents:
  Prompt injection + file access → deleted/modified files.
  Prompt injection + email tool → exfiltrated data sent directly.
  Prompt injection + database write → corrupted/deleted records.
  Prompt injection + HTTP tool → arbitrary outbound requests.
  Prompt injection + shell access → remote code execution.
  
  The agent is the weapon. The injection is the trigger.
  Every tool permission is a capability you're handing to any 
  attacker who successfully injects your system.
```

Every vulnerability in Files 01-04 (injection, indirect injection, exfiltration, jailbreaking) escalates from "bad output" to "real damage" the moment you add agent tools. The tool design is the primary attack surface, not the model.

## OWASP LLM06: Excessive Agency

The core pattern: agent given more permissions than any single task requires.

```
Examples of excessive agency:
  Task: "Read and summarize this document."
  Agent permissions: read + write + delete files.
  Required: read only. Write and delete are attack surface for free.
  
  Task: "Check my calendar for conflicts."
  Agent permissions: calendar read + email send + contacts access.
  Required: calendar read only. Email send = exfiltration channel.
  
  Task: "Query the database for sales figures."
  Agent permissions: SELECT + INSERT + UPDATE + DELETE on all tables.
  Required: SELECT on sales table only.
  Every unnecessary permission is a capability the attacker inherits.
```

## Tool Design as Primary Attack Surface

### Dangerous Tool Patterns

```python
# DANGEROUS: shell execution with string input
def execute_shell(command: str) -> str:
    return subprocess.run(command, shell=True, capture_output=True).stdout
# Injection payload becomes the shell command. This is RCE.

# DANGEROUS: unrestricted file deletion
def delete_file(path: str) -> str:
    os.remove(path)
    return f"Deleted {path}"
# Injection controls what gets deleted. Path traversal trivial.

# DANGEROUS: unrestricted email
def send_email(to: str, subject: str, body: str) -> str:
    smtp.send(to, subject, body)
    return "Sent"
# Injection sends arbitrary emails. Zero confirmation. Exfiltration channel.

# DANGEROUS: unrestricted HTTP
def http_request(url: str, method: str, body: str) -> str:
    return requests.request(method, url, data=body).text
# Injection makes arbitrary HTTP requests. Exfiltration, SSRF, anything.
```

### Safe Tool Patterns

```python
# SAFE: scoped file read with directory allowlist
def read_file(path: str, allowed_dirs: list[str]) -> str:
    resolved = Path(path).resolve()
    if not any(resolved.is_relative_to(d) for d in allowed_dirs):
        raise PermissionError(f"Access denied: {path}")
    return resolved.read_text()

# SAFE: structured query with parameterization
def query_sales(year: int, region: str) -> list[dict]:
    # Parameters are typed and validated — not arbitrary SQL
    return db.execute(
        "SELECT * FROM sales WHERE year = %s AND region = %s",
        (year, region)
    )

# SAFE: email with confirmation gate
def draft_email(to: str, subject: str, body: str) -> str:
    draft_id = save_draft(to, subject, body)
    return f"Draft saved as {draft_id}. Requires human approval to send."
    # Human reviews and clicks send. Injection can draft but not send.

# SAFE: HTTP restricted to allowlist
ALLOWED_HOSTS = {"api.internal.com", "data.internal.com"}
def http_get(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname not in ALLOWED_HOSTS:
        raise PermissionError(f"Blocked: {parsed.hostname}")
    return requests.get(url).text
```

## Principle of Least Privilege — Concrete Application

```
For every tool, ask three questions:
  1. Does this task REQUIRE this tool? 
     If no → don't give the agent access.
  2. Does this tool need write/mutate capability?
     If no → make it read-only.
  3. Can the parameters be structured/typed instead of free strings?
     If yes → use enums, validated types, allowlists.

Irreversible actions that ALWAYS require human confirmation:
  - Send email / message
  - Delete file / database record
  - Charge payment / create invoice
  - Publish content / deploy code
  - Modify production database
  - Make external API calls with side effects
  
  "Are you sure?" prompts from the agent to the user don't count.
  The confirmation must happen OUTSIDE the agent loop — in your 
  application UI, not in the LLM conversation. The LLM can be 
  injected into confirming its own actions.
```

## Sandbox Isolation Architecture

```
Agent execution environment:

  Network:
    Outbound: DENY ALL except explicitly allowlisted endpoints.
    Enforced at: container network policy / firewall rules.
    NOT at: application code (can be bypassed by injection).
  
  Filesystem:
    Scoped to: /agent/workspace/ only.
    No access to: system files, other users' data, config files.
    Enforced at: container mount configuration or chroot.
  
  Database:
    Connection: read-only unless write is explicitly required for the task.
    Scoped to: specific tables/views, not full database access.
    Enforced at: database user permissions (separate DB user for agent).
  
  Process:
    Cannot spawn child processes or execute shell commands 
    unless shell execution is an explicit, scoped, audited tool.
    Enforced at: container security policy (no-new-privileges).
```

## Tool Call Audit Logging

```
Every tool call must log:
  - Timestamp
  - Tool name
  - Full parameters (sanitized for PII in logs, but complete)
  - Calling context (what prompt/conversation triggered this)
  - Tool response
  - User/tenant ID
  - Session ID

Alert on:
  - Tool calls outside normal usage patterns (time of day, frequency)
  - High volume of tool calls in short window (agent loop gone wild)
  - Tool calls with parameters matching known injection patterns
  - Any tool call to a tool that hasn't been called before in this session type
  
Incident response:
  - Can you stop a running agent mid-execution? (kill switch)
  - Can you revert the agent's actions? (undo capability)
  - Who gets paged? What's the escalation path?
  - What gets shut down while investigating?
  
  If you can't answer these questions, you don't have incident 
  response for your agent system. Build it before you need it.
```
