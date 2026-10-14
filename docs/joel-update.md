# Update for Joel

## Completed
- Created the CloudLink repository locally.
- Installed AWS CLI and connected to the Academy Sandbox.
- Created the VPC and source/destination subnets.
- Added infrastructure docs and a failure-test checklist.

## Proposed integration
- Probe runs from the source EC2 instance.
- Destination runs a test service on TCP port 8000.
- Probe uses the destination private IP.
- Johnny supplies instance IDs, IPs, region, and test scenarios.
- Joel supplies the probe/app run instructions.

## Pending
- Servers and security groups are not created yet.
- Need professor confirmation on sandbox persistence and team access.
- Need agreement on the application interface.
