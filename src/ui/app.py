#!/usr/bin/env python3

import streamlit as st
import pandas as pd
import time
import json
import os
import sys
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from src.core.scraper import (
    get_markdown_from_jina,
    extract_blog_list_with_gemini,
    fetch_individual_blog_content,
    validate_and_format_items,
    TokenUsage,
    BlogItem
)

st.set_page_config(
    page_title="Blog Scraper",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stage-container {
        background-color: #f8f9fa;
        padding: 1.5rem;
        border-radius: 10px;
        border-left: 4px solid #667eea;
        margin: 1rem 0;
    }
    .main > div {
        padding-top: 1rem;
    }
</style>
""", unsafe_allow_html=True)

def initialize_session_state():
    if 'stage' not in st.session_state:
        st.session_state.stage = 'input'
    if 'blog_items' not in st.session_state:
        st.session_state.blog_items = []
    if 'processing_complete' not in st.session_state:
        st.session_state.processing_complete = False

def extract_content_directly():
    st.markdown('<div class="stage-container">', unsafe_allow_html=True)
    st.subheader("🔍 Blog Content Extraction")
    
    url = st.text_input(
        "Blog Website URL:",
        value="https://blog.python.org/",
        placeholder="Enter the main blog page URL...",
        help="Enter the URL of the main blog page"
    )
    
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        st.error("🔑 **API Key Required**: Please set GEMINI_API_KEY or GOOGLE_API_KEY environment variable")
        st.code("export GEMINI_API_KEY=your_api_key_here")
        st.markdown('</div>', unsafe_allow_html=True)
        return
    
    max_posts = st.number_input(
        "Maximum posts to extract:",
        min_value=1,
        max_value=20,
        value=5,
        help="Limit the number of posts to process"
    )
    
    if st.button("🚀 Start Content Extraction", type="primary", use_container_width=True):
        if not url.strip():
            st.error("Please enter a valid URL")
            return
        
        overall_progress = st.progress(0)
        status_text = st.empty()
        post_progress_container = st.container()
        
        try:
            # Step 1: Get blog list
            status_text.text("📄 Finding blog posts...")
            overall_progress.progress(0.1)
            
            markdown = get_markdown_from_jina(url)
            if not markdown.strip():
                st.error("❌ Failed to get markdown content from the URL")
                return
            
            status_text.text("🔍 Extracting blog post URLs...")
            overall_progress.progress(0.2)
            
            raw_items, token_usage = extract_blog_list_with_gemini(markdown, url)
            if not raw_items:
                st.error("❌ No blog posts found on the page")
                return
            
            # Limit posts to process
            posts_to_process = raw_items[:max_posts]
            total_posts = len(posts_to_process)
            
            status_text.text(f"📝 Found {total_posts} posts - extracting content...")
            
            # Step 2: Extract content from each post
            processed_items = []
            
            for i, item in enumerate(posts_to_process):
                progress = 0.2 + (0.8 * i / total_posts)
                overall_progress.progress(progress)
                status_text.text(f"📖 Processing post {i+1} of {total_posts}: {item.get('title', 'Unknown')[:40]}...")
                
                with post_progress_container:
                    with st.expander(f"📝 Post {i+1}/{total_posts}: {item.get('title', 'Unknown')[:60]}...", expanded=(i==0)):
                        post_col1, post_col2 = st.columns([3, 1])
                        
                        with post_col1:
                            post_progress = st.progress(0)
                            post_status = st.empty()
                        
                        with post_col2:
                            post_metrics = st.empty()
                        
                        post_status.text("🔄 Fetching content...")
                        post_progress.progress(50)
                        
                        content, content_tokens = fetch_individual_blog_content(item)
                        item["content"] = content
                        
                        post_progress.progress(100)
                        post_status.text("✅ Complete")
                        
                        with post_metrics:
                            st.metric("Characters", f"{len(content):,}")
                            if content.strip():
                                st.success("✅ Extracted")
                                # Show extracted content immediately
                                with st.expander(f"📖 Content Preview - {item.get('title', 'Unknown')[:40]}...", expanded=False):
                                    st.write(f"**Author:** {item.get('author', 'Unknown')}")
                                    st.write(f"**Type:** {item.get('content_type', 'blog')}")
                                    st.write(f"**URL:** {item.get('source_url', '')}")
                                    
                                    if len(content) > 500:
                                        preview = content[:500] + "..."
                                        st.text_area("Content", value=preview, height=150, key=f"preview_{i}", label_visibility="hidden")
                                        st.write(f"*Preview showing first 500 of {len(content):,} characters*")
                                    else:
                                        st.text_area("Content", value=content, height=150, key=f"preview_{i}", label_visibility="hidden")
                            else:
                                st.warning("❌ No content found")
                
                processed_items.append(item)
            
            # Final processing
            overall_progress.progress(1.0)
            status_text.text(f"✅ Content extraction complete! Found {len(processed_items)} posts.")
            
            validated_items = validate_and_format_items(processed_items)
            st.session_state.blog_items = validated_items
            st.session_state.processing_complete = True
            st.session_state.stage = 'results'
            
            time.sleep(1)
            st.rerun()
            
        except Exception as e:
            st.error(f"❌ Error during extraction: {str(e)}")
    
    st.markdown('</div>', unsafe_allow_html=True)

def display_final_results():
    st.subheader("🎉 Scraping Complete!")
    
    st.write(f"**Successfully extracted {len(st.session_state.blog_items)} blog posts:**")
    
    st.subheader("📝 Extracted Blog Posts")
    
    for i, item in enumerate(st.session_state.blog_items, 1):
        with st.expander(f"📰 {i}. {item.title}"):
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.write(f"**URL:** {item.source_url}")
                st.write(f"**Author:** {item.author or 'Unknown'}")
                st.write(f"**Type:** {item.content_type}")
                st.write(f"**Content Length:** {len(item.content):,} characters")
                
                if item.content:
                    st.write("**Content Preview:**")
                    preview = item.content[:500] + "..." if len(item.content) > 500 else item.content
                    st.text_area("Content Preview", value=preview, height=200, key=f"content_{i}", label_visibility="hidden")
                else:
                    st.warning("No content extracted - the post might be empty or inaccessible")
            
            with col2:
                item_json = {
                    "title": item.title,
                    "content": item.content,
                    "content_type": item.content_type,
                    "source_url": item.source_url,
                    "author": item.author,
                    "user_id": item.user_id
                }
                
                st.download_button(
                    label="📥 Download JSON",
                    data=json.dumps(item_json, indent=2),
                    file_name=f"blog_post_{i}.json",
                    mime="application/json",
                    key=f"download_{i}"
                )
    
    all_results = {
        "team_id": "aline123",
        "items": [
            {
                "title": item.title,
                "content": item.content,
                "content_type": item.content_type,
                "source_url": item.source_url,
                "author": item.author,
                "user_id": item.user_id
            }
            for item in st.session_state.blog_items
        ]
    }
    
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="📥 Download All Results (JSON)",
            data=json.dumps(all_results, indent=2),
            file_name="blog_scraper_results.json",
            mime="application/json",
            type="primary",
            use_container_width=True
        )
    
    with col2:
        if st.button("🔄 Start New Scraping", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

def main():
    initialize_session_state()
    
    st.title("📰 Blog Scraper")
    st.write("Extract blog posts with AI-powered content extraction")
    
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            st.success("✅ API Key configured")
        else:
            st.error("❌ API Key not found")
            st.code("export GEMINI_API_KEY=your_key")
        
        st.header("📋 Process Overview")
        st.write("""
        **Content Extraction**
        - Finds all blog posts on the page
        - Extracts full content from each post
        - Shows progress: "Processing 3 of 10 posts"
        """)
        
        if st.session_state.processing_complete:
            st.header("📊 Status")
            st.write("✅ Content extraction complete!")
    
    if st.session_state.stage == 'input':
        extract_content_directly()
    elif st.session_state.stage == 'results':
        display_final_results()

if __name__ == "__main__":
    main() 