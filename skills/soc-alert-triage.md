# soc-alert-triage

Use for L1 triage of Wazuh / Sentinel / Defender alerts.

## Steps
1. Restate the alert: rule ID/name, level, agent/host, user, source IP, timestamp.
2. Evidence: list only fields present in the alert JSON. Quote field names and values. Mark anything inferred as "inferred".
3. Context checks (only if tools allow): is the source IP internal/known? Is the user/host in an expected role? Other alerts on the same host/user in the last 24h?
4. Map to ATT&CK only when the alert data supports it. Give the technique ID and the field that supports it.
5. Verdict: one of
   - Likely benign (evidence: ...)
   - Suspicious, needs analyst (what is missing)
   - Likely true positive, escalate (evidence: ...)
   Never mark benign without a stated reason from the data.
6. Next actions: at most 3, ordered, read-only first. Containment actions are suggestions for a human, never executed.

## Output
Verdict line first, then Evidence, Context, Next actions, Uncertain.

## Do not
- Invent IOCs, hashes, or threat-actor attribution.
- Treat a single failed login or one scan as an incident without a pattern.
