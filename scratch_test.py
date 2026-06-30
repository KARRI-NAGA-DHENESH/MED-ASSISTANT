import asyncio
import os
import sys

# Ensure current directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.agent import app
from google.adk.runners import InMemoryRunner
from google.genai import types

async def main():
    print("Initializing InMemoryRunner...")
    runner = InMemoryRunner(app=app)
    
    print("Creating test session...")
    session = await runner.session_service.create_session(
        app_name="app", user_id="test_user"
    )
    print(f"Session created: {session.id}")
    
    print("Sending test message: 'hello'...")
    try:
        async for event in runner.run_async(
            user_id="test_user",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part.from_text(text="hello")]),
        ):
            print(f"\n[EVENT] author={event.author} route={event.route}")
            if event.output:
                print(f"  Output: {event.output}")
            if event.content:
                print(f"  Content: {event.content}")
    except Exception as e:
        print("\n--- EXCEPTION ENCOUNTERED ---")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
