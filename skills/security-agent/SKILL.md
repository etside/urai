---
name: security-agent
description: "AI security engineering across AWS, GCP, Azure, Kubernetes, GitHub, and GitLab. Use for threat analysis, IAM audit, vulnerability scanning, compliance checking, incident response, and security hardening. Based on Cynative open-source security agent framework."
source: https://github.com/cynative/cynative
---

# Security Agent (Urai)

Urai's security agent can audit, analyze, and harden cloud infrastructure and codebases.

## Scope

**In scope (authorized use only):**
- Auditing your own infrastructure
- Compliance checking (SOC2, HIPAA, PCI-DSS, ISO27001)
- Vulnerability scanning of your own code
- IAM policy review
- Security hardening recommendations
- CTF challenges

**Out of scope:**
- Attacking systems you don't own
- Credential theft or exfiltration
- Bypassing authentication without authorization

## Capabilities

### Cloud Security
```bash
urai agent "audit my AWS IAM policies for privilege escalation paths"
urai agent "check my GCP project for public storage buckets"
urai agent "review Kubernetes RBAC for overprivileged service accounts"
```

### Code Security
```bash
urai agent "scan this Python code for SQL injection vulnerabilities" --file app.py
urai agent "check for hardcoded secrets in this repo" --path ./myproject
```

### GitHub/GitLab Security
```bash
urai agent "audit GitHub Actions workflows for supply chain risks"
urai agent "check for exposed secrets in git history"
```

## Security Tools Available

- `web_fetch` — check public security advisories
- `code_run` — run security scanners (bandit, semgrep, trufflehog)
- `browser_run` — interact with security dashboards
- `wiki_search` — search CVE/threat intelligence knowledge base

## Threat Analysis Loop

```
1. Enumerate attack surface
2. Identify vulnerabilities
3. Assess exploitability and impact
4. Recommend mitigations
5. Verify mitigations applied
```

## Output Format

Security findings are reported as:
- Severity: CRITICAL / HIGH / MEDIUM / LOW / INFO
- Finding: description of the issue
- Evidence: specific code/config location
- Remediation: exact fix with code snippet
- Reference: CVE or security advisory link
