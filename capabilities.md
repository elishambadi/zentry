🗂 Core Modules
1. Task Management
Create tasks with: title, date, tag (Physical / Spiritual / Work / Relationships / Bonus), priority (Low–Urgent), rest flag
Subtasks (add, toggle, delete)
Notes on tasks & subtasks
Links attached to tasks
Toggle complete, delete, edit
Carry over incomplete tasks to next day
Recurrence: one-time, daily, weekly, custom days (with end date)
2. Daily View
Day-by-day task dashboard
Add tasks, ideas, and journal entries inline
View overdue/carried-over tasks from previous days
Daily mood tracking (Very Happy → Very Sad + notes)
3. Daily Journal
Rich journal editor per day
Per-user, per-date entries
4. Calendar
Month view & Week view
Visualize tasks across dates
5. Goals
Short-term & long-term goals with images, descriptions, target dates
Mark complete/incomplete
Link tasks to goals (many-to-many via TaskGoal)
Auto-creates a "Celebrate" bonus task on goal creation
6. Ideas Board
Capture raw ideas (title + description)
AI breakdown: generates clarifying questions and task lists from an idea
Convert idea → task directly
View converted vs. active ideas
7. Notebooks
Create notebooks with pages and blocks (content blocks + images)
Comments on blocks
Print view for notebooks
8. Pomodoro Focus Mode
Shows today's tasks ranked for deep work
Complete tasks directly from Pomodoro page
Configurable default Pomodoro duration (user preference)
9. Weekly Review
Structured weekly reflection view
10. Monthly Review
Monthly performance/reflection view
🤖 ZenAI (AI Assistant)
Persistent chat sessions (per section: general, task, idea, goal, review)
Goal breakdown: AI breaks a goal into actionable tasks with time-slot scheduling
Idea breakdown: AI asks clarifying questions → generates task list
Add AI-suggested tasks directly to schedule
Context-aware (sees user's goals, ideas, tasks for a given slot)
Session history (stored messages per session)
Calendar-aware: shows busy blocks when scheduling
👤 User & Preferences
Auth via django-allauth (signup, login, logout)
User Preferences: default landing page, monthly reading books, favorite authors, Pomodoro defaults
Per-user data isolation (all data scoped to logged-in user)
📱 PWA (Progressive Web App)
manifest.json + service-worker.js — installable on mobile/desktop
🛠 Tech Stack
Backend: Django, Python, PostgreSQL (Docker)
AI: External LLM API (httpx calls)
Frontend: Tailwind CSS, HTMX/JS, Jinja-style Django templates
Auth: django-allauth
Deployment: Docker + docker-compose
💡 Monetization-Relevant Angles
B2C SaaS — recurring subscription for premium AI features (ZenAI sessions, idea/goal breakdowns)
Freemium — free task/journal/calendar, paid AI + notebooks + recurring tasks
Habit/productivity coaching niche — pairs well with the life-area tagging (Physical, Spiritual, Work, Relationships)
Pomodoro + Goal tracking combo — productivity tool market
PWA = low-friction mobile distribution without app store fees
Data — mood + journal + goal completion data for personal analytics upsell