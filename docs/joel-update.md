# Update for Joel

## Ready
- Shared GitHub repository created; invitation sent.
- AWS VPC, two subnets, internet routing, and security groups created.
- Both EC2 servers launched and SSH tested.
- Destination test service running on port 8000.
- Source-to-destination HTTP test passed.

## Connection details
- Region: us-east-1.
- Source instance: i-0e4cb59f00340b267.
- Source private IP: 10.20.1.33.
- Destination instance: i-0f32c4732129523c5.
- Destination private IP: 10.20.2.151.
- Target port: 8000.
- Expected response: CloudLink destination is healthy.

## Proposed app setup
Run the probe from the source server.
Use the destination private IP for tests.
Send Johnny the app setup and run commands when ready.
Do not commit AWS credentials or SSH keys.

## Johnny's next tasks
Run controlled failure tests and record recovery steps.

## Pending
- App integration has not been verified.
- Sandbox persistence and shared AWS access need professor confirmation.
