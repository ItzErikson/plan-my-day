# Plan My Day

Build and deploy your own AI agent on AWS. It keeps your calendar and to-do list, and plans your day for you.

> "Add a meeting with my study group at 4pm Thursday"
> "Add CS homework due Friday"
> "Plan my day"

**You need:** a laptop and your `@vanderbilt.edu` email. Do every step on your laptop.

---

## Part 0: Sign up (10 min)

Do these in order. Use your **@vanderbilt.edu** email for all of them.

### 0.1 Create your free AWS account

1. Open **https://aws.amazon.com/start-here/**
2. Click **Create an account**.
3. Sign up with your **@vanderbilt.edu** email and follow the steps. This also creates your **AWS Builder ID** (your one login for everything below).
4. If it asks you to name a project, type `plan-my-day`.
5. You're done when you see a page with **Credits remaining: $100.00**.

> ⚠️ Never click **Activate advanced features** or **Upgrade plan**. Your free plan can't charge you.

### 0.2 Unlock your free student perks

1. Open **https://builder.aws.com/student-rewards**
2. Sign in with the same Builder ID.
3. Click **Verify** and finish the student check (SheerID) with your @vanderbilt.edu email.
4. Finish your Builder Center profile: add a **photo** and a short **bio**, then save. This unlocks 12 months of free Skill Builder Premium.

### 0.3 Get Kiro (free for a year)

1. Open **https://kiro.dev/students**
2. Download Kiro and install it.
3. Open Kiro and sign in with your **AWS Builder ID**.
4. On the Kiro account page, click **Verify** on the "You are eligible for Kiro Students" banner and finish the check.

### 0.4 RSVP

Open **https://www.meetup.com/aws-sbg-at-vanderbilt-university/** → find tonight's event → **Attend**.

---

## Part 1: Deploy your agent (5 min)

### 1.1 Open CloudShell

1. Open **https://console.aws.amazon.com/cloudshell/home** (sign in with your Builder ID if asked).
2. If a "Welcome to AWS CloudShell" box shows up, click **Close**.
3. Wait until you see a line ending in `$` and a blinking cursor.

### 1.2 Run the deploy command

1. Click inside the black CloudShell window.
2. Copy this whole line:

   ```bash
   git clone https://github.com/ItzErikson/plan-my-day.git && cd plan-my-day && python3 deploy.py
   ```

3. Paste it into CloudShell (**Cmd+V** on Mac, **Ctrl+V** on Windows) and press **Enter**.
   If a "Safe Paste" box pops up, click **Paste**.

### 1.3 Pick a passphrase

1. When it says `Pick a passphrase for your agent`, type a password you'll remember (no spaces), for example `commodore2026`.
2. Press **Enter**.

### 1.4 Open your agent

1. Wait about 1 minute until you see:

   ```
   DONE! Your agent is live at:

      https://xxxxxxxx.lambda-url.us-east-2.on.aws/
   ```

2. Copy that link and open it in a new browser tab.
3. Type your passphrase → **Unlock**.

### 1.5 Try it

Type these one at a time (change the details to your real life):

```
Add a meeting with my study group at 4pm Thursday
Add CS homework due Friday
Add calc exam next Wednesday at 10am
Plan my day
What do I have this week?
I finished my CS homework
```

✅ **Done with Part 1.** You have a live AI agent on AWS. Text the link to yourself so you can use it on your phone.

---

## Part 2: Make it yours with Kiro (10 min)

### 2.1 Open the project in Kiro

1. Download this project: **https://github.com/ItzErikson/plan-my-day/archive/refs/heads/main.zip**
2. Unzip it (double-click the zip file).
3. In Kiro: **File → Open Folder** → pick the `plan-my-day-main` folder → **Open**.

### 2.2 Connect Kiro to your AWS account

1. Open **https://console.aws.amazon.com**
2. At the top, find the box **"Connect your AI coding agent to AWS"** → click **Copy agent prompt**.
3. In Kiro, open the chat panel (on the right side of the window).
4. Paste the prompt and press **Enter**.
5. Kiro will ask to run commands and may open a browser tab to sign in. Click **Run** / **Allow** each time.
6. Wait until Kiro says it's connected.

### 2.3 Ask Kiro to change your agent

1. Pick **one** idea:

   - Make the agent talk like a hype-man sports announcer
   - Add a priority (high, medium, low) to to-do items and plan high-priority ones first
   - Show how many days are left until each due date in the To-do list
   - Add a "Clear finished tasks" button
   - Your own idea

2. Copy this prompt into Kiro chat. Replace `YOUR IDEA HERE` with the idea you picked:

   ```
   Read README.md, app.py, and index.html in this project.
   Make this change: YOUR IDEA HERE
   Keep everything else working.
   Then redeploy by running: python3 deploy.py --update
   (If python3 doesn't work, use python. Install boto3 if it's missing.)
   Tell me when it's live.
   ```

3. Press **Enter**. Click **Run** / **Allow** when Kiro asks.
4. When Kiro says it's done, refresh your agent's tab and try your new feature.

> **Kiro can't connect to AWS?** Use CloudShell instead:
> 1. In CloudShell, click **Actions → Upload file** → pick the file Kiro changed (`app.py` or `index.html`) from your `plan-my-day-main` folder.
> 2. Paste this and press **Enter** (change `app.py` to `index.html` if that's the file you uploaded):
>    ```bash
>    cp ~/app.py ~/plan-my-day/app.py && cd ~/plan-my-day && python3 deploy.py --update
>    ```

---

## If something goes wrong

| You see | Do this |
|---|---|
| `destination path 'plan-my-day' already exists` | Paste `cd ~/plan-my-day && git pull && python3 deploy.py` and press **Enter** |
| "Wrong passphrase" in the browser | Passphrases are case-sensitive. Forgot it? In CloudShell paste `cd ~/plan-my-day && python3 deploy.py` and pick a new one |
| `{"Message":"Forbidden"}` when you open the link | In CloudShell paste `cd ~/plan-my-day && python3 deploy.py --update`. Still broken? Raise your hand |
| The agent says "The agent hit an error" | Copy the message and raise your hand |
| `ERROR:` in CloudShell | Copy the error and raise your hand |
| CloudShell is stuck or blank | Refresh the page |
| The agent gets today's date wrong | It uses your laptop's clock. Check your laptop's date and time |

---

## Delete everything (optional)

In CloudShell, paste this and press **Enter**:

```bash
cd ~/plan-my-day && python3 deploy.py --delete
```

---

## How it works

```
Your browser ──► Lambda function URL ──► app.py (the agent)
                                            ├── Amazon Bedrock (Amazon Nova): understands you, picks tools
                                            └── DynamoDB: stores your events and to-dos
```

| File | What it is |
|---|---|
| `app.py` | The agent: its tools (add event, add task, list, complete, delete) and the AI loop |
| `index.html` | The web page you chat in |
| `deploy.py` | Creates the table, permissions, Lambda function, and link in your AWS account |

Made by the AWS Student Builder Group @ Vanderbilt.
