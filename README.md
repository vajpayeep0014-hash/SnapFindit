SnapFind — Campus Lost & Found System
A Flask-based web app for Medicaps University that digitises the lost and found process with AI-powered spam detection, image verification, and a conversational chatbot. Access is restricted to @medicaps.ac.in emails.
Authors: Pulkit Vajpayee (EN23CS304055) · Deepesh Nayak (EN24CS3T40001)
Guide: Prof. Vishal Sharma · Prof. Suyog Munshi | B.Tech CSE, Jan–June 2026

Tech Stack:
LayerTechnologyBackendPython 3.10, 
Flask 3.xDatabasePostgreSQL 14 + Flask-SQLAlchemyMediaCloudinary (storage + AI tagging)AI Spam FilterGoogle Gemini 2.0 FlashAI ChatbotGroq API / Llama-3.1-8b-instantAuthWerkzeug, 
smtplib (OTP via Gmail)SecurityFlask-Limiter,
Flask-WTFDeploymentGunicorn on Render

Features:
OTP Registration — restricted to @medicaps.ac.in; passwords hashed with PBKDF2-SHA256
Item Reporting — upload photo + description; Gemini checks for spam before routing to admin
Claim Submission — proof photo analysed by Cloudinary Vision AI; synonym-expansion algorithm scores ownership confidence (0–100)
Dual-tier Admin — Block Admins manage their campus area; Central Admin has full system control and user management
AI Chatbot — floating assistant on every page powered by Groq/Llama
Security — CSRF protection, rate limiting (5 req/min), magic-bytes file validation, HTTP-only session cookies


Installation
bash# 1. Clone and enter the project
git clone <https://github.com/vajpayeep0014-hash/SnapFindit.git> && cd snapfind

# 2. Create virtual environment
python -m venv venv && source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment — copy and fill in credentials
cp .env.example .env

# 5. Set up the database
flask db init && flask db migrate -m "init" && flask db upgrade

# 6. Run
flask run

App runs at https://snapfindit.onrender.com/