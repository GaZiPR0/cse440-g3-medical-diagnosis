#!/usr/bin/env python
import os
import webbrowser
import builtins
from contextlib import contextmanager
import io
from contextlib import redirect_stdout

# Compatibility shim: experta's old `frozendict` dependency references
# `collections.Mapping`, which was moved to `collections.abc` in Python 3.3
# and removed in Python 3.10+. Restore the aliases so experta can import.
import collections
import collections.abc
for _abc_name in ("Mapping", "MutableMapping", "Sequence", "Iterable",
                  "Set", "Callable", "Hashable"):
    if not hasattr(collections, _abc_name):
        setattr(collections, _abc_name, getattr(collections.abc, _abc_name))

try:
    from experta import *
except Exception:
    pass

EXPERTA_AVAILABLE = all(
    name in globals()
    for name in ("KnowledgeEngine", "Fact", "Rule", "AND", "OR", "DefFacts")
)

_ACTIVE_IO = None


class NeedInput(Exception):
    """Raised in web mode when the engine needs the next user response."""

    def __init__(self, question):
        super().__init__(question["prompt"])
        self.question = question


class DiagnosisComplete(Exception):
    """Raised in web mode when the engine reaches a diagnosis."""

    def __init__(self, disease, symptoms):
        super().__init__(disease)
        self.disease = disease
        self.symptoms = symptoms


def _prompt_id(kind, prompt, options=None):
    parts = [kind, prompt.strip()]
    if options:
        parts.extend(options)
    return "||".join(parts)


class EngineIOAdapter:
    """Feeds stored web answers back into the console expert engine."""

    def __init__(self, answers):
        self.answers = answers

    def _get_or_raise(self, question):
        key = question["key"]
        if key in self.answers:
            return self.answers[key]
        raise NeedInput(question)

    def text(self, prompt):
        prompt_clean = prompt.strip()

        if prompt_clean == "What's your name? :":
            question = {"key": "name", "type": "text", "prompt": prompt_clean, "question": "What's your name?"}
        elif prompt_clean == "what's your gender?(m/f) :":
            question = {
                "key": "gender",
                "type": "select",
                "prompt": prompt_clean,
                "question": "What's your gender?",
                "options": ["Male", "Female"],
            }
        elif prompt_clean == "Please list your drug allergies:":
            question = {"key": "allergy_details", "type": "text", "prompt": prompt_clean, "question": prompt_clean}
        elif prompt_clean == "Please list your current medications:":
            question = {"key": "medication_details", "type": "text", "prompt": prompt_clean, "question": prompt_clean}
        else:
            question = {
                "key": _prompt_id("text", prompt_clean),
                "type": "text",
                "prompt": prompt_clean,
                "question": prompt_clean,
            }

        value = self._get_or_raise(question)
        if question["key"] == "gender":
            return "m" if str(value).lower().startswith("m") else "f"
        return value

    def yes_no(self, prompt, key=None):
        prompt_clean = prompt.strip()
        question = {
            "key": key or _prompt_id("yesno", prompt_clean),
            "type": "yesno",
            "prompt": prompt_clean,
            "question": prompt_clean,
        }
        value = self._get_or_raise(question)
        return str(value).lower()

    def multi_input(self, prompt, options, key=None):
        prompt_clean = prompt.strip()
        question = {
            "key": key or _prompt_id("multi", prompt_clean, options),
            "type": "multi",
            "prompt": prompt_clean,
            "question": prompt_clean,
            "options": options + ["none"],
        }
        value = self._get_or_raise(question)
        if isinstance(value, list):
            selected = value
        else:
            selected = [value]
        return selected

    def diagnose(self, disease, symptoms):
        raise DiagnosisComplete(disease, symptoms)


@contextmanager
def engine_io_context(adapter):
    global _ACTIVE_IO
    previous_io = _ACTIVE_IO
    previous_input = builtins.input
    _ACTIVE_IO = adapter
    builtins.input = adapter.text
    try:
        yield
    finally:
        _ACTIVE_IO = previous_io
        builtins.input = previous_input

### Helper functions ###

def multi_input(input_str, options=[], key=None):
    """`key` identifies the question in web mode so it is stored and asked once."""
    if _ACTIVE_IO is not None:
        return _ACTIVE_IO.multi_input(input_str, options, key)

    print(input_str)

    while True:
        try:
            all_options = options + ["none"]

            print("0) none")
            for i, option in enumerate(options):
                print(f"{i+1}) {option}")

            choice = input("Your choice: ").split()

            indexes = [int(x)-1 for x in choice]

            for x in indexes:
                if x >= len(all_options):
                    raise ValueError

                if x == -1 and len(indexes) > 1:
                    raise ValueError

            return [all_options[i] for i in indexes]

        except:
            print("Invalid input. Try again.")

def yes_no(input_str, key=None):
    """`key` identifies the question in web mode so it is stored and asked once."""
    if _ACTIVE_IO is not None:
        return _ACTIVE_IO.yes_no(input_str, key)

    input_str += " (yes/no): "

    while True:
        try:
            user_input = input(input_str).strip().lower()

            if user_input in ["y", "yes", "yup"]:
                return "yes"

            elif user_input in ["n", "no", "nope"]:
                return "no"

            else:
                print("Please answer only yes or no.")

        except KeyboardInterrupt:
            print("\nPlease do not press Ctrl+C. Type yes or no.")

        except EOFError:
            print("\nInput error. Please try again.")

def suggest_disease(disease, symptoms):
    if _ACTIVE_IO is not None:
        _ACTIVE_IO.diagnose(disease, symptoms)

    print(f"\nYou might be suffering from {disease}")

    symptoms_text = '- ' + '\n - '.join(symptoms)

    print(f"This conclusion is reached because you show symptoms among the following:\n{symptoms_text}")

    open_doc = yes_no(f"\nDo you want to know more regarding {disease}?")

    if open_doc == "yes":
        html_file = os.path.join(os.getcwd(), "Treatment", "html", f"{disease}.html")

        if os.path.exists(html_file):
            webbrowser.open(f"file:///{html_file}", new=2)
        else:
            print(f"HTML file for {disease} not found.")

    raise SystemExit


def _selected(value):
    """Multi-select answers arrive as a list; "none" means nothing was picked."""
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [v for v in value if v != "none"]


def diagnose_from_answers(answers):
    """Pure diagnosis helper shared by the web app and console expert system."""
    a = answers
    fevers = _selected(a.get("fever_type"))
    no_fever = "fever_type" in a and not fevers
    normal_fever = "Normal Fever" in fevers
    low_fever = "Low Fever" in fevers
    high_fever = "High Fever" in fevers

    vomits = _selected(a.get("vomit_type"))
    severe_vomiting = "Severe Vomiting" in vomits
    normal_vomiting = "Normal Vomiting" in vomits

    def yes_count(*keys):
        return sum(1 for key in keys if a.get(key) == "yes")

    if a.get("red_eyes") == "yes":
        if a.get("eye_crusting") == "yes" or a.get("eye_burn") == "yes":
            return "Conjunctivitis", ["Red eyes", "Burning/crusting in eyes", "Eye discomfort"]
        if a.get("eye_irritation") == "yes":
            return "Eye Allergy", ["Red eyes", "Eye irritation", "Allergic reaction"]
        if (
            a.get("eye_burn") == "no"
            and a.get("eye_crusting") == "no"
            and a.get("eye_irritation") == "no"
            and yes_count("gritty", "screen_strain", "eye_watering", "blink_clears", "light_wind") >= 3
        ):
            return "Dry Eye Syndrome", [
                "Red eyes", "Gritty sandy feeling", "Dry tired eyes after screen use",
                "Excessive watering", "Blurred vision that clears on blinking",
                "Sensitivity to light and wind"
            ]

    if (
        a.get("diabetes") == "yes"
        and a.get("fatigue") == "yes"
        and a.get("extreme_thirst") == "yes"
        and a.get("extreme_hunger") == "yes"
        and yes_count(
            "frequent_urination", "weight_loss", "irritability",
            "blurred_vision", "frequent_infections", "slow_healing_sores"
        ) >= 3
    ):
        return "Diabetes", [
            "Fatigue", "Extreme thirst", "Extreme hunger", "Weight loss",
            "Blurred vision", "Frequent infections", "Frequent urination",
            "Irritability", "Slow healing of sores"
        ]

    if (
        a.get("hypertension") == "yes"
        and a.get("short_breath") == "yes"
        and a.get("chest_pain") == "yes"
        and yes_count("heaviness", "sweating", "dizziness", "burning_heart") >= 2
    ):
        return "Coronary Arteriosclerosis", [
            "Shortness of breath", "Chest pain", "Heaviness",
            "Sweating", "Dizziness", "Burning sensation near heart"
        ]

    if (
        a.get("heart_disease") == "yes"
        and a.get("fatigue") == "yes"
        and a.get("short_breath") == "yes"
        and yes_count(
            "irregular_heartbeat", "weakness", "pale_skin",
            "lightheadedness", "cold_limbs"
        ) >= 3
    ):
        return "Anemia", [
            "Shortness of breath", "Fatigue", "Irregular heartbeat",
            "Weakness", "Pale skin", "Dizziness", "Cold limbs"
        ]

    if (
        a.get("thyroid") == "yes"
        and a.get("fatigue") == "yes"
        and yes_count(
            "depression", "constipation", "feeling_cold", "dry_skin",
            "dry_hair", "weight_gain", "decreased_sweating",
            "slow_heart_rate", "joint_stiffness", "hoarseness"
        ) >= 5
    ):
        return "Hypothyroidism", [
            "Fatigue", "Depression", "Constipation", "Cold feeling",
            "Dry skin", "Dry hair", "Weight gain", "Decreased sweating",
            "Slow heart rate", "Joint pains", "Hoarseness in voice"
        ]

    if high_fever and yes_count(
        "severe_headache", "eyes_pain", "muscle_pain",
        "severe_joint_pain", "nausea", "rashes", "bleeding"
    ) >= 5:
        return "Dengue", [
            "High fever", "Headache", "Eye pain", "Muscle pain",
            "Joint pains", "Nausea", "Rashes", "Bleeding"
        ]

    if high_fever and yes_count(
        "step_fever", "abdominal_pain", "bowel_change", "rose_spots",
        "severe_weakness", "unsafe_food", "swollen_belly"
    ) >= 5:
        return "Typhoid", [
            "High fever rising day by day", "Continuous abdominal pain",
            "Constipation or diarrhoea", "Rose coloured spots",
            "Extreme weakness", "Unsafe food or water", "Tender swollen abdomen"
        ]

    if high_fever and yes_count(
        "swollen_joints", "sudden_joint_onset", "morning_stiffness",
        "chik_rash", "lasting_tiredness", "muscle_headache"
    ) >= 4:
        return "Chikungunya", [
            "High fever", "Swollen and painful joints",
            "Sudden onset of joint pain", "Morning joint stiffness",
            "Skin rash", "Lasting tiredness", "Headache with muscle pain"
        ]

    if low_fever and yes_count(
        "headache", "persistent_cough", "wheezing", "chills",
        "chest_tightness", "sore_throat", "body_aches",
        "breathlessness", "blocked_nose"
    ) >= 7:
        return "Bronchitis", [
            "Slight fever", "Cough", "Wheezing", "Chills",
            "Tightness in chest", "Sore throat", "Body aches",
            "Headache", "Breathlessness", "Blocked nose"
        ]

    if low_fever and yes_count(
        "facial_pain", "worse_bending", "thick_mucus", "reduced_smell",
        "tooth_pain", "bad_breath", "morning_headache"
    ) >= 4:
        return "Sinusitis", [
            "Slight fever", "Facial pain and pressure",
            "Pain worse on bending forward", "Thick nasal discharge",
            "Reduced sense of smell", "Upper tooth pain",
            "Bad breath", "Morning headache"
        ]

    if low_fever and yes_count(
        "sneezing", "runny_nose", "mild_sore_throat",
        "watery_eyes", "gradual_mild"
    ) >= 3:
        return "Common Cold", [
            "Slight fever", "Frequent sneezing", "Runny nose with clear mucus",
            "Mild sore throat", "Watery eyes", "Mild symptoms with slow onset"
        ]

    if a.get("appetite_loss") == "yes" and no_fever and a.get("short_breath") != "yes" and a.get("fatigue") != "yes":
        if a.get("joint_pain") == "yes" and yes_count(
            "stiff_joint", "swell_joint", "red_skin_joint",
            "decreased_range", "tired_small_walk"
        ) >= 3:
            return "Arthritis", [
                "Stiff joints", "Swelling in joints", "Joint pains",
                "Red skin around joints", "Tiredness",
                "Reduced movement near joints", "Appetite loss"
            ]

        if severe_vomiting and yes_count(
            "burning_stomach", "bloating", "mild_nausea",
            "weight_loss", "abdominal_pain"
        ) >= 3:
            return "Peptic Ulcer", [
                "Appetite loss", "Severe vomiting",
                "Burning sensation in stomach", "Bloated stomach",
                "Nausea", "Weight loss", "Abdominal pain"
            ]

        if normal_vomiting and yes_count(
            "nausea", "fullness", "bloating",
            "abdominal_pain", "indigestion", "gnawing"
        ) >= 4:
            return "Gastritis", [
                "Appetite loss", "Vomiting", "Nausea",
                "Fullness near abdomen", "Bloating near abdomen",
                "Abdominal pain", "Indigestion", "Gnawing pain near abdomen"
            ]

    if a.get("fatigue") == "yes" and no_fever and a.get("short_breath") != "yes":
        if a.get("extreme_thirst") == "yes" and a.get("extreme_hunger") == "yes" and yes_count(
            "frequent_urination", "weight_loss", "irritability",
            "blurred_vision", "frequent_infections", "slow_healing_sores"
        ) >= 4:
            return "Diabetes", [
                "Fatigue", "Extreme thirst", "Extreme hunger", "Weight loss",
                "Blurred vision", "Frequent infections", "Frequent urination",
                "Irritability", "Slow healing of sores"
            ]

        if a.get("extreme_thirst") == "yes" and a.get("dizziness") == "yes" and yes_count(
            "less_frequent_urination", "dark_urine", "lethargy", "dry_mouth"
        ) >= 2:
            return "Dehydration", [
                "Fatigue", "Extreme thirst", "Dizziness", "Dark urine",
                "Lethargic feeling", "Dry mouth", "Less frequent urination"
            ]

        if a.get("muscle_weakness") == "yes" and yes_count(
            "depression", "constipation", "feeling_cold", "dry_skin",
            "dry_hair", "weight_gain", "decreased_sweating",
            "slow_heart_rate", "joint_stiffness", "hoarseness"
        ) >= 7:
            return "Hypothyroidism", [
                "Fatigue", "Muscle weakness", "Depression", "Constipation",
                "Cold feeling", "Dry skin", "Dry hair", "Weight gain",
                "Decreased sweating", "Slow heart rate", "Joint pains",
                "Hoarseness in voice"
            ]

        if a.get("muscle_weakness") == "yes" and yes_count(
            "unintentional_weight_loss", "fast_heartbeat", "heat_intolerance",
            "excess_sweating", "tremor", "anxiety", "hyper_sleep_trouble",
            "frequent_bowel"
        ) >= 5:
            return "Hyperthyroidism", [
                "Fatigue", "Muscle weakness", "Unintentional weight loss",
                "Rapid heartbeat", "Heat intolerance", "Excessive sweating",
                "Hand tremors", "Anxiety and irritability", "Trouble sleeping",
                "Frequent bowel movements"
            ]

    if a.get("short_breath") == "yes" and no_fever:
        if a.get("back_joint_pain") == "yes" and yes_count(
            "sweating", "snoring", "sudden_physical",
            "tired_small_walk", "isolated", "low_confidence"
        ) >= 4:
            return "Obesity", [
                "Shortness of breath", "Back and joint pains",
                "High sweating", "Snoring habit", "Tiredness",
                "Low confidence"
            ]

        if (
            a.get("chest_pain") == "yes"
            and a.get("fatigue") == "yes"
            and a.get("headache") == "yes"
            and yes_count(
                "irregular_heartbeat", "weakness", "pale_skin",
                "lightheadedness", "cold_limbs"
            ) >= 3
        ):
            return "Anemia", [
                "Shortness of breath", "Chest pain", "Fatigue",
                "Headache", "Irregular heartbeat", "Weakness",
                "Pale skin", "Dizziness", "Cold limbs"
            ]

        if (
            a.get("chest_pain") == "yes"
            and a.get("fatigue") == "yes"
            and a.get("pain_arms") == "yes"
            and yes_count("heaviness", "sweating", "dizziness", "burning_heart") >= 2
        ):
            return "Coronary Arteriosclerosis", [
                "Shortness of breath", "Chest pain", "Fatigue",
                "Arm pains", "Heaviness", "Sweating",
                "Dizziness", "Burning sensation near heart"
            ]

        if (
            a.get("chest_pain") == "yes"
            and a.get("cough") == "yes"
            and yes_count("wheezing", "sleep_trouble") >= 1
        ):
            return "Asthma", [
                "Shortness of breath", "Chest pain", "Cough",
                "Wheezing sound when exhaling",
                "Trouble sleeping because of coughing or wheezing"
            ]

        if a.get("cough") == "yes" and yes_count(
            "long_term_cough", "breathless_activity", "chest_wheeze",
            "smoking", "frequent_chest_infections", "chest_tightness", "bluish"
        ) >= 4:
            return "COPD", [
                "Shortness of breath", "Long lasting cough with mucus",
                "Breathlessness on daily activity", "Wheezing in chest",
                "Smoking history", "Frequent chest infections",
                "Tightness in chest"
            ]

    if normal_fever:
        if (
            a.get("nf_chest_pain") == "yes"
            and a.get("fatigue") == "yes"
            and a.get("chills") == "yes"
            and yes_count("tb_persistent_cough", "weight_loss", "night_sweats", "cough_blood") >= 2
        ):
            return "Tuberculosis", [
                "Fever", "Chest pain", "Fatigue", "Loss of appetite", "Persistent cough"
            ]

        if (
            a.get("fatigue") == "yes"
            and a.get("sore_throat") == "yes"
            and yes_count(
                "weakness", "dry_cough", "muscle_ache",
                "chills", "nasal_congestion", "headache"
            ) >= 4
        ):
            return "Influenza", [
                "Fever", "Fatigue", "Sore throat", "Weakness",
                "Dry cough", "Muscle aches", "Chills",
                "Nasal congestion", "Headache"
            ]

        if (
            a.get("fatigue") == "yes"
            and a.get("abdominal_pain") == "yes"
            and yes_count("flu_like", "dark_urine", "pale_stool", "weight_loss", "jaundice") >= 3
        ):
            return "Hepatitis", [
                "Fever", "Fatigue", "Abdominal pain", "Flu-like symptoms",
                "Dark urine", "Pale stool", "Weight loss",
                "Yellow eyes and skin (jaundice)"
            ]

        if (
            a.get("nf_chest_pain") == "yes"
            and a.get("short_breath") == "yes"
            and a.get("nausea") == "yes"
            and yes_count("rest_breathless", "high_sweat", "rapid_breath", "cough_phlegm", "diarrhea") >= 3
        ):
            return "Pneumonia", [
                "Fever", "Chest pain", "Shortness of breath", "Nausea",
                "Sweating with chills", "Rapid breathing",
                "Cough with phlegm", "Diarrhea"
            ]

        if (
            a.get("chills") == "yes"
            and a.get("abdominal_pain") == "yes"
            and a.get("nausea") == "yes"
            and yes_count("headache", "sweat", "cough", "weakness", "muscle_ache", "back_pain") >= 4
        ):
            return "Malaria", [
                "Fever", "Chills", "Abdominal pain", "Nausea",
                "Headache", "Sweating", "Cough", "Weakness",
                "Muscle pain", "Back pain"
            ]

        if a.get("rashes") == "yes" and yes_count(
            "headache", "muscle_ache", "sore_throat", "lymph",
            "diarrhea", "cough", "weight_loss", "night_sweats"
        ) >= 6:
            return "AIDS", [
                "Fever", "Rashes", "Headache", "Muscle ache",
                "Sore throat", "Swollen lymph nodes", "Diarrhea",
                "Cough", "Weight loss", "Night sweat"
            ]

        if a.get("nausea") == "yes" and yes_count(
            "upper_abdominal_pain", "pain_after_eating",
            "heartbeat_fast", "weight_loss", "oily_stool"
        ) >= 3:
            return "Pancreatitis", [
                "Nausea", "Fever", "Upper abdominal pain",
                "Heartbeat", "Weight loss", "Oily and smelly stool"
            ]

        if (
            a.get("fatigue") == "yes"
            and a.get("short_breath") == "yes"
            and a.get("nausea") == "yes"
            and yes_count("chills", "cough", "body_aches", "headache", "sore_throat", "lose_smell", "diarrhea") >= 4
        ):
            return "Corona Virus", [
                "Fever", "Fatigue", "Shortness of breath", "Nausea",
                "Chills", "Cough", "Body aches", "Headache",
                "Sore throat", "Diarrhea", "Loss of taste/smell"
            ]

        if a.get("abdominal_pain") == "yes" and yes_count(
            "burning_urination", "frequent_urge", "cloudy_urine",
            "flank_pain", "blood_urine", "constant_urge"
        ) >= 4:
            return "Urinary Tract Infection", [
                "Fever", "Lower abdominal pain", "Burning sensation while urinating",
                "Frequent urination", "Cloudy or strong smelling urine",
                "Lower back or flank pain", "Blood in urine",
                "Constant urge to urinate"
            ]

        if a.get("nausea") == "yes" and yes_count(
            "watery_diarrhea", "cramps", "repeated_vomiting",
            "after_outside_food", "fluid_loss", "gastro_muscle_ache"
        ) >= 4:
            return "Gastroenteritis", [
                "Fever", "Nausea", "Watery diarrhoea", "Stomach cramps",
                "Repeated vomiting", "Recent outside food",
                "Weakness and dry mouth", "Mild muscle aches"
            ]

    return None, []


class DiagnosisFlow:
    """Web wrapper that replays the exact terminal engine to fetch the next question."""

    def __init__(self):
        self.answers = {}
        self.result = None
        self.current_question = None
        self.done = False
        self.history = []
        self.prediction_prompted = None

    def get_current_question(self):
        if self.done:
            return None

        if self.current_question is not None:
            return self.current_question

        if not EXPERTA_AVAILABLE:
            self.done = True
            self.result = {
                "disease": None,
                "symptoms": [],
                "error": "experta is required to run the exact terminal engine."
            }
            return None

        adapter = EngineIOAdapter(self.answers)
        engine = MedicalExpert()

        try:
            with engine_io_context(adapter), redirect_stdout(io.StringIO()):
                engine.reset()
                engine.run()
        except NeedInput as need:
            question = need.question
            if question["key"] == "gender":
                question = dict(question)
                question["type"] = "select"
                question["options"] = ["Male", "Female"]
            if not self.history or self.history[-1]["key"] != question["key"]:
                self.history.append(dict(question))
            self.current_question = question
            return question
        except DiagnosisComplete as result:
            self.result = {"disease": result.disease, "symptoms": result.symptoms}
            self.done = True
            return None

        self.result = {"disease": None, "symptoms": []}
        self.done = True
        return None

    def submit_answer(self, key, answer):
        self.answers[key] = answer
        self.current_question = None
        self.result = None
        self.done = False

    def run_diagnosis(self):
        if self.result:
            return self.result.get("disease"), self.result.get("symptoms", [])

        adapter = EngineIOAdapter(self.answers)
        engine = MedicalExpert()

        try:
            with engine_io_context(adapter), redirect_stdout(io.StringIO()):
                engine.reset()
                engine.run()
        except DiagnosisComplete as result:
            self.result = {"disease": result.disease, "symptoms": result.symptoms}
            return result.disease, result.symptoms
        except NeedInput:
            return None, []

        self.result = {"disease": None, "symptoms": []}
        return None, []

    def start_edit(self, key):
        if key not in self.answers:
            return

        keep_keys = []
        trimmed_history = []

        for question in self.history:
            trimmed_history.append(question)
            keep_keys.append(question["key"])
            if question["key"] == key:
                break

        self.history = trimmed_history
        self.answers = {k: self.answers[k] for k in keep_keys if k in self.answers}
        self.current_question = None
        self.result = None
        self.done = False
        self.prediction_prompted = None

    def revise_answer(self, key, answer):
        self.start_edit(key)
        self.answers[key] = answer
        self.current_question = None
        self.result = None
        self.done = False


# ============================================================
# HTML TEMPLATES
# ============================================================

if EXPERTA_AVAILABLE:
    class MedicalExpert(KnowledgeEngine):
    
        @DefFacts()
        def _initial_action_(self):
            print("Hi. I am an Expert System who can help you in medical diagnosis.")
            print("When prompted with options, enter space seperated integer values corresponding to all the options which apply to you.")
            print("Please answer the following questions to find out the disease and its cure")
            # yeild all the facts you require here
            yield Fact(action="engine_start")
            
        @Rule(Fact(action="engine_start"))
        def getUserInfo(self):
            self.declare(Fact(name=input("What's your name? : ")))
            self.declare(Fact(gender=input("what's your gender?(m/f) : ")))
            self.declare(Fact(action="medical_history"))
    
        @Rule(Fact(action="medical_history"))
        def askMedicalHistory(self):
            print("\n" + "="*60)
            print("Now let me ask about your medical history.")
            print("This information helps me provide better diagnosis.")
            print("="*60)
    
            diabetes = yes_no("Do you have Diabetes?", key="diabetes")
            if diabetes == "yes":
                self.declare(Fact(diabetes="yes"))
                diabetes_type = multi_input("What type of diabetes?", ["Type 1", "Type 2", "Gestational", "Don't know"], key="diabetes_type")
                if diabetes_type[0] != "none":
                    diabetes_type_clean = diabetes_type[0].replace(" ", "_").replace(",", "")
                    self.declare(Fact(diabetes_type=diabetes_type_clean))
            else:
                self.declare(Fact(diabetes="no"))
    
            blood_pressure = yes_no("Do you have High Blood Pressure (Hypertension)?", key="hypertension")
            if blood_pressure == "yes":
                self.declare(Fact(hypertension="yes"))
                bp_managed = yes_no("Is it managed with medication?", key="hypertension_managed")
                self.declare(Fact(hypertension_managed=bp_managed))
            else:
                self.declare(Fact(hypertension="no"))
    
            heart_disease = yes_no("Do you have any Heart Disease?", key="heart_disease")
            if heart_disease == "yes":
                self.declare(Fact(heart_disease="yes"))
                heart_condition = multi_input("What type of heart condition?", ["Coronary Artery Disease", "Heart Failure", "Arrhythmia", "Heart Valve Problem", "Other"], key="heart_condition_type")
                if heart_condition[0] != "none":
                    heart_condition_clean = heart_condition[0].replace(" ", "_").replace(",", "")
                    self.declare(Fact(heart_condition_type=heart_condition_clean))
            else:
                self.declare(Fact(heart_disease="no"))
    
            asthma_history = yes_no("Do you have Asthma?", key="asthma_history")
            self.declare(Fact(asthma=asthma_history))
    
            kidney_disease = yes_no("Do you have Kidney Disease?", key="kidney_disease")
            self.declare(Fact(kidney_disease=kidney_disease))
    
            liver_disease = yes_no("Do you have Liver Disease?", key="liver_disease")
            self.declare(Fact(liver_disease=liver_disease))
    
            thyroid = yes_no("Do you have Thyroid Disorder?", key="thyroid")
            if thyroid == "yes":
                self.declare(Fact(thyroid_disorder="yes"))
                thyroid_type = multi_input("What type?", ["Hyperthyroidism", "Hypothyroidism", "Don't know"], key="thyroid_type")
                if thyroid_type[0] != "none":
                    thyroid_type_clean = thyroid_type[0].replace(" ", "_").replace(",", "")
                    self.declare(Fact(thyroid_type=thyroid_type_clean))
            else:
                self.declare(Fact(thyroid_disorder="no"))
    
            cancer_history = yes_no("Do you have or had Cancer?", key="cancer_history")
            if cancer_history == "yes":
                self.declare(Fact(cancer_history="yes"))
                cancer_type = multi_input("What type (if known)?", ["Blood", "Lung", "Breast", "Colon", "Prostate", "Other", "Don't know"], key="cancer_type")
                if cancer_type[0] != "none":
                    cancer_type_clean = cancer_type[0].replace(" ", "_").replace(",", "")
                    self.declare(Fact(cancer_type=cancer_type_clean))
            else:
                self.declare(Fact(cancer_history="no"))
    
            # Allergies
            allergies = yes_no("Do you have any known drug allergies?", key="drug_allergies")
            if allergies == "yes":
                self.declare(Fact(drug_allergies="yes"))
                allergy_details = input("Please list your drug allergies: ")
                if allergy_details.strip():
                    self.declare(Fact(allergy_details=allergy_details))
            else:
                self.declare(Fact(drug_allergies="no"))
    
            # Current medications
            meds = yes_no("Are you currently taking any medications?", key="current_medications")
            if meds == "yes":
                self.declare(Fact(current_medications="yes"))
                med_details = input("Please list your current medications: ")
                if med_details.strip():
                    self.declare(Fact(medication_details=med_details))
            else:
                self.declare(Fact(current_medications="no"))
    
            self.declare(Fact(action="questionnaire"))
        
        @Rule(Fact(action="questionnaire"))
        def askBasicQuestions(self):
            self.declare(Fact(red_eyes=yes_no("Do you suffer from red eyes?", key="red_eyes")))
            self.declare(Fact(fatigue=yes_no("Are you suffering from fatigue?", key="fatigue")))
            self.declare(Fact(short_breath=yes_no("Are you having shortness of breath?", key="short_breath")))
            self.declare(Fact(appetite_loss=yes_no("Are you having loss of appetite?", key="appetite_loss")))
            fevers = multi_input("Do you suffer from fever?", ["Normal Fever","Low Fever","High Fever"], key="fever_type")
            if fevers[0]!="none":
                self.declare(Fact(fever="yes"))
                for f in fevers:
                    f=f.replace(" ","_")
                    self.declare(Fact(f)) 
            else:
                self.declare(Fact(fever="no"))
    
        @Rule(AND(Fact(appetite_loss="yes"), Fact(fever="no"), Fact(short_breath="no"), Fact(fatigue="no")))
        def askRelatedToAppetiteLoss(self):
            self.declare(Fact(joint_pain=yes_no("Are you having any joint pains?", key="joint_pain")))
            vomits = multi_input("Did you have vomitings?", ["Severe Vomiting", "Normal Vomiting"], key="vomit_type")
            if vomits[0]!="none":
                self.declare(Fact(vomit="yes"))
                for v in vomits:
                    v=v.replace(" ","_")
                    self.declare(Fact(v))
            else:
                self.declare(Fact(vomit="no"))
    
        @Rule(AND(Fact(appetite_loss="yes"), Fact(fever="no"), Fact(short_breath="no"), Fact(fatigue="no"), Fact(joint_pain="yes")))
        def askArthritis(self):
            stiff_joint=yes_no("Are you having stiff Joints?", key="stiff_joint")
            swell_joint=yes_no("Are you experiencing swelly Joints?", key="swell_joint")
            red_skin_around_joint=yes_no("Did the skin turn red around the Joints?", key="red_skin_joint")
            decreased_range=yes_no("Did the range of motion decrease at the Joints?", key="decreased_range")
            tired=yes_no("Are you feeling tired even if you walk small distance?", key="tired_small_walk")
            count=0
            for string in [stiff_joint, swell_joint, red_skin_around_joint, decreased_range, tired]:
                if string=="yes":
                    count+=1
    
            if count>=3:
                symptoms = ["Stiff joints", "Swelling in joints", "Joint Pains", "Red shik around joints", "Tiredness", "Reduced Movement near joints", "Appetite loss"]
                suggest_disease("Arthritis", symptoms)
    
        @Rule(AND(Fact(appetite_loss="yes"), Fact(fever="no"), Fact(short_breath="no"), Fact(fatigue="no"), Fact("Severe_Vomiting")))
        def askPepticUlcer(self):
            burning_stomach=yes_no("Is your stomach has burning sensation?", key="burning_stomach")
            bloating=yes_no("Are you having a feeling of fullness, bloating or belching?", key="bloating")
            mild_nausea=yes_no("Are you having mild Nausea?", key="mild_nausea")
            weight_loss=yes_no("Did you lose your weight?", key="weight_loss")
            abdominal_pain=yes_no("Are you having an intense and localized abdominal pain?", key="abdominal_pain")
            count=0
            for string in [burning_stomach, bloating, mild_nausea, weight_loss, abdominal_pain]:
                if string=="yes":
                    count+=1
    
            if count>=3:
                symptoms = ["Appetite loss", "Severe Vomiting", "Burning sensation in stomach", "Bloated stomach", "Nausea", "Weight loss", "Abdominal pain"]
                suggest_disease("Peptic Ulcer", symptoms)
    
        @Rule(AND(Fact(appetite_loss="yes"), Fact(fever="no"), Fact(short_breath="no"), Fact(fatigue="no"), Fact("Normal_Vomiting")))
        def askGastritis(self):
            nausea=yes_no("Are you having a feeling of vomiting(Nausea)?", key="nausea")
            fullness=yes_no("Are you having a feeling of fullness in your upper abdomen?", key="fullness")
            bloating=yes_no("Are you feeling bloating in your abdomen?", key="bloating")
            abdominal_pain=yes_no("Are you having pain near abdomen?", key="abdominal_pain")
            indigestion=yes_no("Are you facing problems of indigestion?", key="indigestion")
            gnawing=yes_no("Are you experiencing gnawing or burning ache or pain in your upper abdomen that may become either worse or better with eating", key="gnawing")
            count=0
            for string in [nausea, fullness, bloating, abdominal_pain, indigestion, gnawing]:
                if string=="yes":
                    count+=1
    
            if count>=4:
                symptoms = ["Appetite loss", "Vomiting", "Nausea", "Fullness near abdomen", "Bloating near abdomen", "Abdominal pain", "Indigestion", "Gnawing pain near abdomen"]
                suggest_disease("Gastritis", symptoms)
    
    
        @Rule(AND(Fact(fatigue="yes"), Fact(fever="no"), Fact(short_breath="no")))
        def askRelatedToFatigue(self):
            self.declare(Fact(extreme_thirst=yes_no("Are you feeling extremely thirsty than before?", key="extreme_thirst")))
            self.declare(Fact(extreme_hunger=yes_no("Are you feeling extremely hungry than before?", key="extreme_hunger")))
            self.declare(Fact(dizziness=yes_no("Are you feeling dizzy?", key="dizziness")))
            self.declare(Fact(muscle_weakness=yes_no("Are your muscles weaker than berfore?", key="muscle_weakness")))
    
        @Rule(AND(Fact(fatigue="yes"), Fact(fever="no"), Fact(short_breath="no"), Fact(extreme_thirst="yes"), Fact(extreme_hunger="yes")))
        def askDiabetes(self):
            frequent_urination=yes_no("Is your Urination more frequent than before?", key="frequent_urination")
            weight_loss=yes_no("Did you lose your weight unintentionally?", key="weight_loss")
            irratabiliry=yes_no("Are you more irritable now a days?", key="irritability")
            blurred_vision=yes_no("Did your vision get blurred?", key="blurred_vision")
            frequent_infections=yes_no("Are you having frequent infections such as gums or skin infections", key="frequent_infections")
            sores=yes_no("Are your sores healing slowly?", key="slow_healing_sores")
            count=0
            for string in [frequent_urination, weight_loss, irratabiliry, blurred_vision, frequent_infections, sores]:
                if string=="yes":
                    count+=1
    
            if count>=4:
                symptoms = ["Fatigue", "Extreme thirst", "Extreme hunger", "Weight loss", "Blurred vision", "Frequent infections", "Frequent urination", "Irritability", "Slow healing of sores"]
                suggest_disease("Diabetes", symptoms)
    
        @Rule(AND(Fact(fatigue="yes"), Fact(fever="no"), Fact(short_breath="no"), Fact(extreme_thirst="yes"), Fact(dizziness="yes")))
        def askDehydration(self):
            less_frequent_urination=yes_no("Are you having less frequent urination?", key="less_frequent_urination")
            dark_urine=yes_no("Did the urine become dark?", key="dark_urine")
            lethargy=yes_no("Are you feeling lethargic?", key="lethargy")
            dry_mouth=yes_no("Is your mouth considerably dry?", key="dry_mouth")
            count=0
            for string in [less_frequent_urination, dark_urine, lethargy, dry_mouth]:
                if string=="yes":
                    count+=1
    
            if count>=2:
                symptoms = ["Fatigue", "Extreme thirst", "Dizziness", "Dark urine", "Lethargic feeling", "Dry mouth", "Less frequent urination"]
                suggest_disease("Dehydration", symptoms)
    
        @Rule(AND(Fact(fatigue="yes"), Fact(fever="no"), Fact(short_breath="no"), Fact(muscle_weakness="yes")))
        def askHypothoroidism(self):
            depression=yes_no("Are you feeling depressed now a days?", key="depression")
            constipation=yes_no("Are you experiencing constipation?", key="constipation")
            feeling_cold=yes_no("Are you feeling cold?", key="feeling_cold")
            dry_skin=yes_no("Has your skin became drier?", key="dry_skin")
            dry_hair=yes_no("Is your hair too becoming dry and also thinner?", key="dry_hair")
            weight_gain=yes_no("Did you gain your weight considerably?", key="weight_gain")
            decreased_sweating=yes_no("Are you not sweating much as earlier?", key="decreased_sweating")
            slowed_heartrate=yes_no("Did your heart rate slow down?", key="slow_heart_rate")
            pain_joints=yes_no("Are you experiencing pain and stiffness in joints?", key="joint_stiffness")
            hoarseness=yes_no("Is your voice changing abnormally?", key="hoarseness")
            count=0
            for string in [depression, constipation, feeling_cold, dry_skin, dry_hair, weight_gain, decreased_sweating, slowed_heartrate, pain_joints, hoarseness]:
                if string=="yes":
                    count+=1
    
            if count>=7:
                symptoms = ["Fatigue", "Muscle weakness", "Depression", "Constipation", "Cold feeling", "Dry skin", "Dry hair", "Weight gain", "Decreased sweating", "Slow heart rate", "Joint pains", "Hoarseness in voice"]
                suggest_disease("Hypothyroidism", symptoms)

        @Rule(AND(Fact(fatigue="yes"), Fact(fever="no"), Fact(short_breath="no"), Fact(muscle_weakness="yes")), salience=-10)
        def askHyperthyroidism(self):
            weight_loss=yes_no("Did you lose weight even though you are eating the same amount or more?", key="unintentional_weight_loss")
            fast_heartbeat=yes_no("Is your heartbeat fast, pounding or irregular?", key="fast_heartbeat")
            heat_intolerance=yes_no("Do you feel unusually hot or unable to tolerate warm weather?", key="heat_intolerance")
            excess_sweating=yes_no("Are you sweating much more than you used to?", key="excess_sweating")
            tremor=yes_no("Do your hands or fingers shake or tremble?", key="tremor")
            anxiety=yes_no("Are you feeling nervous, anxious or unusually irritable?", key="anxiety")
            sleep_trouble=yes_no("Are you having trouble falling asleep?", key="hyper_sleep_trouble")
            frequent_bowel=yes_no("Are your bowel movements more frequent than before?", key="frequent_bowel")
            count=0
            for string in [weight_loss, fast_heartbeat, heat_intolerance, excess_sweating, tremor, anxiety, sleep_trouble, frequent_bowel]:
                if string=="yes":
                    count+=1

            if count>=5:
                symptoms = ["Fatigue", "Muscle weakness", "Unintentional weight loss", "Rapid heartbeat", "Heat intolerance", "Excessive sweating", "Hand tremors", "Anxiety and irritability", "Trouble sleeping", "Frequent bowel movements"]
                suggest_disease("Hyperthyroidism", symptoms)

        @Rule(AND(Fact(short_breath="yes"), Fact(fever="no")))
        def askRelatedToShortBreath(self):
            self.declare(Fact(back_joint_pian=yes_no("Are you having back and joint pain?", key="back_joint_pain")))
            self.declare(Fact(chest_pain=yes_no("Are you having chest pain?", key="chest_pain")))
            self.declare(Fact(cough=yes_no("Are you having cough frequently?", key="cough")))
            self.declare(Fact(fatigue=yes_no("Are you feeling fatigue?", key="fatigue")))
            self.declare(Fact(headache=yes_no("Are you having headache?", key="headache")))
            self.declare(Fact(pain_arms=yes_no("Are you having pain in arms and shoulders?", key="pain_arms")))
    
        @Rule(AND(Fact(short_breath="yes"), Fact(fever="no"), Fact(back_joint_pian="yes")))
        def askObesity(self):
            sweating=yes_no("Are you sweating more than normal?", key="sweating")
            snoring=yes_no("Did you develop a habit of snoring?", key="snoring")
            sudden_physical=yes_no("Are you not able to cope up with sudden physical activity?", key="sudden_physical")
            tired=yes_no("Are you feeling tired every day withour doing much work?", key="tired_small_walk")
            isolatd=yes_no("Are you feeling isolated?", key="isolated")
            confidence=yes_no("Are you having low confidence and self esteem in day to day activities?", key="low_confidence")
            count=0
            for string in [sweating, snoring, sudden_physical, tired, isolatd, confidence]:
                if string=="yes":
                    count+=1
    
            if count>=4:
                symptoms = ["Shortness in breath", "Back and Joint pains", "High sweating", "Snoring habit", "Tireness", "Low confidence"]
                suggest_disease("Obesity", symptoms)
    
        @Rule(AND(Fact(short_breath="yes"), Fact(fever="no"), Fact(chest_pain="yes"), Fact(fatigue="yes"), Fact(headache="yes")))
        def askAnemia(self):
            irregular_heartbeat=yes_no("Are you experiencing irregular heartbeat?", key="irregular_heartbeat")
            weakness=yes_no("Are you feeling weak?", key="weakness")
            pale_skin=yes_no("Has your skin turned pale or yellowish?", key="pale_skin")
            lightheadedness=yes_no("Are you having dizziness or light headedness?", key="lightheadedness")
            cold_hands_feet=yes_no("Are you having cold hands and feet?", key="cold_limbs")
            count=0
            for string in [irregular_heartbeat, weakness, pale_skin, lightheadedness, cold_hands_feet]:
                if string=="yes":
                    count+=1
    
            if count>=3:
                symptoms = ["Shortness in breath", "Chest pain", "Fatigue", "Headache", "Irregular heartbeat", "Weakness", "Pale skin", "Dizziness", "Cold limbs"]
                suggest_disease("Anemia", symptoms)
    
        @Rule(AND(Fact(short_breath="yes"), Fact(fever="no"), Fact(chest_pain="yes"), Fact(fatigue="yes"), Fact(pain_arms="yes")))
        def askCAD(self):
            heaviness=yes_no("Did you have feeling of heaviness or tightness, usually in the centre of the chest, which may spread to the arms, neck, jaw, back or stomach?", key="heaviness")
            sweating=yes_no("Are you sweating frequently?", key="sweating")
            dizziness=yes_no("Are you feeling dizzy?", key="dizziness")
            burning=yes_no("Do you feel burning sensation near heart?", key="burning_heart")
            count=0
            for string in [heaviness, sweating, dizziness, burning]:
                if string=="yes":
                    count+=1
    
            if count>=2:
                symptoms = ["Shortness in breath", "Chest pain", "Fatigue", "Arm pains", "Heaviness", "Sweating", "Diziness", "Burning sensation near heart"]
                suggest_disease("Coronary Arteriosclerosis", symptoms)
    
        @Rule(AND(Fact(short_breath="yes"), Fact(fever="no"), Fact(chest_pain="yes"), Fact(cough="yes")))
        def askAsthma(self):
            Wheezing=yes_no("Are you having a whistling or wheezing sound when exhaling?", key="wheezing")
            sleep_trouble=yes_no("Are you having trouble sleeping caused by shortness of breath, coughing or wheezing?", key="sleep_trouble")
            count=0
            for string in [Wheezing, sleep_trouble]:
                if string=="yes":
                    count+=1
    
            if count>=1:
                symptoms = ["Shortness in breath", "Chest pain", "Cough", "Wheezing sound when exhaling", "Trouble sleep because of coughing or wheezing"]
                suggest_disease("Asthma", symptoms)

        @Rule(AND(Fact(short_breath="yes"), Fact(fever="no"), Fact(cough="yes")), salience=-10)
        def askCOPD(self):
            long_term_cough=yes_no("Have you had a cough that brings up mucus on most days for several months?", key="long_term_cough")
            breathless_activity=yes_no("Do you become breathless during everyday activities such as walking or climbing stairs?", key="breathless_activity")
            chest_wheeze=yes_no("Do you hear a whistling or wheezing sound in your chest?", key="chest_wheeze")
            smoking=yes_no("Do you smoke, or did you smoke regularly for many years?", key="smoking")
            frequent_infections=yes_no("Do you catch chest infections often, and do they take long to clear?", key="frequent_chest_infections")
            chest_tightness=yes_no("Are you feeling tightness in your chest?", key="chest_tightness")
            bluish=yes_no("Have your lips or fingernails ever looked bluish or grey?", key="bluish")
            count=0
            for string in [long_term_cough, breathless_activity, chest_wheeze, smoking, frequent_infections, chest_tightness, bluish]:
                if string=="yes":
                    count+=1

            if count>=4:
                symptoms = ["Shortness in breath", "Long lasting cough with mucus", "Breathlessness on daily activity", "Wheezing in chest", "Smoking history", "Frequent chest infections", "Tightness in chest"]
                suggest_disease("COPD", symptoms)
