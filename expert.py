#!/usr/bin/env python
import os
import webbrowser
import builtins
from contextlib import contextmanager
import io
from contextlib import redirect_stdout
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

def multi_input(input_str, options=[]):
    if _ACTIVE_IO is not None:
        return _ACTIVE_IO.multi_input(input_str, options)

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

def yes_no(input_str):
    if _ACTIVE_IO is not None:
        return _ACTIVE_IO.yes_no(input_str)

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
