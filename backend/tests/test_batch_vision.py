"""
Test Azure OpenAI Batch API for Vision Analysis
Tests Global Batch deployment with a sample image
"""

import json
import os
import tempfile
import time

from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

# Configuration
endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
api_key = os.getenv("AZURE_OPENAI_API_KEY")
api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o")

print("=" * 70)
print("🧪 TESTING AZURE OPENAI BATCH API FOR VISION")
print("=" * 70)
print(f"📍 Endpoint: {endpoint}")
print(f"📋 API Version: {api_version}")
print(f"🤖 Deployment: {deployment}")
print("🎯 Deployment Type: Global Batch (for Batch API)")
print()

# Initialize client
client = AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)

# Create a simple test image (1x1 red pixel PNG)
test_image_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="

# Create batch request file
batch_requests = [
    {
        "custom_id": "test_frame_1",
        "method": "POST",
        "url": "/chat/completions",
        "body": {
            "model": deployment,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Describe what you see in this image. Be concise.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{test_image_base64}"},
                        },
                    ],
                }
            ],
            "max_tokens": 100,
        },
    },
    {
        "custom_id": "test_frame_2",
        "method": "POST",
        "url": "/chat/completions",
        "body": {
            "model": deployment,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What color is dominant in this image?"},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{test_image_base64}"},
                        },
                    ],
                }
            ],
            "max_tokens": 50,
        },
    },
]

# Write to JSONL file
with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
    for request in batch_requests:
        f.write(json.dumps(request) + "\n")
    batch_file_path = f.name

print(f"📝 Created batch file: {batch_file_path}")
print(f"📊 Batch size: {len(batch_requests)} requests")
print()

try:
    # Step 1: Upload the batch file
    print("📤 Step 1: Uploading batch file...")
    with open(batch_file_path, "rb") as f:
        batch_file = client.files.create(file=f, purpose="batch")
    print(f"✅ File uploaded: {batch_file.id}")
    print()

    # Step 2: Create batch job
    print("🚀 Step 2: Creating batch job...")
    batch_job = client.batches.create(
        input_file_id=batch_file.id, endpoint="/chat/completions", completion_window="24h"
    )
    print(f"✅ Batch job created: {batch_job.id}")
    print(f"📊 Status: {batch_job.status}")
    print()

    # Step 3: Poll for completion
    print("⏳ Step 3: Waiting for batch completion...")
    print("(This may take 3-5 minutes for Global Batch deployments)")
    print()

    max_wait = 600  # 10 minutes
    start_time = time.time()
    poll_interval = 10  # Check every 10 seconds

    while time.time() - start_time < max_wait:
        batch_status = client.batches.retrieve(batch_job.id)
        elapsed = int(time.time() - start_time)

        print(f"[{elapsed}s] Status: {batch_status.status}", end="")

        if batch_status.request_counts:
            counts = batch_status.request_counts
            print(f" | Completed: {counts.completed}/{counts.total}", end="")
            if counts.failed > 0:
                print(f" | Failed: {counts.failed}", end="")

        print()

        if batch_status.status == "completed":
            print(f"\n✅ Batch completed in {elapsed}s!")
            print()

            # Step 4: Download and parse results
            print("📥 Step 4: Downloading results...")
            result_file_id = batch_status.output_file_id

            if result_file_id:
                result_content = client.files.content(result_file_id)
                result_text = result_content.read().decode("utf-8")

                print("📊 Results:")
                print("=" * 70)

                for line in result_text.strip().split("\n"):
                    result = json.loads(line)
                    custom_id = result.get("custom_id", "unknown")

                    if result.get("response", {}).get("status_code") == 200:
                        response_body = result["response"]["body"]
                        content = response_body["choices"][0]["message"]["content"]
                        tokens = response_body["usage"]["total_tokens"]

                        print(f"\n✅ {custom_id}:")
                        print(f"   Response: {content}")
                        print(f"   Tokens: {tokens}")
                    else:
                        print(f"\n❌ {custom_id}: Failed")
                        print(f"   Error: {result.get('error', 'Unknown error')}")

                print()
                print("=" * 70)
                print("🎉 BATCH API TEST SUCCESSFUL!")
                print("=" * 70)
            else:
                print("⚠️  No output file available")

            break

        elif batch_status.status in ["failed", "expired", "cancelled"]:
            print(f"\n❌ Batch {batch_status.status}")
            if batch_status.errors:
                print(f"Errors: {batch_status.errors}")
            break

        time.sleep(poll_interval)
    else:
        print(f"\n⏰ Timeout after {max_wait}s")
        print("Batch may still be processing. Check Azure Portal for status.")
        print(f"Batch ID: {batch_job.id}")

except Exception as e:
    print(f"\n❌ Error: {e}")
    print("\nFull error details:")
    import traceback

    traceback.print_exc()

finally:
    # Cleanup
    if os.path.exists(batch_file_path):
        os.unlink(batch_file_path)
        print("\n🧹 Cleaned up batch file")
