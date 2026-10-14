# Deploy and test CloudLink in AWS Academy

This guide creates the **hosted** CloudLink lab in your AWS Academy sandbox. “Hosted” means the dashboard runs on an EC2 web instance in AWS, rather than on your Mac at `127.0.0.1:5001`. Creating the web stack installs the app from the [CloudLink GitHub repository](https://github.com/dong-quan-tran/cloudlink); it does not require uploading the app or entering AWS credentials in the browser. The lab creates a VPC, three public-subnet EC2 instances (web, node A, node B), and their network rules. The nodes communicate over private IPs within the VPC.

**Status:** This three-stack deployment has not yet been tested end to end. The steps below are the planned first validation, so stop and inspect any failed stack rather than assuming the web app is installed. Academy permissions or quotas may limit what you can create.

## 1. Prepare the sandbox

1. Start the AWS Academy sandbox and open its AWS console in **us-east-1**. Open **CloudShell** there. CloudShell is just where you run the deployment commands; the app itself will run on EC2.
2. Find the public IPv4 address of the **Mac/browser that will open CloudLink**. On that Mac, run `curl -4 https://checkip.amazonaws.com` in Terminal. Add `/32` to the result (for example, `203.0.113.10/32`). Do **not** use CloudShell's public IP for this setting unless that is truly where your browser will run. This address becomes `ManagementCidr`, the only allowed browser and direct SSH source.
3. In CloudShell, confirm that the lab's `vockey` EC2 key pair is present in this Region:

   ```sh
   aws ec2 describe-key-pairs --region us-east-1 --key-names vockey --query 'KeyPairs[0].KeyName' --output text
   ```

   If it is missing, stop: all three templates currently refer to that key name.

## 2. Deploy the three stacks

In a fresh CloudShell directory, get the public repository and enter its infrastructure folder:

```sh
git clone https://github.com/dong-quan-tran/cloudlink.git
cd cloudlink/infra
```

Run each command below **one at a time**, waiting for it to finish before starting the next. Replace `YOUR_PUBLIC_IP/32` with the address from step 1. Do not include spaces in the CIDR value.

```sh
aws cloudformation deploy --region us-east-1 \
  --stack-name cloudlink-network --template-file network.yaml \
  --parameter-overrides ManagementCidr=YOUR_PUBLIC_IP/32

aws cloudformation deploy --region us-east-1 \
  --stack-name cloudlink-web --template-file web.yaml \
  --parameter-overrides NetworkStackName=cloudlink-network \
    RepositoryUrl=https://github.com/dong-quan-tran/cloudlink.git RepositoryRef=main

aws cloudformation deploy --region us-east-1 \
  --stack-name cloudlink-probes --template-file probes.yaml \
  --parameter-overrides NetworkStackName=cloudlink-network
```

The order matters: the web and probe stacks use values created by `cloudlink-network`. The web instance installs Nginx, Gunicorn, and the CloudLink app from the GitHub repository during its first boot. The probe instances start a test service on TCP port 8080 and trust the web instance's **public** management key. The web instance keeps the private key; it is not stored in GitHub. CloudFormation uses your Academy session to create resources; the hosted app does not need those credentials.

## 3. Open the dashboard and run the first test

Get the dashboard address from the web stack:

```sh
aws cloudformation describe-stacks --region us-east-1 \
  --stack-name cloudlink-web \
  --query "Stacks[0].Outputs[?OutputKey=='WebUrl'].OutputValue" \
  --output text
```

Open the returned `http://.../` URL in the browser on the Mac whose IP you allowed. The app may take a few minutes to finish installing after CloudFormation reports the stack complete; refresh if necessary. When node A and node B appear:

1. Select **CloudLink-Node-A** as the source and **CloudLink-Node-B** as the destination.
2. Leave **Destination address** on **Private IP**.
3. Choose **Ping (ICMP)** and run the test. The expected baseline is success.
4. Choose **Custom TCP port**, enter **8080**, and run it. The expected baseline is success.
5. Try **HTTP (80)**, **HTTPS (443)**, or **SSH banner (22)** between A and B if you want a controlled failure. Those ports are not part of the peer-to-peer baseline, so failure is expected. This does **not** mean the two instances have no route between them.

The **Recent tests** area should show the results. The dashboard's own HTTP connection is separate from the A-to-B port you choose; opening the dashboard does not require port 80 or 443 to be allowed *between* A and B. The hosted inventory currently supports the two lab nodes and their private addresses. Do not use the **Public IP** destination option for this first test.

## If something does not work

- **A stack fails:** In the CloudFormation console, open that stack's **Events** tab and read the first failed resource. Check Academy permissions, instance quotas, key pair, and Region before retrying.
- **The dashboard does not open:** Confirm you used the web stack's `WebUrl`, your Mac's current public IP matches `ManagementCidr`, and the web instance is running. A completed stack does not guarantee its first-boot install succeeded. If you can SSH to the web instance, inspect `/var/log/cloud-init-output.log` and `systemctl status cloudlink nginx`.
- **The dashboard opens but a test cannot start:** Check that both probe instances are running, that the web instance's management key reached them during first boot, and that the web-to-source SSH rule exists. Probe first-boot logs are also in `/var/log/cloud-init-output.log`.
- **A test runs but fails:** Check the specific protocol and port, the destination service, and the A-to-B security-group rules. CloudLink provides likely next checks, not a guaranteed root-cause diagnosis.

The current dashboard uses **HTTP with a restricted `/32` source**, not HTTPS or user authentication. Keep it limited to your own address, do not enter secrets, and delete the lab when finished. A public deployment would need authentication and TLS.

## Local preview versus hosted test

The Flask page previously opened at `http://127.0.0.1:5001/` is a **local preview**. It does not create the AWS lab. A live local test also needs fresh Academy credentials in the same terminal, EC2 API permissions, and SSH access from your Mac to node A; Academy may restrict that path. For the first end-to-end check, use the hosted instructions above.

## Clean up

Deleting these stacks removes the new lab instances and their locally saved test history. The app does not currently have a history-export button; if you need to keep the data, copy `/var/lib/cloudlink/history.sqlite3` from the web instance before deleting it. Delete in reverse order so the network's exported values are no longer in use:

```sh
aws cloudformation delete-stack --region us-east-1 --stack-name cloudlink-probes
aws cloudformation wait stack-delete-complete --region us-east-1 --stack-name cloudlink-probes
aws cloudformation delete-stack --region us-east-1 --stack-name cloudlink-web
aws cloudformation wait stack-delete-complete --region us-east-1 --stack-name cloudlink-web
aws cloudformation delete-stack --region us-east-1 --stack-name cloudlink-network
aws cloudformation wait stack-delete-complete --region us-east-1 --stack-name cloudlink-network
```

These commands target the three **new** CloudLink stacks only; an older two-node lab stack, if present, is separate. AWS CloudFormation requires importing stacks to be removed before the network stack that exports their values.

## References

- [AWS CLI: deploy a CloudFormation stack](https://docs.aws.amazon.com/cli/latest/reference/cloudformation/deploy.html)
- [AWS CloudFormation cross-stack exports and imports](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-stack-exports.html)
