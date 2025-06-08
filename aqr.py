from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from pymongo import MongoClient
from flask_cors import CORS
import os
import logging
from bson import ObjectId

app = Flask(__name__)
app.secret_key = os.urandom(24)

CORS(app, supports_credentials=True, resources={r"/*": {"origins": ["http://localhost:5000"]}})

# Logging setup
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# MongoDB setup
try:
    client = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=5000)
    client.server_info()
    db = client['aptitude_db']
    collection = db['questions']
    user_collection = db['login']
    result_collection = db['results']
    logger.info("MongoDB connected successfully.")
except Exception as e:
    logger.error(f"MongoDB connection failed: {e}")

ITEMS_PER_PAGE = 5

@app.route('/')
def home():
    user_email = session.get('user_email')
    return render_template('aqrhome.html', user_email=user_email)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/participate/question')
def participate_question():
    return redirect(url_for('participate'))

@app.route('/analysis')
def status():
    if 'user_email' not in session:
        return redirect(url_for('home'))

    user_email = session['user_email']
    result = result_collection.find_one({'email': user_email}) or {'score': 0}

    stats = {
        'username': user_email.split('@')[0],
        'score': result['score'],
        'max_score': 2500
    }
    return render_template('analysis.html', stats=stats)

@app.route('/participate')
def participate():
    if 'user_email' not in session:
        return redirect(url_for('home'))

    page = request.args.get('page', 1, type=int)
    total_questions = collection.count_documents({})
    total_pages = (total_questions + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start = (page - 1) * ITEMS_PER_PAGE
    paginated_questions = list(collection.find().skip(start).limit(ITEMS_PER_PAGE))

    user_email = session['user_email']
    result = result_collection.find_one({'email': user_email}) or {}
    completed_ids = [str(qid) for qid in result.get('completed_questions', [])]

    for q in paginated_questions:
        q['completed'] = str(q['_id']) in completed_ids

    return render_template('quiz.html', problems=paginated_questions, current_page=page, total_pages=total_pages)

@app.route('/question/<concept>', methods=['GET', 'POST'])
def question(concept):
    if 'user_email' not in session:
        return redirect(url_for('home'))

    # Fetch current question
    question_data = collection.find_one({'slug': concept})
    if not question_data:
        return "Question not found", 404

    # Find all slugs to calculate previous/next
    # Only get documents where 'slug' field exists
    all_slugs = list(collection.find({'slug': {'$exists': True}}, {'slug': 1, '_id': 0}))
    slug_list = [q['slug'] for q in all_slugs]

    try:
        index = slug_list.index(concept)
    except ValueError:
        return "Invalid slug", 404

    prev_slug = slug_list[index - 1] if index > 0 else None
    next_slug = slug_list[index + 1] if index < len(slug_list) - 1 else None

    # POST request logic (answer submitted)
    if request.method == 'POST':
        selected_answer = request.form['answer']
        correct = selected_answer == question_data['answer']

        if correct:
            user_email = session['user_email']
            question_id = question_data['_id']
            result = result_collection.find_one({'email': user_email})

            if result:
                completed = result.get('completed_questions', [])
                if question_id not in completed:
                    result_collection.update_one(
                        {'email': user_email},
                        {
                            '$inc': {'score': 10},
                            '$push': {'completed_questions': question_id}
                        }
                    )
            else:
                result_collection.insert_one({
                    'email': user_email,
                    'score': 10,
                    'completed_questions': [question_id]
                })

        return render_template(
            'question.html',
            question_data=question_data,
            selected=selected_answer,
            correct=correct,
            prev_slug=prev_slug,
            next_slug=next_slug
        )

    # GET request logic (show question)
    return render_template(
        'question.html',
        question_data=question_data,
        prev_slug=prev_slug,
        next_slug=next_slug
    )


@app.route('/leaderboard')
def leaderboard():
    users = list(result_collection.find({}, {'_id': 0, 'email': 1, 'score': 1}))
    
    # Sort users by score descending
    users.sort(key=lambda x: x['score'], reverse=True)
    
    leaderboard_data = []
    prev_score = None
    rank = 0
    actual_position = 0

    for user in users:
        actual_position += 1
        if user['score'] != prev_score:
            rank = actual_position
            prev_score = user['score']
        leaderboard_data.append({'rank': rank, 'email': user['email'], 'score': user['score']})

    return render_template('leader board.html', leaderboard=leaderboard_data)

# Manual Signup
@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    confirm_password = data.get('confirm_password')

    if password != confirm_password:
        return jsonify({'success': False, 'error': 'Passwords do not match'})

    if user_collection.find_one({'email': email}):
        return jsonify({'success': False, 'error': 'User already exists'})

    user_collection.insert_one({'email': email, 'password': password})
    session['user_email'] = email
    return jsonify({'success': True, 'email': email})

# Manual Login
@app.route('/manual-login', methods=['POST'])
def manual_login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    user = user_collection.find_one({'email': email})
    if not user or user['password'] != password:
        return jsonify({'success': False, 'error': 'Invalid email or password'})

    session['user_email'] = email
    return jsonify({'success': True, 'email': email})

if __name__ == '__main__':
    app.run(debug=True)
