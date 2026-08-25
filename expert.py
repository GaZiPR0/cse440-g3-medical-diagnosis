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
