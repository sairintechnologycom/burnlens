#!/usr/bin/env python3
"""Test all three LLM providers through BurnLens proxy."""

import os
import sys
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Verify keys are loaded
keys = {
    "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
    "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY"),
    "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY"),
}

print("🔑 API Keys Status:")
for key, value in keys.items():
    status = "✓ Loaded" if value else "✗ Missing"
    print(f"  {key}: {status}")

if not any(keys.values()):
    print("\n❌ No API keys found. Please update .env file with your keys:")
    print("  - OpenAI: https://platform.openai.com/api-keys")
    print("  - Anthropic: https://console.anthropic.com/account/keys")
    print("  - Google: https://aistudio.google.com/app/apikey")
    sys.exit(1)

print("\n🧪 Testing providers...\n")

# Test OpenAI
if keys["OPENAI_API_KEY"]:
    try:
        import openai
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=10,
            messages=[{"role": "user", "content": "hi"}]
        )
        print(f"✓ OpenAI: {response.usage}")
    except Exception as e:
        print(f"✗ OpenAI failed: {e}")

# Test Anthropic
if keys["ANTHROPIC_API_KEY"]:
    try:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "hi"}]
        )
        print(f"✓ Anthropic: {response.usage}")
    except Exception as e:
        print(f"✗ Anthropic failed: {e}")

# Test Google
if keys["GOOGLE_API_KEY"]:
    try:
        import google.generativeai as genai
        genai.configure(api_key=keys["GOOGLE_API_KEY"])
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content("hi", stream=False)
        print(f"✓ Google: Generated {len(response.text)} chars")
    except Exception as e:
        print(f"✗ Google failed: {e}")

print("\n✅ Provider tests complete!")
