import os
import re
import logging
import requests
from typing import Tuple, Optional, List
from utils.config import CONFIG

logger = logging.getLogger(__name__)


HOST_RE = re.compile(r"\b([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b")
IP_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b")


def detect_network_indicators(text: str) -> Tuple[bool, int, int, List[str], List[str]]:
    """Return (found, host_count, ip_count, hosts, ips) for hostnames/IP addresses in text."""
    if not text:
        return (False, 0, 0, [], [])
    hosts = HOST_RE.findall(text)
    ips = IP_RE.findall(text)
    # HOST_RE returns only last label via grouping; re-find without groups for concrete strings
    host_strs = re.findall(HOST_RE.pattern, text)
    return (bool(hosts or ips), len(hosts), len(ips), host_strs, ips)


def strip_scope(text: str, scope: Optional[str]) -> str:
    """Remove occurrences of scope text from the payload to avoid leakage."""
    if not text:
        return text
    if scope:
        try:
            return text.replace(scope, "[SCOPE_REDACTED]")
        except Exception:
            return text
    return text


def _call_google_model(model: str, api_key: str, text: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={api_key}"
    )
    payload = {"contents": [{"parts": [{"text": text}]}]}
    response = requests.post(
        url, json=payload, headers={"Content-Type": "application/json"}, verify=False
    )
    response.raise_for_status()
    data = response.json()
    text_out = None
    if isinstance(data, dict):
        candidates = data.get("candidates")
        if candidates:
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            text_out = "".join(p.get("text", "") for p in parts)
    if not text_out:
        raise ValueError("No text returned from AI")
    return text_out


def generate_template(prompt_text: str, mission_details: str) -> str:
    """Generate a template using Google AI generative models."""
    api_key = CONFIG.get("ai_key")
    model = CONFIG.get("ai_model")
    if not api_key or not model:
        raise ValueError("AI configuration missing")

    try:
        return _call_google_model(model, api_key, f"{prompt_text}\n\n{mission_details}")
    except Exception as e:
        logger.error(f"AI generation failed: {e}")
        raise


def rewrite_text(instruction: str, selected_text: str) -> str:
    """Rewrite/transform selected_text per instruction via Google AI, returning markdown/plain text."""
    api_key = CONFIG.get("ai_key")
    model = CONFIG.get("ai_model")
    if not api_key or not model:
        raise ValueError("AI configuration missing")

    system_prompt = (
        "You are helping edit a markdown document. Follow the instruction to transform "
        "ONLY the provided selection. Keep the result concise and maintain markdown structure. "
        "Return ONLY the transformed text with no extra commentary."
    )
    composed = (
        f"{system_prompt}\n\nInstruction:\n{instruction}\n\nSelected text:\n" 
        f"""""{selected_text}"""""
    )
    return _call_google_model(model, api_key, composed)

