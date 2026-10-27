"""
Plan My Day: a personal AI agent that runs on AWS Lambda.

- Your calendar and to-do list live in DynamoDB.
- The "brain" is a Bedrock model that can call the tools below.
- The web page (index.html) is served from the same Lambda function URL.
"""

import base64
import hmac
import json
import os
import uuid
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Attr

# ---------- Settings (safe to change) ----------
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
AGENT_PERSONALITY = (
    "You are Plan My Day, a friendly personal assistant for a busy college student. "
    "Be short, warm, and practical."
)
# -----------------------------------------------

TABLE_NAME = os.environ.get("TABLE_NAME", "plan-my-day")
PASSPHRASE = os.environ.get("PASSPHRASE", "")
MAX_TOOL_ROUNDS = 6

_table = None
_bedrock = None


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table


def bedrock():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime")
    return _bedrock


# ---------- Tools the agent can use ----------

def add_event(title, date, start, end=None, notes=None):
    item = {
        "id": "evt-" + uuid.uuid4().hex[:8],
        "kind": "event",
        "title": title,
        "date": date,
        "start": start,
    }
    if end:
        item["end"] = end
    if notes:
        item["notes"] = notes
    table().put_item(Item=item)
    return {"added": item}


def add_task(title, due_date=None, notes=None):
    item = {
        "id": "task-" + uuid.uuid4().hex[:8],
        "kind": "task",
        "title": title,
        "done": False,
    }
    if due_date:
        item["due_date"] = due_date
    if notes:
        item["notes"] = notes
    table().put_item(Item=item)
    return {"added": item}


def list_items(start_date=None, end_date=None):
    items = []
    kwargs = {}
    while True:
        page = table().scan(**kwargs)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    events = [i for i in items if i.get("kind") == "event"]
    if start_date:
        events = [e for e in events if e.get("date", "") >= start_date]
    if end_date:
        events = [e for e in events if e.get("date", "") <= end_date]
    events.sort(key=lambda e: (e.get("date", ""), e.get("start", "")))

    tasks = [i for i in items if i.get("kind") == "task" and not i.get("done")]
    tasks.sort(key=lambda t: t.get("due_date") or "9999-99-99")
    return {"events": events, "open_tasks": tasks}


def complete_task(task_id):
    table().update_item(
        Key={"id": task_id},
        UpdateExpression="SET done = :d",
        ConditionExpression=Attr("id").exists(),
        ExpressionAttributeValues={":d": True},
    )
    return {"completed": task_id}


def delete_item(item_id):
    table().delete_item(Key={"id": item_id})
    return {"deleted": item_id}


TOOLS = {
    "add_event": add_event,
    "add_task": add_task,
    "list_items": list_items,
    "complete_task": complete_task,
    "delete_item": delete_item,
}

TOOL_SPECS = [
    {"toolSpec": {
        "name": "add_event",
        "description": "Add an event with a set time to the calendar (class, meeting, practice).",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "start": {"type": "string", "description": "24h time HH:MM"},
                "end": {"type": "string", "description": "24h time HH:MM (optional)"},
                "notes": {"type": "string"},
            },
            "required": ["title", "date", "start"],
        }},
    }},
    {"toolSpec": {
        "name": "add_task",
        "description": "Add a to-do item (homework, errand) with an optional due date.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "due_date": {"type": "string", "description": "YYYY-MM-DD (optional)"},
                "notes": {"type": "string"},
            },
            "required": ["title"],
        }},
    }},
    {"toolSpec": {
        "name": "list_items",
        "description": "Get calendar events between two dates (inclusive) plus all open to-do items. "
                       "Always call this before planning a day or answering what is coming up.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            },
        }},
    }},
    {"toolSpec": {
        "name": "complete_task",
        "description": "Mark a to-do item as done. Use list_items first to find its id.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        }},
    }},
    {"toolSpec": {
        "name": "delete_item",
        "description": "Delete an event or to-do item. Use list_items first to find its id.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {"item_id": {"type": "string"}},
            "required": ["item_id"],
        }},
    }},
]


# ---------- The agent loop ----------

def system_prompt(now):
    return [{"text": (
        f"{AGENT_PERSONALITY}\n"
        f"The user's current local date and time is: {now}.\n"
        "Turn words like 'tomorrow', 'Thursday', or '4pm' into exact dates (YYYY-MM-DD) "
        "and 24h times (HH:MM) before calling tools.\n"
        "When asked to plan the day: call list_items for that date, then write a simple "
        "time-blocked schedule that fits open tasks around fixed events, most urgent first, "
        "with short breaks. Never invent events that are not in the calendar.\n"
        "After adding or changing something, confirm it in one short sentence.\n"
        "Use plain text, no markdown tables."
    )}]


def run_agent(history, now):
    messages = []
    for m in history[-10:]:
        role = "assistant" if m.get("role") == "assistant" else "user"
        text = str(m.get("text", "")).strip()
        if not text:
            continue
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"][0]["text"] += "\n" + text
        else:
            messages.append({"role": role, "content": [{"text": text}]})
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    if not messages or messages[-1]["role"] != "user":
        return "Say something and I'll help you plan!"

    for _ in range(MAX_TOOL_ROUNDS):
        resp = bedrock().converse(
            modelId=MODEL_ID,
            system=system_prompt(now),
            messages=messages,
            toolConfig={"tools": TOOL_SPECS},
            inferenceConfig={"maxTokens": 1024},
        )
        msg = resp["output"]["message"]
        messages.append(msg)

        if resp.get("stopReason") != "tool_use":
            return "".join(c.get("text", "") for c in msg["content"]).strip()

        results = []
        for block in msg["content"]:
            if "toolUse" not in block:
                continue
            call = block["toolUse"]
            try:
                output = TOOLS[call["name"]](**call.get("input", {}))
                status = "success"
            except Exception as err:  # tell the model what went wrong
                output = {"error": str(err)}
                status = "error"
            results.append({"toolResult": {
                "toolUseId": call["toolUseId"],
                "content": [{"json": json.loads(json.dumps(output, default=str))}],
                "status": status,
            }})
        messages.append({"role": "user", "content": results})

    return "Sorry, that took too many steps. Try asking in a simpler way."


# ---------- Web handler (Lambda function URL) ----------

def respond(status, body, content_type="application/json"):
    if not isinstance(body, str):
        body = json.dumps(body, default=str)
    return {
        "statusCode": status,
        "headers": {"Content-Type": content_type, "Cache-Control": "no-store"},
        "body": body,
    }


def passphrase_ok(event):
    given = (event.get("headers") or {}).get("x-passphrase", "")
    return bool(PASSPHRASE) and hmac.compare_digest(given.encode(), PASSPHRASE.encode())


def handler(event, context=None):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")

    if method == "GET" and path in ("/", "/index.html"):
        html = (Path(__file__).parent / "index.html").read_text()
        return respond(200, html, "text/html; charset=utf-8")

    if not path.startswith("/api/"):
        return respond(404, {"error": "Not found"})
    if not passphrase_ok(event):
        return respond(401, {"error": "Wrong passphrase"})

    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode()
    try:
        data = json.loads(body)
    except ValueError:
        data = {}

    if method == "GET" and path == "/api/items":
        return respond(200, list_items())

    if method == "POST" and path == "/api/chat":
        try:
            reply = run_agent(data.get("history", []), data.get("now", "unknown"))
        except Exception as err:
            return respond(500, {"error": f"The agent hit an error: {err}"})
        return respond(200, {"reply": reply})

    return respond(404, {"error": "Not found"})
