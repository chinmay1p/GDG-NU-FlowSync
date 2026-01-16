# 🚀 FlowSync
### Team: Travelling Salesmen

An all-in-one **project management, task management, and meeting intelligence platform** that connects **Slack, GitHub, dashboards, and Google Meet** to ensure that **no action item is ever lost**.

---

## 📌 Problem Statement

In most teams today:
- Tasks discussed in meetings are forgotten
- Action items are scattered across Slack, GitHub, and calendars
- Managers manually translate conversations into work
- Employees lack clarity on priorities and deadlines

Our platform solves this by **connecting meetings, tasks, and collaboration tools into a single workflow**.

---

## ✨ Key Features

### 🏢 Organization & Team Management
- Create or join organizations using a **6-digit join code**
- Role-based access:
  - **Admin**
  - **Manager**
  - **Employee**
- Team creation and member assignment using **real email IDs**
- One user can belong to multiple teams with different roles

---

### 📊 Role-Based Dashboards
- **Admin Dashboard**
  - Org overview
  - Teams & members
  - All tasks visibility
- **Manager Dashboard**
  - Task assignment
  - Approval control
  - Slack & GitHub integrations
- **Employee Dashboard**
  - Assigned tasks
  - Priorities & deadlines
  - GitHub issue links

---

### ✅ Task Management System
- Tasks have:
  - Title
  - Priority
  - Status
  - Assignee
  - Optional GitHub issue link
- Two task types:
  1. **GitHub Tasks** (create GitHub issues)
  2. **Internal Tasks** (dashboard + calendar only)
- Managers approve tasks before execution

---

### 🗓️ Calendar View
- Tasks visualized in a **calendar layout**
- Helps teams plan work around deadlines

---

### 🔌 Slack Integration
- Assign tasks directly from Slack using a slash command:
- Slack command: /assign email@example.com Task description priority=high
- Instantly acknowledges request (no timeout)
- Creates task asynchronously
- Optionally creates a GitHub issue
- Slack user email is mapped to platform user automatically

---

### 🧑‍💻 GitHub Integration
- Managers link a GitHub repository at project level
- Approved tasks can:
- Create GitHub issues
- Sync issue URL back to dashboard
- Real GitHub API integration using secure tokens

---

### 🎙️ Google Meet Integration (Meeting Intelligence)
- Chrome Extension detects active Google Meet sessions
- Meeting session token connects extension to backend
- Audio capture pipeline (tab audio)
- Task detection engine triggers **action item popups**
- Manager approves detected tasks
- Approved tasks sync to:
- Dashboard
- GitHub
- Slack

---

## 🧠 AI Capabilities
- Action item detection (meeting intelligence)
- Task reasoning and prioritization
- Designed for Gemini-powered reasoning (lazy-loaded for stability)
- AI decisions are **never auto-executed** — always manager-approved

---

## 🛠️ Tech Stack

### Frontend
- **React + Vite**
- **Tailwind CSS**
- Firebase Authentication
- WebSocket client for real-time updates

### Backend
- **FastAPI (Python)**
- Firebase Admin SDK
- Firestore (primary database)
- WebSockets
- Background task processing
- Slack API
- GitHub API

### Chrome Extension
- Manifest V3
- Google Meet DOM integration
- Firebase Auth
- WebSocket communication

---

## ☁️ Google Technologies Used

- **Firebase Authentication**  
Secure login using real Google accounts

- **Firebase Firestore**  
Single source of truth for orgs, teams, users, and tasks

- **Firebase Admin SDK**  
Server-side verification and access control

- **Google Meet (via Chrome Extension)**  
Live meeting detection and interaction

- **Gemini (planned / integrated)**  
Task reasoning and meeting intelligence

---

## 🔐 Security & Design Principles
- No static users or mock data
- All users authenticated via Firebase
- Backend re-validates:
- Org membership
- Team role
- Permissions
- Slack requests verified using signing secret
- No trust in frontend for access control
- AI never auto-executes actions

---




