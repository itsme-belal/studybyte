# StudyByte — User Manual

> **Peer-to-peer micro-tutoring platform for university students**
> Token rate: `2 Tokens = 1 BDT`

---

## Table of Contents

1. [Learner Manual](#-chapter-1-the-learner-manual)
   - [Account Setup & Verification](#11-account-setup--verification)
   - [Loading Your Wallet](#12-loading-your-wallet)
   - [Finding & Booking Tutors](#13-finding--booking-tutors)
   - [Live Virtual Classroom](#14-live-virtual-classroom--escrow-release)
2. [Tutor Manual](#-chapter-2-the-tutor-manual)
   - [Academic Onboarding](#21-academic-onboarding--verification)
   - [Listings & Schedule](#22-managing-your-listings--schedule)
   - [Conducting Sessions](#23-conducting-live-sessions--claiming-payments)
   - [Cash Out](#24-cashing-out-wallet-withdrawals)
3. [Admin Manual](#-chapter-3-the-admin-manual)
   - [Platform Dashboard](#31-platform-health--real-time-auditing)
   - [Tutor Applications](#32-tutor-applications-review-queue)
   - [Ledger Moderation](#33-ledger-moderation--mobile-gateway-approvals)
   - [Dispute Resolution](#34-dispute-arena--auditing-dashboard)
   - [System Moderation](#35-system-level-commands--moderation)

---

## 🧑‍🎓 Chapter 1: The Learner Manual

### 1.1 Account Setup & Verification

**Flow:**
```
/register  →  /verify_signup  →  /profile
```

**Steps:**

1. **Sign Up** — Go to `/register`. Fill in your name, student email, password, university department, and student ID. Select **Learner** as your role.
2. **Google Auth (optional)** — Click **Sign in with Google** for one-click setup via `/google_auth`. A wallet is created automatically with `0.0` tokens.
3. **Email OTP** — A 6-digit code is sent to your email. Enter it at `/verify_signup` to activate your account.
4. **Theme Preference** — Visit `/profile` and choose Dark/Light mode via `/set_theme`.

---

### 1.2 Loading Your Wallet

**Flow:**
```
/wallet  →  Select gateway  →  /payment_gateway/simulate  →  Pending → Admin approval
```

> **Conversion rate:** `1 BDT = 2 Tokens` · `100 Tokens = 50 BDT`

**Steps:**

1. Go to `/wallet` and click **Purchase Tokens**.
2. Select your payment provider: **bKash**, **Nagad**, or **Rocket**.
3. Enter the BDT amount and complete the checkout at `/payment_gateway/simulate`.
4. Enter your **sender mobile number** and **10-character Transaction ID (TxID)**.
5. Click **Submit Payment**. Your request shows as `Pending`.
6. Once an admin verifies your TxID, tokens are credited to your wallet instantly.

---

### 1.3 Finding & Booking Tutors

**Flow:**
```
/marketplace  →  /listing/<id>  →  /book/<id>  →  /booking/<id>/confirm
```

**Navigating the Marketplace:**

- Go to `/marketplace` and filter by **Subject Category**, **Department**, **Rating**, or **Price Range**.
- Click any listing to open the detail page at `/listing/<id>`.

**Booking a Slot:**

- Open the tutor's schedule at `/book/<listing_id>` and select an available time slot.
- Confirm the booking. Tokens are deducted from your wallet and **frozen in escrow** — the tutor cannot access them yet. Booking status changes to `Pending`.

> **Cancellations:** Cancel any booking before it starts at `/booking/<id>/cancel` to instantly get your tokens refunded.

---

### 1.4 Live Virtual Classroom & Escrow Release

**Route:** `/booking/<id>/chat`

**In the Classroom:**

| Feature | Details |
|---|---|
| Real-time chat | SocketIO-powered instant messaging with your tutor |
| Materials library | Download slides, PDFs, and code files from the shared sidebar via `/material/<id>/download` |
| Video class | Click **Start/Join Video Class** to launch an encrypted Jitsi P2P call in a new tab |

**Releasing Escrow:**

1. When the session ends, the tutor shares a **6-character alphanumeric Completion Code**.
2. Enter the code into your chat panel or booking screen.
3. The platform processes `/booking/<id>/check_in`, updates the booking to `Completed`, and releases tokens from escrow to the tutor's wallet.
4. **Rate your tutor** (1–5 stars) and leave a review.

---

## 🎓 Chapter 2: The Tutor Manual

### 2.1 Academic Onboarding & Verification

**Flow:**
```
/tutor/apply  →  Upload transcript  →  Admin review  →  Verified badge
```

**Steps:**

1. Go to `/tutor/apply` from your dashboard.
2. Upload your official **grade report or transcript** (PDF or image). Files are stored securely in Cloudinary.
3. Select the departments you are qualified to tutor (e.g. B.Sc. CSE, B.Sc. EEE).
4. Submit the application. An admin manually reviews your transcript.
5. You will receive an **email notification** once approved (`is_tutor_verified = True`) or rejected with a reason for re-submission.

---

### 2.2 Managing Your Listings & Schedule

**Creating a Listing** — Route: `/listing/create`

| Field | Guidance |
|---|---|
| Topic title | Be specific, e.g. *"OOP: Inheritance & Polymorphism"* |
| Category | Set the university department |
| Rate | Set hourly price in tokens, e.g. 100 tokens = 50 BDT |
| Description | Detail concepts covered, your grade in the course, and how you will help |

**Building Your Schedule** — Route: `/tutor/availability`

- Select a date and a start/end time window (e.g. 2026-06-05 from 14:00–15:00).
- Click **Add Time Slot**. Learners can book the slot immediately.

---

### 2.3 Conducting Live Sessions & Claiming Payments

**Flow:**
```
/tutor/dashboard  →  /booking/<id>/chat  →  Upload material  →  Share code  →  Tokens paid
```

**Steps:**

1. Check active bookings at `/tutor/dashboard`. You will also receive an automatic email when a student books you.
2. Click **Enter Chat Room** at `/booking/<id>/chat` when the session starts.
3. Upload slides or code files via **Upload Course Material** at `/booking/<id>/upload_material`. Files are stored in Cloudinary.
4. Click **Start Video Room** to launch the Jitsi call.
5. Once done, share the **Verification Completion Code** (located top-right of the chat panel) with the student.
6. When the student enters the code, the escrow releases instantly and your wallet balance updates.

---

### 2.4 Cashing Out (Wallet Withdrawals)

**Flow:**
```
/wallet  →  Withdraw  →  Choose provider  →  Enter phone & amount  →  Pending  →  Cash received
```

**Steps:**

1. Go to `/wallet` and click **Withdraw Funds**.
2. Select your mobile provider: **bKash**, **Nagad**, or **Rocket**.
3. Enter your personal mobile number and the token amount to convert.
4. Submit the request. It registers as `Pending`.
5. An admin sends the cash to your phone and approves the ticket. Tokens are permanently deducted from your wallet.

---

## 👑 Chapter 3: The Admin Manual

### 3.1 Platform Health & Real-Time Auditing

**Dashboard route:** `/admin`

- **Live analytics** — requests to `/api/admin/analytics` populate charts with monthly registration metrics, transaction history, and cash flow cycles.
- **Platform revenue ledger** — tracks system commission, total deposit transactions, and processed withdrawals.

---

### 3.2 Tutor Applications Review Queue

1. Navigate to `/admin` → **Tutor Applications** manager.
2. Click **Review** on any pending application.
3. The interface displays the official grade report PDF/image from Cloudinary.
4. **Actions:**
   - **Approve** — Click **Approve Application** at `/admin/verify_tutor/<id>`. The tutor receives a verified badge and a welcome email via Brevo.
   - **Reject** — Enter a specific rejection reason and click **Reject Application**. The tutor is notified immediately and may re-submit updated files.

---

### 3.3 Ledger Moderation & Mobile Gateway Approvals

**Processing bKash/Nagad Deposits:**

1. Open the **Token Purchase Requests** manager.
2. Verify the submitted BDT amount and TxID against your merchant account dashboard.
3. If valid → click **Approve** at `/admin/purchase/<id>/approve`. Tokens are credited to the user.
4. If invalid or fraudulent → click **Reject**.

**Processing Tutor Cash-Outs:**

1. Open the **Withdrawal Requests** manager.
2. Review the tutor's mobile number, BDT amount, and wallet balance.
3. Send the money to their phone via your bKash/Nagad merchant panel.
4. Click **Complete Request** at `/admin/withdraw/<id>/approve`. Tokens are permanently deducted.

---

### 3.4 Dispute Arena & Auditing Dashboard

**Route:** `/admin/disputes`

```
User files dispute  →  Admin audits logs  →  Refund student OR Release to tutor
```

**Process:**

1. Users file disputes at `/dispute/<id>`. View all open cases at `/admin/disputes`.
2. Click **Audit** on any active case. The session audit dashboard shows:
   - **SocketIO chat log** — every message exchanged between tutor and student.
   - **Room connection timestamps** — exact join/disconnect times for both parties.
3. **Resolution actions:**
   - **Refund Student** — if the audit confirms the tutor did not attend or failed to teach.
   - **Release Escrow** — if the student attended but refuses to provide the completion code.
4. Close the dispute.

**Example audit report:**
```
Dispute #14 | Booking ID: 412 | CSE 347
Student claim: "Tutor never joined the Jitsi video class."
Tutor join time: NEVER ENTERED
Student join time: 15:30:12 UTC
→ Action: Refund Student
```

---

### 3.5 System-Level Commands & Moderation

| Action | Route | Effect |
|---|---|---|
| Suspend account | `/admin/user/<id>/toggle_suspend` | Sets status to `Suspended`, terminates sessions |
| Reset password | `/admin/user/<id>/set_password` | Emergency password recovery |
| View active sessions | `/admin/sessions` | Oversee all active booking rooms |
| Force-close session | `/admin/booking/<id>/force_close` | End stalled or stuck sessions |

---

## 🛡️ Security Model

| Layer | Details |
|---|---|
| Database | Supabase PostgreSQL with **Row Level Security (RLS) enabled** |
| Public access | Anon key cannot directly read/write `wallet` or `booking` tables |
| Server access | Only the Flask server (database owner role) can mutate financial balances |
| Escrow | Tokens locked on booking; unlocked only by completion code or admin action |
| File storage | Transcripts and course materials stored securely in **Cloudinary** |
| Email | Automated notifications powered by **Brevo** |
| Video | Encrypted peer-to-peer sessions via **Jitsi** |

---

*StudyByte — empowering university students to learn and earn through peer knowledge sharing.*
