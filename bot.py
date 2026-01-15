import discord
from google import genai
from dotenv import load_dotenv
import os
import asyncio
from keep_alive import keep_alive # <--- ADD THIS

load_dotenv()

# ================= CONFIGURATION =================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
KNOWLEDGE_FILE = 'knowledge.txt'
# Replace with the ID of your specific questions channel
MISSED_QUESTIONS_FILE = 'missed_questions.txt'

# Replace with the ID of your specific questions channel
QUESTIONS_CHANNEL_ID = 1449084904343339168 

ADMIN_CHANNEL_MISSING_ANSWERS_ID = 1461483376195145758

# Replace with YOUR Discord User ID (Integer) so only you can use !reload
# Turn on Developer Mode in Discord -> Right Click your Name -> Copy User ID
ADMIN_USER_ID = 545298092048646144 

ADMIN_CHANNEL_ID = 1453869127180746843

MODEL_NAME = "gemini-2.0-flash-lite-preview-02-05"
# Setup Google GenAI Client
client_genai = genai.Client(api_key=GOOGLE_API_KEY)

# Global Variable for Knowledge
knowledge_base = ""

def load_knowledge():
    """Helper function to load knowledge from file."""
    global knowledge_base
    try:
        with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
            knowledge_base = f.read()
        print(f"Knowledge file loaded! ({len(knowledge_base)} characters)")
        return True
    except FileNotFoundError:
        print(f"CRITICAL ERROR: Could not find {KNOWLEDGE_FILE}.")
        knowledge_base = ""
        return False

# Initial Load
load_knowledge()

# Setup Discord Client
intents = discord.Intents.default()
intents.message_content = True
client_discord = discord.Client(intents=intents)

# Keep Alive (For Render)
# Only needed if you added keep_alive.py and requirements.txt contains flask
try:
    from keep_alive import keep_alive
    keep_alive()
except ImportError:
    print("Keep alive module not found. Skipping web server.")

@client_discord.event
async def on_ready():
    print(f'Logged in as {client_discord.user}')
    print(f"Questions Channel: {QUESTIONS_CHANNEL_ID}")
    print(f"Missed Qs Channel: {ADMIN_CHANNEL_MISSING_ANSWERS_ID}")

@client_discord.event
async def on_message(message):
    if message.author == client_discord.user:
        return

    # 1. ADMIN COMMANDS (!reload)
    if message.content == "!reload":
        if message.channel.id == ADMIN_CHANNEL_ID and message.author.id == ADMIN_USER_ID:
            success = load_knowledge()
            if success:
                await message.reply("✅ Knowledge base reloaded successfully!")
            else:
                await message.reply("❌ Error: Could not find the knowledge file.")
        return 

    # 2. PUBLIC QUESTIONS
    if message.channel.id != QUESTIONS_CHANNEL_ID:
        return

    is_question = message.content.strip().endswith("?")
    is_mentioned = client_discord.user in message.mentions

    if not (is_question or is_mentioned):
        return

    if not knowledge_base:
        return 

    print(f"Processing for {message.author}: {message.content}")

    async with message.channel.typing():
        try:
            # Context
            history_buffer = []
            async for msg in message.channel.history(limit=5):
                clean_content = msg.clean_content 
                history_buffer.append(f"{msg.author.name}: {clean_content}")
            
            history_buffer.reverse()
            conversation_text = "\n".join(history_buffer)

            prompt = (
                f"You are a helpful assistant for a Discord server. "
                f"Use the 'Knowledge Base' below to answer the user's question.\n\n"
                
                f"INSTRUCTIONS FOR AI:\n"
                f"1. **Match Concepts, Not Just Words:** If the user asks about a specific example (e.g., 'YouTube') and the rules mention a general category (e.g., 'No Advertising'), you MUST apply the rule and answer.\n"
                f"2. **Be Direct:** Answer clearly based on the text provided.\n"
                f"3. **When to use SILENCE:** Only reply 'SILENCE' if the user's question is completely unrelated to anything in the Knowledge Base. If you are 60% sure, give the answer.\n"
                f"4. Do NOT use markdown headers like #.\n\n"

                f"--- KNOWLEDGE BASE ---\n{knowledge_base}\n\n"
                f"--- CONVERSATION HISTORY ---\n{conversation_text}\n\n"
                f"User Question: {message.content}"
            )

            response = client_genai.models.generate_content(
                model=MODEL_NAME,
                contents=prompt
            )
            
            if response.text:
                response_text = response.text.strip()
                
                # --- SILENCE CHECK (The part you fixed) ---
                if response_text == "SILENCE":
                    print(f"Missed question from {message.author.name}")
                    
                    # 1. Stay Silent to the user
                    
                    # 2. Send to Admin Channel
                    # We use the new variable here
                    admin_channel = client_discord.get_channel(ADMIN_CHANNEL_MISSING_ANSWERS_ID)
                    if admin_channel:
                        await admin_channel.send(
                            f"⚠️ **Missed Question**\n"
                            f"**User:** {message.author.name}\n"
                            f"**Question:** {message.content}"
                        )
                    return 

                # --- SENDING MESSAGE ---
                if len(response_text) > 2000:
                    parts = [response_text[i:i+1900] for i in range(0, len(response_text), 1900)]
                    for index, part in enumerate(parts):
                        if index == 0:
                            await message.reply(part)
                        else:
                            await message.channel.send(part)
                else:
                    await message.reply(response_text)

        except Exception as e:
            print(f"Error: {e}")

client_discord.run(DISCORD_TOKEN)


