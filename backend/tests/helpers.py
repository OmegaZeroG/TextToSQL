import json


class FakeLLM:
    """Scripted LLMProvider: returns queued responses in order (raising any
    Exception instances) and records every prompt it was sent."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, system_prompt, user_prompt, json_mode=False):
        self.calls.append({"system": system_prompt, "user": user_prompt, "json_mode": json_mode})
        if not self.responses:
            raise AssertionError("FakeLLM received more calls than were scripted")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def gen(sql="SELECT COUNT(*) AS n FROM orders", **overrides):
    payload = {
        "sql": sql,
        "explanation": "Counts orders.",
        "confidence": 5,
        "tables_used": ["orders"],
        "ambiguous": False,
    }
    payload.update(overrides)
    return json.dumps(payload)


BACK_TRANSLATION = json.dumps({"back_translated_question": "How many orders are there?"})


def alignment(score):
    return json.dumps({"alignment_score": score})
