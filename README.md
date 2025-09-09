# 🎓 Gemini Quiz Generator

![GitHub Repo Size](https://img.shields.io/github/repo-size/Pratibha65/ObsessedQuiz) 
![Python Version](https://img.shields.io/badge/python-3.11-blue) 
![Flask](https://img.shields.io/badge/flask-2.3-green) 
![License](https://img.shields.io/badge/license-MIT-lightgrey)

A modern web app that generates **interactive multiple-choice quizzes** on any topic using the **Google Gemini AI API**. Choose a difficulty level, answer questions, and get a **dynamic score card** with feedback. Share your score or download it as an image!  

---

## 🌟 Features

- Generate **10-question quizzes** on any topic.
- Choose difficulty: **Easy | Medium | Hard**.
- Interactive quiz interface with **radio buttons** for answers.
- Instant scoring with **detailed feedback** for each question.
- **Score card** with topic, difficulty, and your score.
- Share score on **Twitter**.
- **Download score card** as an image.
- Dark-themed, responsive UI for mobile and desktop.

---

## 🛠️ Tech Stack

- **Backend:** Python, Flask, Flask-Session, dotenv  
- **Frontend:** HTML, CSS, JavaScript  
- **AI Integration:** Google Gemini API  
- **Session Handling:** Flask-Session  
- **Image Capture:** html2canvas  

---

## ⚡ Installation & Setup

1. **Clone the repository**
git clone https://github.com/Pratibha65/ObsessedQuiz.git
cd ObsessedQuiz

2. **Create a virtual environment**
python -m venv venv
source venv/bin/activate   # Linux/Mac
venv\Scripts\activate      # Windows


3. **Install dependencies**
pip install -r requirements.txt


4. **Configure environment variables**
Create a .env file in the root directory:
SECRET_KEY=your_secret_key
GEMINI_API_KEY=your_gemini_api_key


5. **Run the Flask app**
python app.py


Open your browser at http://127.0.0.1:5000 to use the app.

🗂️ Project Structure

ObsessedQuiz/
├── templates/
│   └── index.html        # Frontend HTML template
├── static/
│   └── style.css         # CSS styling
├── app.py                # Flask backend
├── requirements.txt      # Python dependencies
└── README.md             # Project documentation


🚀 Usage

1. Enter a topic in the input box.

2. Select the quiz difficulty.

3. Click Generate Quiz.

4. Answer the questions.

5. Click Submit Quiz to see your score card.

**Optionally:** 
Share your score on Twitter.
Download your score card as an image.

📝 License
This project is licensed under the MIT License.

👩‍💻 Author
Pratibha65 / ObsessedORwhat
