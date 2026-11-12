"""LLM extractor: Claude with a forced tool call whose input schema is the Invoice model.

Forcing `tool_choice` makes the model return arguments that conform to the JSON
schema rather than prose, and pydantic re-validates them on our side.
"""
import os

from .schema import Invoice

MODEL = os.environ.get("INVX_MODEL", "claude-sonnet-5-5")
INSTRUCTIONS = (
    "Extract the invoice fields exactly as printed. Dates as YYYY-MM-DD. Amounts as plain decimals "
    "without symbols or thousands separators. Currency as an ISO 4217 code. Do not correct the vendor's "
    "arithmetic: if the printed total is wrong, return the printed total. Use null for absent fields."
)


def extract_llm(text: str, client=None) -> Invoice:
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    tool = {"name": "record_invoice", "description": "Record the extracted invoice.", "input_schema": Invoice.model_json_schema()}
    msg = client.messages.create(
        model=MODEL, max_tokens=2000, tools=[tool], tool_choice={"type": "tool", "name": "record_invoice"},
        messages=[{"role": "user", "content": f"{INSTRUCTIONS}\n\n<invoice>\n{text}\n</invoice>"}],
    )
    block = next(b for b in msg.content if getattr(b, "type", "") == "tool_use")
    return Invoice.model_validate(block.input)
