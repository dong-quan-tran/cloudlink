"""Shared job state for the hosted dashboard and its SQS workers."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from botocore.exceptions import ClientError

TERMINAL = frozenset(("completed", "failed"))


def conditional_failure(error: ClientError) -> bool:
    return error.response["Error"]["Code"] == "ConditionalCheckFailedException"


class JobStore:
    def __init__(self, session: Any, table_name: str, queue_url: str):
        self.table = session.resource("dynamodb").Table(table_name)
        self.queue = session.client("sqs")
        self.queue_url = queue_url

    def submit(self, source: Any, destination: Any, *, history_owner: str, **request: Any) -> dict[str, Any]:
        now = int(time.time())
        job = {
            "id": str(uuid.uuid4()), "status": "queued",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "history_partition": history_owner, "expires_at": now + 7 * 86400,
            "deadline": now + 900,
            "source_id": source.instance_id, "source_name": source.name,
            "destination_id": destination.instance_id, "destination_name": destination.name,
            "request": request,
        }
        self.table.put_item(Item=job, ConditionExpression="attribute_not_exists(id)")
        try:
            self.queue.send_message(QueueUrl=self.queue_url, MessageBody=json.dumps({"id": job["id"]}))
        except Exception:
            self.fail(job["id"], "The request could not be queued. Please submit it again.", queued_only=True)
            raise
        return {"id": job["id"], "status": "queued"}

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self.table.get_item(Key={"id": job_id}, ConsistentRead=True).get("Item")

    def claim(self, job_id: str, owner: str) -> bool:
        now = int(time.time())
        try:
            self.table.update_item(
                Key={"id": job_id},
                UpdateExpression="SET #s = :running, lease_owner = :owner, lease_until = :lease",
                ConditionExpression="(#s = :queued OR (#s = :running AND lease_until < :now)) AND deadline > :now",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":queued": "queued", ":running": "running",
                                           ":owner": owner, ":lease": now + 120, ":now": now},
            )
            return True
        except ClientError as error:
            if conditional_failure(error):
                return False
            raise

    def complete(self, job_id: str, owner: str, result: dict[str, Any]) -> bool:
        try:
            self.table.update_item(
                Key={"id": job_id},
                UpdateExpression="SET #s = :done, result_json = :result REMOVE lease_owner, lease_until",
                ConditionExpression="#s = :running AND lease_owner = :owner",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":running": "running", ":done": "completed",
                                           ":owner": owner, ":result": json.dumps(result)},
            )
            return True
        except ClientError as error:
            if conditional_failure(error):
                return False
            raise

    def fail(self, job_id: str, message: str, queued_only: bool = False, owner: str | None = None) -> None:
        condition = "#s = :queued" if queued_only else "#s IN (:queued, :running)"
        values = {":queued": "queued", ":failed": "failed", ":error": message}
        if not queued_only:
            values[":running"] = "running"
        if owner:
            condition = "#s = :running AND lease_owner = :owner"
            values.pop(":queued")
            values[":owner"] = owner
        try:
            self.table.update_item(
                Key={"id": job_id}, UpdateExpression="SET #s = :failed, #e = :error",
                ConditionExpression=condition, ExpressionAttributeNames={"#s": "status", "#e": "error"},
                ExpressionAttributeValues=values,
            )
        except ClientError as error:
            if not conditional_failure(error):
                raise

    @staticmethod
    def view(job: dict[str, Any]) -> dict[str, Any]:
        if job["status"] == "completed":
            return {**json.loads(job["result_json"]), "id": job["id"], "status": "completed"}
        status = job["status"]
        error = job.get("error")
        if status not in TERMINAL and int(job["deadline"]) <= int(time.time()):
            status, error = "failed", "This request timed out. Please submit a new test."
        return {
            "id": job["id"], "status": status, "timestamp": job["created_at"],
            "source_name": job["source_name"], "destination_name": job["destination_name"],
            "mode": job["request"].get("mode", "live"),
            "test_type": job["request"]["test_type"], "address_type": job["request"]["address_type"],
            "summary": {"queued": "Queued", "running": "Running", "failed": "Could not run"}[status],
            "error": error,
        }

    def recent(self, history_owner: str, limit: int = 20) -> list[dict[str, Any]]:
        response = self.table.query(
            IndexName="history", KeyConditionExpression="history_partition = :p",
            ExpressionAttributeValues={":p": history_owner}, ScanIndexForward=False,
            Limit=min(max(limit, 1), 100),
        )
        # TTL cleanup is asynchronous; don't display expired items while it catches up.
        return [self.view(item) for item in response.get("Items", [])
                if int(item["expires_at"]) > int(time.time())]
