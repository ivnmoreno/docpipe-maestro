# Security Incident Response Runbook

## Section 1: Severity Classification & Response SLAs

1.1 Any confirmed confidentiality breach or production outage affecting customer data is classified as SEV-1 under playbook IR-RB-012 and requires on-call incident commander triage within IR-15M (15 minutes), except during pre-announced maintenance windows documented in CHANGE-404.

1.2 Partial service degradation without customer data exposure is classified as SEV-2 with a four-hour engineering acknowledgment SLA.

## Section 2: Regulatory Breach Notification

2.1 Suspected unauthorized disclosure of regulated records MUST be escalated to the Data Protection Officer under protocol DPO-24H within 24 hours and reported to supervisory authorities within 72 hours under REG-72H, unless forensic containment confirms zero personal data exfiltration.

## Section 3: Credential & Key Rotation Playbook

3.1 When compromise of a service credential or encryption key is suspected under KEY-ROT-4H, responders MUST rotate affected KMS-401 keys per Information Security Policy Section 1 within four hours, provided that active session tokens are revoked simultaneously via PAM-08.

## Section 4: Post-Incident Review & Blameless Postmortem

4.1 Every SEV-1 and SEV-2 incident MUST publish a blameless postmortem within 5 business days under standard PIR-5D with tracked remediation owners, subject to Executive Sponsor sign-off before deployment freezes lift.

## Section 5: External Law Enforcement & Media Escalation

5.1 Only Corporate Legal and Executive Communications may issue external advisories under rule COMMS-01; engineering responders are not entitled to share incident logs or root-cause timelines with external parties directly.
