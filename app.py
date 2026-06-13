import time
from google.api_core.exceptions import ResourceExhausted
from flask import Flask, render_template, request, jsonify, session, send_file
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from PyPDF2 import PdfReader, PdfWriter
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_session import Session
from flask_babel import Babel, _
from flask_sqlalchemy import SQLAlchemy
from flask import url_for
import uuid
import os
import google.generativeai as genai
import json
import re
import io

# --- IMPORT FROM NEW FILE ---
from models import db, Challenge


#for hindi font
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
HINDI_FONT_NAME = 'DevanagariUnicode' 
HINDI_FONT_FILE = 'NotoSansDevanagari-Regular.ttf' # *** USER MUST DOWNLOAD AND PLACE THIS 

try:
    # 1. Try a common Windows Hindi font path first
    pdfmetrics.registerFont(TTFont(HINDI_FONT_NAME, HINDI_FONT_FILE))
except Exception as e:
    # 2. Fallback to a well-known font name (may still fail if not present)
    print(f"Warning: Failed to load Hindi font at {HINDI_FONT_FILE}. Error: {e}")
    try:
        # Try a more generic widely available font that may include Devanagari
        pdfmetrics.registerFont(TTFont(HINDI_FONT_NAME, 'arialuni.ttf')) # Arial Unicode MS
    except:
        # 3. Final fallback: Register 'Helvetica' but Hindi text will likely still fail (show squares)
        pdfmetrics.registerFont(TTFont(HINDI_FONT_NAME, 'Helvetica'))
        print("Final Fallback: Using Helvetica. Hindi characters may not render correctly.")

load_dotenv()

# Create Flask app
app = Flask(__name__)

# Babel Configuration
# ...
app.config['BABEL_DEFAULT_LOCALE'] = 'en'

def get_locale():
    # This function is now defined without a decorator
    return session.get('language', 'en')

# Pass the function directly when initializing Babel
babel = Babel(app, locale_selector=get_locale)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per hour"]  # fallback if no custom limit is set
)

# --- DATABASE CONFIGURATION ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///quizzes.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 

# Bind the database to this specific app instance
db.init_app(app)

# Create the tables if they don't exist yet
with app.app_context():
    db.create_all()

# CORS(app)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_secret")  # fallback for local dev

app.config["SECRET_KEY"]  # for signing session ID
app.config["SESSION_TYPE"] = "filesystem"      # stores session data on server disk
app.config["SESSION_PERMANENT"] = False        # clears when browser closes
Session(app)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") 
genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel('gemini-2.5-flash')

LETTER_TO_INDEX = {"A": 0, "B": 1, "C": 2, "D": 3}
INDEX_TO_LETTER = "ABCD"



# Homepage route
@app.route('/')
def home():
    return render_template('index.html', lang=get_locale())

@app.route('/set-language', methods=['POST'])
def set_language():
    data = request.get_json()
    lang = data.get('language', 'en')
    session['language'] = lang
    return jsonify({"status": "ok", "language": lang})


# Route to handle Gemini queries
@app.route('/ask-gemini', methods=['POST'])
@limiter.limit("12 per minute")
def ask_gemini():
    topic = request.json.get('topic', 'General Knowledge')
    difficulty = request.json.get('difficulty', 'medium')
    num_questions = int(request.json.get('num_questions', 10))
    language = session.get('language', 'en')  # default English
    question_type = request.json.get('question_type', 'multiple-choice')

    batch_size = 10  # how many questions to fetch per call
    all_questions = []
    all_answers = []
    max_attempts = 5
    attempts = 0

    while attempts<max_attempts and len(all_questions) < num_questions:
        remaining = num_questions - len(all_questions)
        count = min(batch_size, remaining)
        attempts += 1

        if question_type == 'true-false':
            user_query = f"""
            Generate exactly {count} true/false questions on the topic "{topic}".
            Difficulty: {difficulty}. The quiz must be strictly in language {language}.
            Each question must have exactly two options labeled A and B, "A. True" and "B. False". The correct answer must be in a separate field. Also, provide an explanation for the correct answer.

            Respond strictly in this JSON format:
            [
            {{
                "question": "...",
                "options": ["A. True", "B. False"],
                "answer": "A",
                "explanation":"This is the explanation for the correct answer..."
            }}
            ]
            """
        else: 
            user_query = f"""
            Generate exactly {count} multiple-choice questions on the topic "{topic}".
            Difficulty: {difficulty}. The quiz must be strictly in language {language}.
            Each question must have 4 options labeled A-D, and the correct answer in a separate field.
            Also, provide an explanation for the correct answer.

            Respond strictly in this JSON format:
            [
            {{
                "question": "...",
                "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
                "answer": "B",
                "explanation":"This is the explanation for the correct answer..."
            }}
            ]
            """
        try:
            response = model.generate_content(
                user_query,
                generation_config={"response_mime_type": "application/json"}
            )
            raw_text = response.text.strip()
            clean_text = re.sub(r"```(?:json)?|```", "", raw_text).strip()

        
            quiz_batch = json.loads(clean_text)

            # Process each question defensively
            for q in quiz_batch:
                # 1. Ensure the item is a dictionary and contains all mandatory keys
                if not isinstance(q, dict) or not all(k in q for k in ("question", "options", "answer")):
                    print("Warning: Skipping malformed question object missing required fields:", q)
                    continue
                
                # 2. Ensure 'options' is actually an iterable list
                if not isinstance(q["options"], list):
                    print("Warning: 'options' field is not a list. Skipping question:", q.get("question"))
                    continue

                try:
                    # 3. Clean and extract fields safely
                    opts = [str(opt).strip() for opt in q["options"]]
                    ans = str(q["answer"]).strip().upper()[:1]
                    explanation = q.get("explanation", "No explanation provided.")

                    all_questions.append({
                        "question": str(q["question"]),
                        "options": opts,
                        "explanation": str(explanation)
                    })
                    all_answers.append(ans)
                except Exception as item_error:
                    print(f"Warning: Failed to process individual question. Error: {item_error}")
                    continue

            # sanitize
            # for q in quiz_batch:
            #     opts = [opt.strip() for opt in q["options"]]
            #     ans = q["answer"].strip().upper()[:1]  # A/B/C/D
            #     all_questions.append({"question": q["question"], "options": opts, "explanation": q.get("explanation", "No explanation provided.")})
            #     all_answers.append(ans)
        except ResourceExhausted:
            print("Rate limit hit, waiting...")
            time.sleep(15)
            continue
        except json.JSONDecodeError:
            print("Invalid JSON returned by AI. Skipping...")
            continue
        except Exception as e:
            # This prevents internet drops or API hiccups from crashing your server!
            print(f"Unexpected connection or API error: {e}")
            continue

        

    # keep only requested amount (in case model overshot)
    all_questions = all_questions[:num_questions]
    all_answers = all_answers[:num_questions]

    if not all_questions:
        return jsonify({
            "error": "The AI quiz generator is temporarily busy or returned invalid formatting. Please try again in 15 seconds."
        }), 502

    # save in session for grading later
    session["quiz"] = all_questions
    session["answers"] = all_answers
    session["topic"] = topic
    session["difficulty"] = difficulty
    session["num_questions"] = num_questions
    
    # --- NEW: SAVE TO DATABASE FOR SHARING ---
    challenge_id = str(uuid.uuid4())
    new_challenge = Challenge(
        id=challenge_id,
        topic=topic,
        difficulty=difficulty,
        quiz_data=json.dumps(all_questions),
        answers_data=json.dumps(all_answers)
    )
    db.session.add(new_challenge)
    db.session.commit()

    # Generate the full, live URL dynamically
    challenge_link = url_for('load_challenge', challenge_id=challenge_id, _external=True)

    return jsonify({
        "quiz": all_questions, 
        "challenge_id": challenge_id,
        "challenge_link": challenge_link  # Send the full link to the frontend
    })


@app.route('/challenge/<challenge_id>')
def load_challenge(challenge_id):
    # Fetch the challenge from the DB, or return 404 if it doesn't exist
    challenge = Challenge.query.get_or_404(challenge_id)
    
    # Load the JSON strings back into Python lists
    quiz_questions = json.loads(challenge.quiz_data)
    quiz_answers = json.loads(challenge.answers_data)
    
    # Populate this new user's session with the fetched data
    session["quiz"] = quiz_questions
    session["answers"] = quiz_answers
    session["topic"] = challenge.topic
    session["difficulty"] = challenge.difficulty
    session["num_questions"] = len(quiz_questions)
    
    # Render the homepage, but pass a special flag: is_challenge=True
    return render_template('index.html', lang=get_locale(), is_challenge=True, injected_quiz=quiz_questions)

@app.route('/submit-quiz', methods=['POST'])
def submit_quiz():
    try:
        user_answers = request.json.get('answers', [])
        correct_answers = session.get('answers', [])
        quiz = session.get("quiz", [])
        topic = session.get("topic", "Unknown")
        difficulty = session.get("difficulty", "Unknown")
        explanations = [q.get('explanation') for q in quiz]

        score = 0
        feedback = []
        for i, user_ans in enumerate(user_answers):
            user_ans = user_ans.strip().upper()[:1]
            correct = correct_answers[i] if i < len(correct_answers) else ""
            explanation = explanations[i] if i < len(explanations) else ""
            is_correct = user_ans == correct
            feedback.append({
                "question_number": i + 1,
                "question": quiz[i]["question"] if i < len(quiz) else "",
                "user_answer": user_ans,
                "correct_answer": correct,
                "is_correct": is_correct,
                "explanation": explanation 
            })
            if is_correct:
                score += 1

        # save user answers in session for PDF download
        session["user_answers"] = user_answers
        session["score"] = score

        return jsonify({
            "score": score,
            "total": len(correct_answers),
            "feedback": feedback,
            "topic": topic,
            "difficulty": difficulty,
            "quiz": quiz
        })
    except Exception as e:
        print("Error in /submit-quiz:", e)
        return jsonify({"error": str(e)}), 500
    

# Function to add a watermark to each page
def add_watermark(canvas, doc):
    """
    This function is called on each page. It draws a watermark in the background.
    """
    canvas.saveState()
    
    # Move the origin (the (0,0) point) to the center of the page
    canvas.translate(doc.width / 2.0, doc.height / 2.0)
    
    # Rotate the canvas by 45 degrees
    canvas.rotate(45)
    
    # Set the font, color, and transparency
    canvas.setFont('Helvetica', 60)
    # Use RGB with an alpha for transparency (0.8, 0.8, 0.8 is a light gray)
    canvas.setFillColorRGB(0.8, 0.8, 0.8, alpha=0.5)
    
    # Draw the string at the new origin (0,0), which is now the page center
    canvas.drawCentredString(0, 0, "QuizzSpark.com")
    
    canvas.restoreState()


# In app.py, replace your entire download_pdf route with this

@app.route('/download_pdf')
def download_pdf():
    try:
        # --- PART 1: Create the main content PDF in memory ---
        quiz = session.get("quiz", [])
        # ... (get all your other session data as before)
        user_answers = session.get("user_answers", [])
        correct_answers = session.get('answers', [])
        score = session.get("score", 0)
        topic = session.get("topic", "Unknown")
        difficulty = session.get("difficulty", "Unknown")

        content_buffer = io.BytesIO()
        doc = SimpleDocTemplate(content_buffer, pagesize=A4)

        styles = getSampleStyleSheet()
        green_style = ParagraphStyle(
            name='GreenNormal',
            parent=styles['Normal'],
            textColor=colors.green
        )

        elements = []

        # Title
        elements.append(Paragraph(f"<b>Quiz Results</b>", styles['Title']))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph(f"Topic: {topic}", styles['Normal']))
        elements.append(Paragraph(f"Difficulty: {difficulty}", styles['Normal']))
        elements.append(Paragraph(f"Score: {score}/{len(quiz)}", styles['Normal']))
        elements.append(Spacer(1, 24))

        # Loop for questions
        for i, q in enumerate(quiz):
            elements.append(Paragraph(f"Q{i+1}. {q['question']}", styles['Heading3']))

            # Find the full option text for the correct answer
            correct_ans_letter = correct_answers[i] if i < len(correct_answers) else ""
            correct_ans_text = next((opt for opt in q.get("options", []) if opt.startswith(correct_ans_letter)), "Not found")

            for opt in q.get("options", []):
                if opt == correct_ans_text:
                    elements.append(Paragraph(opt, green_style))
                else:
                    elements.append(Paragraph(opt, styles['Normal']))

            user_ans_text = "Not answered"
            if i < len(user_answers) and user_answers[i]:
                # Find the full option text for the user's answer
                user_ans_text = next((opt for opt in q.get("options", []) if opt.startswith(user_answers[i])), "Not answered")

            

            explanation = q.get("explanation", "No explanation provided.")

            elements.append(Spacer(1, 6))
            elements.append(Paragraph(f"Your Answer: {user_ans_text}", styles['Normal']))
            elements.append(Spacer(1, 6))
            elements.append(Paragraph(f"Correct Answer: {correct_ans_text}", styles['Normal']))
            elements.append(Spacer(1, 6))
            elements.append(Paragraph(f"<b>Explanation:</b> {explanation}", styles['Normal']))
            elements.append(Spacer(1, 12))
            
        doc.build(elements)
        content_buffer.seek(0)
        
        # --- PART 2: Create the watermark PDF in memory ---
        watermark_buffer = io.BytesIO()
        c = canvas.Canvas(watermark_buffer, pagesize=A4)
        c.translate(A4[0]/2.0, A4[1]/2.0)
        c.rotate(45)
        c.setFont("Helvetica", 60)
        c.setFillColorRGB(0.8, 0.8, 0.8, alpha=0.5)
        c.drawCentredString(0, 0, "QuizzSpark.com")
        c.save()
        watermark_buffer.seek(0)

        # --- PART 3: Merge the watermark onto the content PDF ---
        output_writer = PdfWriter()
        content_reader = PdfReader(content_buffer)
        watermark_reader = PdfReader(watermark_buffer)
        watermark_page = watermark_reader.pages[0]

        for page in content_reader.pages:
            page.merge_page(watermark_page)
            output_writer.add_page(page)

        # --- PART 4: Serve the final, merged PDF ---
        final_pdf_buffer = io.BytesIO()
        output_writer.write(final_pdf_buffer)
        final_pdf_buffer.seek(0)

        return send_file(
            final_pdf_buffer,
            as_attachment=True,
            download_name="quiz_results_watermarked.pdf",
            mimetype="application/pdf"
        )
    except Exception as e:
        print(f"Error generating PDF: {e}")
        return "Error generating PDF", 500


def _load_font(size=36, bold=False):
    try:
        # Common on Linux containers
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


@app.route('/scorecard.png')
def scorecard_png():
    topic = session.get("topic", "Unknown")
    difficulty = session.get("difficulty", "Unknown").title()
    score = session.get("score", 0)
    total = len(session.get("quiz", [])) or session.get("num_questions", 0)

    # Canvas
    W, H = 1200, 630
    bg = (18, 18, 18)              # #121212
    accent = (0, 224, 198)         # teal
    text_primary = (245, 245, 245) # near-white
    text_muted = (180, 180, 180)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    # Rounded card
    card_margin = 60
    card_radius = 28
    card_bbox = [card_margin, card_margin, W - card_margin, H - card_margin]
    # draw rounded rectangle (Pillow >= 8.2)
    draw.rounded_rectangle(card_bbox, radius=card_radius, fill=(28, 28, 28), outline=accent, width=4)

    # Text
    title_font   = _load_font(60, bold=True)
    big_font     = _load_font(100, bold=True)
    label_font   = _load_font(36, bold=False)
    tag_font     = _load_font(40, bold=True)
    foot_font    = _load_font(30, bold=False)

    # Brand line
    brand = "Gemini Quiz Generator"
    draw.text((card_margin + 40, card_margin + 30), brand, font=title_font, fill=text_primary)

    # Topic & difficulty
    topic_text = f"{topic} Quiz"
    diff_text = f"Difficulty: {difficulty}"
    draw.text((card_margin + 40, card_margin + 130), topic_text, font=tag_font, fill=text_primary)
    draw.text((card_margin + 40, card_margin + 190), diff_text, font=label_font, fill=text_muted)

    # Score
    score_label = "Score"
    draw.text((card_margin + 40, card_margin + 290), score_label, font=label_font, fill=text_muted)

    score_text = f"{score} / {total}"
    # center the big score inside the card horizontally
    tw, th = draw.textbbox((0,0), score_text, font=big_font)[2:]
    draw.text(((W - tw) // 2, card_margin + 340), score_text, font=big_font, fill=accent)

    # Footer CTA
    cta = "Test your skills → QuizzSpark.com/quiz"
    draw.text((card_margin + 40, H - card_margin - 60), cta, font=foot_font, fill=text_primary)

    # Return as PNG
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png", download_name="scorecard.png")



# Run the app
if __name__ == '__main__':
    app.run(debug=False)
