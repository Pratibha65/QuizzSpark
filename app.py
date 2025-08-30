from flask import Flask, render_template, request, jsonify, session, send_file
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from PyPDF2 import PdfReader, PdfWriter
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_session import Session
from flask_babel import Babel, _
import os
import google.generativeai as genai
import json
import re
import io

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

# CORS(app)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_secret")  # fallback for local dev

app.config["SECRET_KEY"]  # for signing session ID
app.config["SESSION_TYPE"] = "filesystem"      # stores session data on server disk
app.config["SESSION_PERMANENT"] = False        # clears when browser closes
Session(app)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") 
genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel('gemini-2.0-flash')

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
@limiter.limit("3 per minute")
def ask_gemini():
    topic = request.json.get('topic', 'General Knowledge')
    difficulty = request.json.get('difficulty', 'medium')
    num_questions = int(request.json.get('num_questions', 10))
    language = session.get('language', 'en')  # default English

    batch_size = 10  # how many questions to fetch per call
    all_questions = []
    all_answers = []

    while len(all_questions) < num_questions:
        remaining = num_questions - len(all_questions)
        count = min(batch_size, remaining)

        user_query = f"""
        Generate exactly {count} multiple-choice questions on the topic "{topic}".
        Difficulty: {difficulty}. The quiz must be strictly in language {language}.
        Each question must have 4 options labeled A-D, and the correct answer in a separate field.

        Respond strictly in this JSON format:
        [
        {{
            "question": "...",
            "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
            "answer": "B"
        }}
        ]
        """

        response = model.generate_content(user_query)
        raw_text = response.text.strip()
        clean_text = re.sub(r"```(?:json)?|```", "", raw_text).strip()

        try:
            quiz_batch = json.loads(clean_text)
        except json.JSONDecodeError:
            print("JSON parsing failed, raw response was:", clean_text)
            quiz_batch = []

        # sanitize
        for q in quiz_batch:
            opts = [opt.strip() for opt in q["options"]]
            ans = q["answer"].strip().upper()[:1]  # A/B/C/D
            all_questions.append({"question": q["question"], "options": opts})
            all_answers.append(ans)

    # keep only requested amount (in case model overshot)
    all_questions = all_questions[:num_questions]
    all_answers = all_answers[:num_questions]

    # save in session for grading later
    session["quiz"] = all_questions
    session["answers"] = all_answers
    session["topic"] = topic
    session["difficulty"] = difficulty
    session["num_questions"] = num_questions

    return jsonify({"quiz": all_questions})

@app.route('/submit-quiz', methods=['POST'])
def submit_quiz():
    try:
        user_answers = request.json.get('answers', [])
        correct_answers = session.get('answers', [])
        quiz = session.get("quiz", [])
        topic = session.get("topic", "Unknown")
        difficulty = session.get("difficulty", "Unknown")

        score = 0
        feedback = []
        for i, user_ans in enumerate(user_answers):
            user_ans = user_ans.strip().upper()[:1]
            correct = correct_answers[i] if i < len(correct_answers) else ""
            is_correct = user_ans == correct
            feedback.append({
                "question_number": i + 1,
                "question": quiz[i]["question"] if i < len(quiz) else "",
                "user_answer": user_ans,
                "correct_answer": correct,
                "is_correct": is_correct
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
            "difficulty": difficulty
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
        score = session.get("score", 0)
        topic = session.get("topic", "Unknown")
        difficulty = session.get("difficulty", "Unknown")

        content_buffer = io.BytesIO()
        doc = SimpleDocTemplate(content_buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        elements = []
        # ... (your existing code to build the 'elements' list with paragraphs is perfect)
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
            for opt in q.get("options", []):
                elements.append(Paragraph(opt, styles['Normal']))
            user_ans = user_answers[i] if i < len(user_answers) else "Not answered"
            elements.append(Paragraph(f"Your Answer: {user_ans}", styles['Normal']))
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
