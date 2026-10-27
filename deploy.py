"""
Deploys Plan My Day to your AWS account (or updates it if it's already there).

    python3 deploy.py            deploy (asks for a passphrase)
    python3 deploy.py --update   push code changes, keep your passphrase (no questions)
    python3 deploy.py --delete   remove everything this script created
"""

import io
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

try:
    import boto3
    from botocore.exceptions import ClientError, ParamValidationError
except ImportError:
    print("Installing boto3 (one time)...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "--user", "boto3"])
    import site
    sys.path.append(site.getusersitepackages())
    import boto3
    from botocore.exceptions import ClientError, ParamValidationError

NAME = "plan-my-day"
HERE = Path(__file__).parent
PRIVATE = os.environ.get("PMD_PRIVATE") == "1"  # testing only: no public link

session = boto3.session.Session()
REGION = session.region_name or "us-east-2"
ddb = session.client("dynamodb", region_name=REGION)
iam = session.client("iam", region_name=REGION)
lam = session.client("lambda", region_name=REGION)
logs = session.client("logs", region_name=REGION)


def step(msg):
    print(f"\n==> {msg}")


def code_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("app.py", "index.html"):
            z.write(HERE / name, name)
    return buf.getvalue()


def function_exists():
    try:
        return lam.get_function(FunctionName=NAME)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return None
        raise


def ask_passphrase(existing):
    if existing:
        prompt = "Pick a passphrase (or press Enter to keep your current one): "
    else:
        prompt = "Pick a passphrase for your agent (no spaces, you'll type it in the browser): "
    while True:
        p = input(prompt).strip()
        if not p and existing:
            return existing
        if p and " " not in p:
            return p
        print("   Passphrase can't be empty or have spaces. Try again.")


def make_table():
    step("Creating your DynamoDB table (your calendar storage)")
    try:
        ddb.create_table(
            TableName=NAME,
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceInUseException":
            raise
        print("   Already exists, keeping your data.")
    ddb.get_waiter("table_exists").wait(TableName=NAME)
    return ddb.describe_table(TableName=NAME)["Table"]["TableArn"]


def make_role(table_arn):
    step("Creating permissions for your agent (IAM role)")
    trust = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"},
                       "Action": "sts:AssumeRole"}],
    }
    created = False
    try:
        arn = iam.create_role(RoleName=f"{NAME}-role",
                              AssumeRolePolicyDocument=json.dumps(trust))["Role"]["Arn"]
        created = True
    except ClientError as e:
        if e.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
        arn = iam.get_role(RoleName=f"{NAME}-role")["Role"]["Arn"]
        print("   Already exists.")
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow",
             "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                        "dynamodb:DeleteItem", "dynamodb:Scan"],
             "Resource": table_arn},
            {"Effect": "Allow", "Action": ["bedrock:InvokeModel"], "Resource": "*"},
            {"Effect": "Allow",
             "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
             "Resource": "*"},
        ],
    }
    iam.put_role_policy(RoleName=f"{NAME}-role", PolicyName=f"{NAME}-policy",
                        PolicyDocument=json.dumps(policy))
    if created:
        print("   Waiting 10 seconds for AWS to set it up...")
        time.sleep(10)
    return arn


def deploy_function(role_arn, passphrase, existing):
    env = {"Variables": {"TABLE_NAME": NAME, "PASSPHRASE": passphrase}}
    if existing:
        step("Updating your Lambda function (the agent)")
        lam.update_function_code(FunctionName=NAME, ZipFile=code_zip())
        lam.get_waiter("function_updated_v2").wait(FunctionName=NAME)
        lam.update_function_configuration(FunctionName=NAME, Environment=env)
        lam.get_waiter("function_updated_v2").wait(FunctionName=NAME)
        return
    step("Creating your Lambda function (the agent)")
    for attempt in range(6):
        try:
            lam.create_function(
                FunctionName=NAME, Runtime="python3.12", Handler="app.handler",
                Role=role_arn, Code={"ZipFile": code_zip()}, Timeout=60, MemorySize=256,
                Environment=env,
            )
            break
        except ClientError as e:
            if e.response["Error"]["Code"] == "InvalidParameterValueException" and attempt < 5:
                time.sleep(5)  # role not ready yet
                continue
            raise
    lam.get_waiter("function_active_v2").wait(FunctionName=NAME)


def make_url():
    step("Creating your agent's web link")
    try:
        url = lam.get_function_url_config(FunctionName=NAME)["FunctionUrl"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        url = lam.create_function_url_config(
            FunctionName=NAME, AuthType="AWS_IAM" if PRIVATE else "NONE")["FunctionUrl"]
    if PRIVATE:
        return url
    perms = [
        dict(StatementId="public-url", Action="lambda:InvokeFunctionUrl",
             FunctionUrlAuthType="NONE"),
        dict(StatementId="public-url-invoke", Action="lambda:InvokeFunction",
             InvokedViaFunctionUrl=True),
    ]
    for p in perms:
        try:
            lam.add_permission(FunctionName=NAME, Principal="*", **p)
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceConflictException":
                raise
        except ParamValidationError:
            pass  # older boto3; the first permission is enough there
    return url


def deploy():
    print(f"Deploying Plan My Day to AWS region {REGION}")
    existing = function_exists()
    old_pass = None
    if existing:
        old_pass = existing["Configuration"].get("Environment", {}).get("Variables", {}).get("PASSPHRASE")
    if "--update" in sys.argv:
        if not old_pass:
            print("Nothing to update yet. Run: python3 deploy.py")
            sys.exit(1)
        passphrase = old_pass
    else:
        passphrase = ask_passphrase(old_pass)

    table_arn = make_table()
    role_arn = make_role(table_arn)
    deploy_function(role_arn, passphrase, existing)
    url = make_url()

    print("\n" + "=" * 60)
    print("DONE! Your agent is live at:\n")
    print(f"   {url}")
    print(f"\nYour passphrase: {passphrase}")
    print("=" * 60)


def delete():
    print(f"Deleting Plan My Day from region {REGION}")
    actions = [
        ("web link", lambda: lam.delete_function_url_config(FunctionName=NAME)),
        ("Lambda function", lambda: lam.delete_function(FunctionName=NAME)),
        ("role policy", lambda: iam.delete_role_policy(RoleName=f"{NAME}-role", PolicyName=f"{NAME}-policy")),
        ("IAM role", lambda: iam.delete_role(RoleName=f"{NAME}-role")),
        ("DynamoDB table", lambda: ddb.delete_table(TableName=NAME)),
        ("logs", lambda: logs.delete_log_group(logGroupName=f"/aws/lambda/{NAME}")),
    ]
    for label, fn in actions:
        try:
            fn()
            print(f"   Deleted {label}")
        except ClientError:
            print(f"   No {label} to delete")
    print("\nAll cleaned up.")


if __name__ == "__main__":
    try:
        delete() if "--delete" in sys.argv else deploy()
    except ClientError as e:
        err = e.response["Error"]
        print(f"\nERROR: {err.get('Code')}: {err.get('Message')}")
        print("Copy this error and show it to a core team member (or paste it into Kiro).")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(1)
