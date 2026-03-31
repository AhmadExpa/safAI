import os
import json
import logging
import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List
from app.routers.openai.openai_chat import get_token_from_header, decode_email_from_token, get_user_id_from_email, store_chat

logger = logging.getLogger(__name__)
router = APIRouter()

# Perplexity API configuration - used via lazy loading
_pplx_config = None

def get_pplx_config():
    """Get Perplexity configuration with lazy loading to ensure env vars are loaded"""
    global _pplx_config
    if _pplx_config is None:
        from dotenv import load_dotenv
        load_dotenv()
        
        api_key = os.getenv("PPLX_API_KEY")
        if api_key:
            api_key = api_key.strip().replace('"', '').replace("'", "")
            
        _pplx_config = {
            "api_key": api_key
        }
        
        if not _pplx_config["api_key"]:
            logger.warning("PPLX_API_KEY not found in environment variables")
            
    return _pplx_config
# Model candidates to try in order - TESTED AND VERIFIED WORKING (Dec 2024)
PPLX_MODEL_CANDIDATES = [
    "sonar-pro",              # Pro model - VERIFIED WORKING
    "sonar-reasoning-pro",    # Reasoning Pro - VERIFIED WORKING
    "sonar-reasoning",        # Reasoning - VERIFIED WORKING
    "sonar-deep-research",    # Deep Research - VERIFIED WORKING
    "sonar",                  # Standard - VERIFIED WORKING
]


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]
    conversation_id: str = None
    project_id: str = None
    personality_id: str = None


@router.post("/perplexity/chat")
async def chat_perplexity(request: Request, chat_request: ChatRequest):
    config = get_pplx_config()
    if not config["api_key"]:
        raise HTTPException(status_code=500, detail="PPLX_API_KEY is not set")

    user_id = None
    try:
        token = get_token_from_header(request)
        if token:
            email = decode_email_from_token(token)
            if email:
                user_id = await get_user_id_from_email(email)
    except Exception as e:
        logger.warning(f"Perplexity auth decode failed: {e}")

    async def event_stream():
        config = get_pplx_config()
        api_key = config["api_key"]
        
        if not api_key:
            yield f"data: {json.dumps({'content': 'Perplexity API key not configured'})}\n\n"
            yield "data: [DONE]\n\n"
            return
            
        url = "https://api.perplexity.ai/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        last_error = None
        # Try each model candidate until one works
        for model_name in PPLX_MODEL_CANDIDATES:
            try:
                body = {
                    "model": model_name,
                    "messages": [{"role": m.role, "content": m.content} for m in chat_request.messages],
                    "stream": True,
                }
                logger.info(f"Perplexity: trying model={model_name}")
                async with httpx.AsyncClient(timeout=300.0) as client:
                    async with client.stream("POST", url, headers=headers, json=body) as resp:
                        if resp.status_code != 200:
                            text = await resp.aread()
                            error_detail = text.decode()
                            try:
                                error_json = json.loads(error_detail)
                                if isinstance(error_json, dict) and 'error' in error_json:
                                    if isinstance(error_json['error'], dict):
                                        error_detail = error_json['error'].get('message', error_detail)
                                    else:
                                        error_detail = str(error_json['error'])
                            except:
                                pass
                            logger.warning(f"Perplexity model {model_name} failed: {error_detail}")
                            last_error = f"API Error ({resp.status_code}): {error_detail}"
                            continue  # Try next model
                        # Success! Stream the response
                        logger.info(f"✅ Perplexity: successfully using model={model_name}")
                        async for line in resp.aiter_lines():
                            if not line or not line.startswith("data: "):
                                continue
                            data = line[6:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                parsed = json.loads(data)
                                delta = parsed.get("choices", [{}])[0].get("delta", {}).get("content")
                                if delta:
                                    yield f"data: {json.dumps({'content': delta})}\n\n"
                            except json.JSONDecodeError:
                                continue
                        yield "data: [DONE]\n\n"
                        return  # Exit after successful response
            except Exception as e:
                logger.warning(f"Perplexity error with model {model_name}: {e}")
                last_error = str(e)
                continue  # Try next model
        # All models failed
        logger.error(f"All Perplexity models failed. Last error: {last_error}")
        yield f"data: {json.dumps({'content': last_error or 'All Perplexity models unavailable'})}\n\n"
        yield "data: [DONE]\n\n"

    async def aggregated():
        collected = []
        async for chunk in event_stream():
            if chunk.startswith("data: "):
                payload = chunk[6:].strip()
                if payload == "[DONE]":
                    yield chunk
                    break
                try:
                    parsed = json.loads(payload)
                    if "content" in parsed:
                        collected.append(parsed["content"])
                except Exception:
                    pass
            yield chunk
        if user_id:
            try:
                response_text = "".join(collected)
                await store_chat(user_id, chat_request, response_text, "Perplexity")
            except Exception as e:
                logger.warning(f"Perplexity store failed: {e}")

    return StreamingResponse(aggregated(), media_type="text/event-stream")

