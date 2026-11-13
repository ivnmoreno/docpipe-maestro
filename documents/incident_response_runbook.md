# Security Incident Response Runbook

**Runbook ID:** IR-RB-012 | **Maintainer:** Security Operations Center (SOC)

## Section 1: Severity Classification

1.1 **SEV-1 (Critical):** Active data exfiltration, ransomware, or production outage affecting >25% of customers. Initial triage SLA is 15 minutes; executive bridge within 30 minutes.
1.2 **SEV-2 (High):** Confirmed unauthorized access to a non-critical system or vulnerability with active exploit intelligence. Triage SLA is 1 hour.
1.3 **SEV-3 (Medium/Low):** Isolated malware on a single endpoint contained by EDR, with no lateral movement. Triage SLA is 4 business hours.

## Section 2: Containment and Evidence Preservation

2.1 On-call responders must isolate affected hosts via EDR network containment before rotating credentials, unless isolating the host would sever live forensic memory capture required for SEV-1 investigations.
2.2 Never reboot a compromised host prior to capturing volatile memory and volatile network connections, except when instructed by the Incident Commander to halt active destructive encryption.
2.3 Cross-reference all customer-impacting notifications with Section 4.1 of the Compliance Policy and Clause 4.2 of the Master Services Agreement.

## Section 3: Post-Incident Review

3.1 A blameless Post-Incident Review (PIR) must be published within five (5) business days for all SEV-1 and SEV-2 incidents, tracking corrective actions with named owners and due dates.
