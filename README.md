# 🛡️ Store Candidate Background Check & OSINT Verification Assistant

An AI-powered, privacy-first background verification tool designed specifically for store owners and hiring managers. 
Upload a candidate's resume (PDF, DOCX, TXT) or manually enter details to extract career history, verify past employer legitimacy, search public digital presence across professional and social platforms, resolve display avatars, and generate tailored reference check questions—all in strict compliance with EEOC non-discrimination guidelines.

---

## ✨ Features

- **Multi-Format Resume Intake**: Drag and drop PDF, DOCX, or TXT resumes. Instant structured data extraction using Gemini.
- **Candidate Avatar & Photo Discovery**: Automatically checks Gravatar, GitHub, and public Open Graph metadata (`og:image`) to give a face to the name and verify identity against namesakes.
- **Multi-Track Public OSINT Search**:
  - **Professional Footprint**: LinkedIn, GitHub, personal portfolios.
  - **Social Footprint**: Twitter / X, Instagram, Facebook, Reddit (via handle/email derivation).
  - **Employer Legitimacy**: Verifies if past stores/employers exist as registered businesses.
  - **Reference Cross-Check**: Checks if listed references are associated with the claimed company.
- **EEOC Workplace Conduct Firewall**:
  - Flags workplace safety risks (theft bragging, public threats, harassment, past employer disparagement).
  - **Legally Redacts** all protected demographic attributes (race, age, religion, medical conditions, pregnancy, family status) so hiring decisions stay compliant.
- **Tailored Reference Call Kit**: Automatically generates role-specific interview questions based on the applicant's claimed duties, plus a ready-to-use outreach email template and call notes logger.
- **Printable Dossier Export**: One-click download of a clean HTML/PDF summary for interview panels.
- **Cloud Security Gate**: Integrated PIN/Passcode lock screen to protect candidate privacy when hosted online.

---

## 🚀 Running Locally on your MacBook

### 1. Prerequisites
Ensure you have Python 3.9+ installed on your Mac.

### 2. Set Up Virtual Environment & Dependencies
```bash
# Navigate to the project directory
cd "/Users/abysahni/Desktop/research/background check"

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### 3. Configure Your Environment
Create a `.env` file from the example template:
```bash
cp .env.example .env
```
Open `.env` and add your **Google Gemini API Key** (Get a free key from [Google AI Studio](https://aistudio.google.com/)):
```env
GEMINI_API_KEY=your_actual_gemini_api_key_here
STORE_ACCESS_CODE=1234
```

### 4. Launch the App
```bash
streamlit run app.py
```
The app will open automatically in your browser at `http://localhost:8501`.

---

## ☁️ Deploying Online for FREE (Streamlit Community Cloud)

You can deploy this app so you can access it securely from your phone, store iPad, or home computer from anywhere in the world.

### Step 1: Create a Private GitHub Repository
1. Go to [GitHub](https://github.com/new) and create a **New Repository**.
2. **Important:** Set the visibility to **Private** (so your candidate verification tool is not visible to the public).
3. Push this project to GitHub:
   ```bash
   git init
   git add .
   git commit -m "Initial commit of Store Candidate Background Check Tool"
   git branch -M main
   git remote add origin https://github.com/<your-username>/<your-repo-name>.git
   git push -u origin main
   ```

### Step 2: Deploy on Streamlit Community Cloud
1. Go to [share.streamlit.io](https://share.streamlit.io/) and log in with your GitHub account.
2. Click **"New app"** (or **"Create app"**).
3. Select your private GitHub repository, branch (`main`), and set the Main file path to `app.py`.
4. Click **"Advanced settings"** and navigate to the **Secrets** section.
5. Paste your secrets:
   ```toml
   GEMINI_API_KEY = "your_actual_gemini_api_key_here"
   STORE_ACCESS_CODE = "YourStoreSecretPin"
   STORE_NAME = "Your Store Name"
   ```
6. Click **"Deploy!"**

Within ~60 seconds, your app will be live at a custom URL (e.g. `https://yourstore-verify.streamlit.app`).

---

## 🔒 Privacy & Compliance Architecture

1. **Passcode Protection**: When deployed on the web, nobody can access the tool without your store's secret PIN.
2. **In-Memory Candidate Processing**: Uploaded resumes are parsed and verified in-memory during your browser session. No applicant resumes or personal data are stored in a public database.
3. **EEOC Non-Discrimination**: The AI synthesis strictly excludes protected demographic traits from background evaluations.
