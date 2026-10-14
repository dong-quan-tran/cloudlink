# CloudLink

A tool for testing cloud connectivity and explaining likely failures.
CloudLink provides guidance; it does not automatically change cloud settings.

## Team
- Johnny: AWS network, test servers, failure scenarios, and setup docs.
- Joel: application, dashboard, probes, diagnostic rules, and result storage.

## Planned first version
- Two AWS EC2 instances: source and destination.
- TCP connection tests to destination port 8000.
- Security-group checks.
- Saved results for before/after comparisons.

## Current progress
- Local Git repository created.
- AWS CLI installed and sandbox access verified.
- VPC and two subnets created.
- Resource IDs saved in infrastructure/network.json.

## Not completed
- Internet gateway and route configuration.
- Security groups.
- EC2 instances.
- Healthy connection test.
- Application integration.

## Open questions
- Does the sandbox keep resources between sessions?
- How will both teammates access the same AWS environment?
- Confirm the application interface with Joel.

## Safety
Never commit AWS credentials, SSH keys, or passwords.
Use only the dedicated CloudLink test resources.
