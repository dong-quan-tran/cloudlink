"""Run bounded source-to-destination checks outside web requests."""

from __future__ import annotations

import json
import logging
import os
import signal
import time
import uuid
from typing import Any

from .jobs import JobStore, TERMINAL
from .network import analyze_network, configuration_result
from .probe import discover_nodes, run_probe

logger = logging.getLogger(__name__)


def process_message(store: JobStore, session: Any, message: dict[str, Any]) -> None:
    job_id = json.loads(message["Body"])["id"]
    job = store.get(job_id)
    receipt = message["ReceiptHandle"]

    def acknowledge() -> None:
        store.queue.delete_message(QueueUrl=store.queue_url, ReceiptHandle=receipt)

    if job is None or job["status"] in TERMINAL:
        acknowledge()
        return
    if int(job["deadline"]) <= int(time.time()):
        store.fail(job_id, "This request timed out. Please submit a new test.")
        acknowledge()
        return
    owner = str(uuid.uuid4())
    if not store.claim(job_id, owner):
        return  # Another worker has a live lease. Do not acknowledge its work.
    try:
        nodes = {node.instance_id: node for node in discover_nodes(session.client("ec2"))}
        source, destination = nodes.get(job["source_id"]), nodes.get(job["destination_id"])
        if source is None or destination is None:
            store.fail(job_id, "One of the selected lab instances is no longer running.", owner=owner)
            acknowledge()
            return
        request = dict(job["request"])
        mode = request.pop("mode", "live")
        if request.get("port") is not None:
            request["port"] = int(request["port"])  # DynamoDB returns numbers as Decimal.
        if mode == "configuration":
            result = configuration_result(session, source, destination, **request)
        else:
            result = run_probe(
                session, source, destination, **request,
                existing_key_path=os.environ["CLOUDLINK_KEY_PATH"], source_address_type="private",
            )
            if not result["check"]["ok"]:
                result["network_analysis"] = analyze_network(session, source, destination, **request)
        if store.complete(job_id, owner, result):
            acknowledge()
    except Exception:
        logger.exception("Job %s failed; SQS will retry it", job_id)
        if int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1")) >= 3:
            store.fail(job_id, "The worker could not complete this request after three deliveries. Please retry.", owner=owner)
        # Keep the message for retry/dead-letter handling. Never acknowledge a failed write.


def main() -> None:
    import boto3

    logging.basicConfig(level=logging.INFO)
    session = boto3.session.Session(region_name=os.getenv("AWS_REGION", "us-east-1"))
    store = JobStore(session, os.environ["CLOUDLINK_TABLE_NAME"], os.environ["CLOUDLINK_QUEUE_URL"])
    stopping = False

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        try:
            response = store.queue.receive_message(
                QueueUrl=store.queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=20,
                MessageSystemAttributeNames=["ApproximateReceiveCount"],
            )
            for message in response.get("Messages", []):
                if not stopping:
                    process_message(store, session, message)
        except Exception:
            logger.exception("Queue operation failed")
            time.sleep(3)


if __name__ == "__main__":
    main()
