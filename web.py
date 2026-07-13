import json
import html
import uuid

from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

sessions = {}


@app.route('/')
def index():
    return render_template_string(MAIN_PAGE)

@app.route('/diagnosis')
def diagnosis():
    session_id = str(uuid.uuid4())
    sessions[session_id] = DiagnosisFlow()
    return render_template_string(DIAGNOSIS_PAGE, session_id=session_id)

@app.route('/api/question')
def get_question():
    session_id = request.args.get('session_id')

    if not session_id or session_id not in sessions:
        return jsonify({'status': 'error', 'message': 'Invalid session'})

    flow = sessions[session_id]
    question = flow.get_current_question()

    if not question:
        # Run diagnosis
        disease, symptoms = flow.run_diagnosis()
        sessions[session_id].result = {'disease': disease, 'symptoms': symptoms}
        return jsonify({
            'status': 'complete',
            'result': {
                'disease': disease,
                'symptoms': symptoms
            }
        })

    # Generate HTML for the question
    question_html = ''

    if question['type'] == 'text':
        question_html = f'''
        <div class="question-section">
            <div class="question">{question["question"]}</div>
            <input type="text" class="text-input" id="text-answer" placeholder="Type your answer..." autofocus>
            <button class="submit-btn" onclick="submitText()">Continue</button>
        </div>
        '''

    elif question['type'] == 'yesno':
        question_html = f'''
        <div class="question-section">
            <div class="question">{question["question"]}</div>
            <div class="yes-no-buttons">
                <button class="yes-btn" onclick="submitAnswer('yes')">Yes</button>
                <button class="no-btn" onclick="submitAnswer('no')">No</button>
            </div>
        </div>
        '''

    elif question['type'] == 'select':
        options_html = ''.join([
            f'<button class="option-btn" onclick=\'submitAnswer({json.dumps(opt)})\'>{html.escape(opt)}</button>'
            for opt in question['options']
        ])
        question_html = f'''
        <div class="question-section">
            <div class="question">{question["question"]}</div>
            <div class="options">
                {options_html}
            </div>
        </div>
        '''

    elif question['type'] == 'multi':
        options_html = ''.join([
            f'''
            <label class="checkbox-label">
                <input type="checkbox" onchange='toggleCheckbox({json.dumps(opt)}, this)'>
                <span>{html.escape(opt)}</span>
            </label>
            '''
            for opt in question['options']
        ])
        question_html = f'''
        <div class="question-section">
            <div class="question">{question["question"]}</div>
            <div class="checkbox-group">
                {options_html}
            </div>
            <button class="submit-btn" onclick="submitMultiSelect()">Continue</button>
        </div>
        '''

    return jsonify({
        'status': 'question',
        'step': len(flow.answers) + 1,
        'html': question_html,
        'key': question.get('key', ''),
        'question': question
    })

@app.route('/api/answer', methods=['POST'])
def submit_answer():
    data = request.json
    session_id = data.get('session_id')
    key = data.get('key')
    answer = data.get('answer')

    if session_id in sessions:
        flow = sessions[session_id]
        if key:
            flow.submit_answer(key, answer)
            disease, symptoms = diagnose_from_answers(flow.answers)
            if disease and flow.prediction_prompted != disease:
                flow.prediction_prompted = disease
                return jsonify({
                    'status': 'predicted',
                    'prediction': {
                        'disease': disease,
                        'symptoms': symptoms
                    }
                })
            flow.prediction_prompted = disease

    return jsonify({'status': 'ok'})