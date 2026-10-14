# CloudLink

CloudLink tests connectivity **from one instance to another**, rather than from the user's browser. The first hosted version is a three-instance AWS Academy lab: one public web instance and two public-subnet probe instances in the same VPC. The web instance reaches a chosen source over a separate management SSH path; the source then runs the selected ping, HTTP, HTTPS, SSH-banner, or custom TCP-port test against the destination. A failed service check is a useful result, not a reason the web app itself should fail.

## Current state

The earlier two-node lab was successfully tested from A to B (ICMP and TCP/8080). The **new three-stack hosted deployment has not yet been tested end to end**. Starting the sandbox, uploading templates, and creating CloudFormation stacks are separate steps; uploading YAML files alone does not create instances or install the app. The web instance also needs a public GitHub repository containing the latest CloudLink code, supplied as `RepositoryUrl` when the web stack is deployed.

## Local app versus hosted app

| Where CloudLink runs | How it finds A and B | How it tells A to run a test |
| --- | --- | --- |
| On your Mac (`127.0.0.1:5001`) | Boto3 uses temporary AWS Academy credentials from your terminal to list running `Project=CloudLink`, `CloudLinkRole=Probe` instances. | EC2 Instance Connect supplies a short-lived SSH key; your Mac connects to A's **public IP** on port 22. The Academy account must permit these API actions, and `ManagementCidr` must include your current public IP. |
| On the CloudFormation web instance | A small inventory file generated at first boot lists the two lab nodes. No AWS API credentials are needed on this instance. | A dedicated SSH key, generated on the web instance, lets it connect to A's **private IP** on port 22. The probe nodes fetch only the public key at first boot. |

CloudFormation itself uses the Academy credentials of whoever deploys the stacks (for example, in CloudShell). Those deployment credentials are **not** copied into the hosted app. The hosted design does not use an EC2 instance profile or Systems Manager Run Command. The local app's live discovery and Instance Connect path may be restricted by Academy permissions; neither has been verified for the new stacks. Do not store temporary credentials, private keys, or session tokens in the repository.

This MVP lists only the two CloudLink lab nodes. Arbitrary private-only instances or peered VPCs require a working management path to the source and suitable network routes and rules; they are future extensions.

## What the three CloudFormation stacks create

- `infra/network.yaml` (`cloudlink-network`): VPC `10.10.0.0/16`, three public subnets (A `10.10.1.0/24`, B `10.10.2.0/24`, web `10.10.3.0/24`), internet gateway, routes, and security groups. It exports IDs used by the other two stacks.
- `infra/web.yaml` (`cloudlink-web`): one Amazon Linux 2023 web instance at `10.10.3.10`. Its user data installs Python 3.11, Nginx, Gunicorn, and the app from the public GitHub repository, then enables a systemd service. There is no `run.py` or Flask development server in the deployment.
- `infra/probes.yaml` (`cloudlink-probes`): two Amazon Linux 2023 probe instances with fixed private IPs `10.10.1.10` and `10.10.2.10`. Their baseline security groups permit ICMP and TCP/8080 from each other's security group.
- A dedicated SSH key generated **on the web instance** at first boot. The probe instances fetch only its public half inside the VPC and authorize it for `ec2-user`. The private half stays on the web instance, outside the repository and browser.
- Browser HTTP and administrative SSH to the web instance are restricted to `ManagementCidr` (your public IPv4 `/32`). Probe-instance SSH accepts the web instance's security group as a management source. The browser never sends SSH commands or AWS credentials.

The web instance uses private addresses to manage source nodes. The default A-to-B test uses the VPC's automatic local route; the internet gateway is for public management and downloading installation packages. A security group allows or blocks packets, but it does not make a source instance execute a test. CloudLink's separate SSH path handles that.

## Deploy the hosted version

Before deploying, (1) push the current project to a **public GitHub repository** with the branch or tag you will use, (2) start the Academy sandbox in `us-east-1`, (3) confirm that its EC2 key pair named `vockey` exists in that Region, and (4) determine the public IPv4 address of the computer that will open the dashboard, expressed as a `/32` CIDR. The `ManagementCidr` value is also the allowed direct SSH source for the probe nodes. Keep `.venv/`, `data/`, credentials, and private keys out of Git.

Upload `network.yaml`, `web.yaml`, and `probes.yaml` from `infra/` to the same CloudShell directory. Run these commands **from that directory**, replacing the sample values. Deploy in order: network, web, probes. An uploaded template by itself changes nothing.

```sh
for template in network.yaml web.yaml probes.yaml; do
  aws cloudformation validate-template --template-body "file://$template"
done
aws cloudformation deploy \
  --stack-name cloudlink-network \
  --template-file network.yaml \
  --parameter-overrides ManagementCidr=YOUR_PUBLIC_IP/32
aws cloudformation deploy \
  --stack-name cloudlink-web \
  --template-file web.yaml \
  --parameter-overrides \
    NetworkStackName=cloudlink-network \
    RepositoryUrl=https://github.com/YOUR_ACCOUNT/YOUR_REPO.git \
    RepositoryRef=main
aws cloudformation deploy \
  --stack-name cloudlink-probes \
  --template-file probes.yaml \
  --parameter-overrides NetworkStackName=cloudlink-network
aws cloudformation describe-stacks \
  --stack-name cloudlink-web \
  --query 'Stacks[0].Outputs' \
  --output table
```

Open the `WebUrl` output of `cloudlink-web` from the IP covered by `ManagementCidr`. Verify that both probe nodes appear, then choose **Private IP** and try ping and custom TCP port **8080** from A to B. The app does not need Academy credentials once hosted. This lab uses restricted **HTTP**, not HTTPS: do not expose port 80 to the whole internet or enter sensitive data into the dashboard. A later public deployment should add authentication and TLS.

CloudFormation can report stack creation complete even when EC2 user data fails. If the app is unavailable, check `/var/log/cloud-init-output.log` and `systemctl status cloudlink nginx` on the web instance. A wrong repository URL or branch prevents the app install. The probe nodes wait for the web instance's public SSH key during first boot. If the web instance is replaced and generates a new key, replace or reconfigure the probes so they trust that key. Pushing new commits alone does not update an already-installed instance.

The UI lets you select node A or B as source, select the destination, choose its private or public address, and run one of five tests: two-packet ICMP ping; HTTP GET `/` on port 80; HTTPS GET `/` on port 443; SSH server-banner check on port 22 without login; or a TCP connection to a chosen port. Any HTTP status code counts as an application response. HTTPS checks the encrypted connection but deliberately does not validate the certificate because the lab connects by IP address; it is **not** a certificate-security test. The initial A/B security groups allow peer ICMP and TCP/8080, so HTTP, HTTPS, and SSH tests between those nodes are expected to fail until the appropriate rules and services are added. A failed probe does not prove there is no route, and a closed service and blocked rule may look similar. CloudLink offers next checks rather than claiming a proven root cause. Results are saved in SQLite on the web instance.

When finished, delete stacks in reverse order: `cloudlink-probes`, then `cloudlink-web`, then `cloudlink-network`. CloudFormation will not delete or change an exported network value while another stack imports it. These are new stacks, not an update to the older two-node lab. Delete that older stack separately if it still exists and is no longer needed.

## Run locally on your Mac

From the project directory, create the virtual environment if needed and run the app without `run.py`:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app 'cloudlink.web:create_app' run --host 127.0.0.1 --port 5001
```

Open `http://127.0.0.1:5001/`. If the Academy sandbox is not running or its temporary credentials are unavailable to the **same terminal** that starts Flask, the page can load but the instance dropdown cannot list live nodes. Load fresh Academy credentials using the Academy instructions and restart Flask; do not paste credentials into project files. The local app uses the standard AWS SDK credential chain, with `us-east-1` as its default Region. Listing nodes requires EC2 read access; running a test also requires EC2 Instance Connect access and an SSH path from your Mac to the selected source's public IP. If Academy disallows either action, the local mode cannot complete a test even though the hosted mode may still work.

Run checks with `python -m unittest discover -s tests -v`. Press `Ctrl+C` in the Flask terminal to stop the local server.
