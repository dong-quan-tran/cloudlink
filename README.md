# CloudLink

CloudLink tests connections between AWS servers and gives troubleshooting guidance.
It will not automatically change AWS settings.

## Team
- Johnny: AWS network, servers, failure tests, and setup docs.
- Joel: app, dashboard, connection tests, and saved results.

## Current status
The test network is working.
The first source-to-destination connection test passed.
Controlled failure tests have not started.
App integration has not been verified.

## Completed
- GitHub repository created; Joel invited.
- AWS sandbox access configured.
- VPC and two subnets created.
- Internet gateway and public routing configured.
- Source and destination security groups created.
- Two Amazon Linux EC2 servers launched.
- SSH access verified for both servers.
- Destination HTTP service running on TCP port 8000.
- Source reached destination private IP 10.20.2.151:8000.

## Next tasks
1. Stop the test service and confirm failure.
2. Restart it and confirm recovery.
3. Test blocked port and wrong source range.
4. Test a stopped destination instance.
5. Save each result and restore the healthy setup.
6. Finish repeatable setup and cleanup scripts.
7. Test Joel's app against the network.

## Open questions
- Does the sandbox keep resources between sessions?
- How should both teammates access the AWS environment?

## Files
- infrastructure/network.json: AWS resource IDs.
- infrastructure/setup-destination.sh: test service setup.
- infrastructure/README.md: network details.
- docs/baseline-result.md: successful connection test.
- docs/test-scenarios.md: failure-test checklist.
- docs/joel-update.md: team handoff.

## Safety
Never commit AWS credentials, SSH keys, or passwords.
Use only the dedicated CloudLink resources.
