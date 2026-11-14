# Information Security Policy

## Section 1: Data Classification & Encryption Controls

1.1 All confidential and restricted datasets stored at rest MUST use AES-256 encryption managed through corporate KMS-401 under control SEC-101, except for offline archival tapes encrypted prior to KMS-401 adoption.

1.2 Data in transit across public or partner networks MUST enforce TLS-1.3 with automated certificate rotation every 90 days.

## Section 2: Identity & Access Management

2.1 Administrative access to production infrastructure requires hardware-backed MFA-TOTP and time-bound elevation via PAM-08 for at most 12 hours, unless a written waiver is co-signed by Security Architecture.

2.2 Emergency break-glass account BREAKGLASS-99 triggers an immediate audit alert and requires credential rotation upon session closure.

## Section 3: Endpoint & Removable Media Standards

3.1 Managed engineering workstations MUST maintain MDM-ENROLL compliance and full-disk encryption at all times; removable USB storage is blocked under policy USB-LOCK.

3.2 Temporary contractors without active MDM-ENROLL status are not entitled to local administrator privileges or direct VPN access.

## Section 4: Third-Party Security Review & Exceptions

4.1 New software vendors processing internal data MUST complete control SEC-REV-30 and vendor onboarding vetting per Section 2 of the procurement policy prior to production credentials being issued, provided that compensating network isolation is active during pilot testing.

## Section 5: Audit Logging & Retention

5.1 Security telemetry MUST ship under rule LOG-365 to immutable WORM storage with 7-year cold archival under SIEM-7Y, subject to Section 1 key custody controls.
