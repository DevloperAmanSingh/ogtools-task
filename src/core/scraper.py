#!/usr/bin/env python3

import os
import json
import requests
import time
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
from google import genai
from dotenv import load_dotenv

load_dotenv()

TEAM_ID = "aline123"
OUTPUT_FILE = "outputs/output.json"
JINA_READER_BASE = "https://r.jina.ai/"

PRICING = {
    "input": 0.00035,
    "output": 0.00053
}

MAX_CHUNK_SIZE = 20000
CHUNK_OVERLAP = 1000

@dataclass
class BlogItem:
    title: str
    content: str
    content_type: str
    source_url: str
    author: str
    user_id: str

@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float

def calculate_cost(input_tokens: int, output_tokens: int) -> float:
    input_cost = (input_tokens / 1000) * PRICING["input"]
    output_cost = (output_tokens / 1000) * PRICING["output"]
    return input_cost + output_cost

def get_markdown_from_jina(url: str) -> str:
    jina_url = f"{JINA_READER_BASE}{url}"
    
    try:
        response = requests.get(jina_url, timeout=30)
        response.raise_for_status()
        print(response)
        return response.text
    except requests.RequestException:
        return ""

def chunk_markdown(markdown: str, max_size: int = MAX_CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    if len(markdown) <= max_size:
        return [markdown]
    
    chunks = []
    start = 0
    
    while start < len(markdown):
        end = start + max_size
        
        if end < len(markdown):
            break_point = markdown.rfind('\n\n', start, end)
            if break_point > start + max_size // 2:
                end = break_point
        
        chunk = markdown[start:end]
        chunks.append(chunk)
        
        if end >= len(markdown):
            break
            
        start = end - overlap
    
    return chunks

def extract_blog_list_with_gemini(markdown: str, source_url: str) -> Tuple[List[Dict[str, Any]], TokenUsage]:
    max_chars = 25000
    if len(markdown) > max_chars:
        markdown = markdown[:max_chars] + "\n\n[Truncated...]"
    
    prompt = f"""Extract blog post list from this markdown. Source: {source_url}

RULES:
- Extract only blog post titles and URLs 
- NO content needed, just list
- Use empty string for content field
- Find author if mentioned

JSON format:
[
  {{
    "title": "Blog Post Title",
    "content": "",
    "content_type": "blog",
    "source_url": "https://full-url-to-post.com",
    "author": "Author Name",
    "user_id": ""
  }}
]

Markdown:
{markdown}

Return only JSON array:"""

    try:
        api_key = os.getenv("GEMINI_API_KEY") 
        if not api_key:
            raise ValueError("API key not set")
        
        client = genai.Client(api_key=api_key)
        
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config={"temperature": 0, "max_output_tokens": 2000}
        )
        
        input_tokens = len(prompt) // 4
        output_tokens = len(response.text) // 4
        total_tokens = input_tokens + output_tokens
        
        token_usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost=calculate_cost(input_tokens, output_tokens)
        )
        
        content = response.text.strip()
        
        import re
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```\s*$', '', content)
        
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if json_match:
            json_str = json_match.group()
            blog_data = json.loads(json_str)
            return blog_data, token_usage
        else:
            blog_data = json.loads(content)
            return blog_data, token_usage
                
    except Exception:
        return [], TokenUsage(0, 0, 0, 0.0)

def extract_blog_content_with_gemini(markdown_chunks: List[str], blog_url: str) -> Tuple[str, TokenUsage]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("API key not set")
    
    client = genai.Client(api_key=api_key)
    total_token_usage = TokenUsage(0, 0, 0, 0.0)
    extracted_parts = []
    
    for chunk in markdown_chunks:
        prompt = f"""Extract the main blog post content from this markdown chunk. Source: {blog_url}

RULES:
- Extract only the main article/blog post content
- Remove navigation, ads, footers, sidebars
- Keep the actual blog post text, code examples, images
- Return clean, readable content

Markdown chunk:
{chunk}

Return clean blog content:"""

        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config={"temperature": 0, "max_output_tokens": 3000}
            )
            
            input_tokens = len(prompt) // 4
            output_tokens = len(response.text) // 4
            chunk_cost = calculate_cost(input_tokens, output_tokens)
            
            total_token_usage.input_tokens += input_tokens
            total_token_usage.output_tokens += output_tokens
            total_token_usage.total_tokens += input_tokens + output_tokens
            total_token_usage.cost += chunk_cost
            
            extracted_parts.append(response.text.strip())
            time.sleep(0.5)
            
        except Exception:
            continue
    
    combined_content = "\n\n".join(part for part in extracted_parts if part.strip())
    return combined_content, total_token_usage

def fetch_individual_blog_content(blog_item: Dict[str, Any]) -> Tuple[str, TokenUsage]:
    blog_url = blog_item.get("source_url", "")
    if not blog_url:
        return "", TokenUsage(0, 0, 0, 0.0)
    
    markdown = get_markdown_from_jina(blog_url)
    if not markdown.strip():
        return "", TokenUsage(0, 0, 0, 0.0)
    
    chunks = chunk_markdown(markdown)
    content, token_usage = extract_blog_content_with_gemini(chunks, blog_url)
    
    return content, token_usage

def validate_and_format_items(raw_items: List[Dict[str, Any]]) -> List[BlogItem]:
    validated_items = []
    
    for item in raw_items:
        try:
            title = item.get("title", "").strip()
            content = item.get("content", "").strip()
            content_type = item.get("content_type", "blog").strip()
            source_url = item.get("source_url", "").strip()
            author = item.get("author", "").strip()
            user_id = item.get("user_id", "").strip()
            
            if not title:
                continue
                
            blog_item = BlogItem(
                title=title,
                content=content,
                content_type=content_type,
                source_url=source_url,
                author=author,
                user_id=user_id
            )
            
            validated_items.append(blog_item)
            
        except Exception:
            continue
    
    return validated_items 