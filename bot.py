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

# Replace with YOUR Discord User ID (Integer) so only you can use !reload
# Turn on Developer Mode in Discord -> Right Click your Name -> Copy User ID
ADMIN_USER_ID = 545298092048646144 

ADMIN_CHANNEL_ID = 1453869127180746843

MODEL_NAME = "gemini-flash-lite-latest"
# =================================================

if not DISCORD_TOKEN or not GOOGLE_API_KEY:
    raise ValueError("Error: DISCORD_TOKEN or GOOGLE_API_KEY is missing from environment variables.")

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

@client_discord.event
async def on_ready():
    print(f'Logged in as {client_discord.user}')
    print(f"Questions Channel: {QUESTIONS_CHANNEL_ID}")
    print(f"Admin Channel: {ADMIN_CHANNEL_ID}")

@client_discord.event
async def on_message(message):
    # Ignore own messages
    if message.author == client_discord.user:
        return

    # =======================================================
    # LOGIC 1: ADMIN COMMANDS (Check this FIRST)
    # =======================================================
    if message.content == "!reload":
        # Check if it is the correct channel AND the correct user
        if message.channel.id == ADMIN_CHANNEL_ID and message.author.id == ADMIN_USER_ID:
            success = load_knowledge()
            if success:
                await message.reply("✅ Knowledge base reloaded successfully!")
            else:
                await message.reply("❌ Error: Could not find the knowledge file.")
        return # Stop processing here if it was a command (even if unauthorized)

    # =======================================================
    # LOGIC 2: PUBLIC QUESTIONS (Check this SECOND)
    # =======================================================
    
    # If the message is NOT in the questions channel, stop immediately.
    if message.channel.id != QUESTIONS_CHANNEL_ID:
        return

    # Check triggers: Ends with "?" OR Bot is Mentioned
    is_question = message.content.strip().endswith("?")
    is_mentioned = client_discord.user in message.mentions

    if not (is_question or is_mentioned):
        return

    if not knowledge_base:
        return 

    print(f"Processing for {message.author}: {message.content}")

    async with message.channel.typing():
        try:
            # --- CONTEXT AWARENESS ---
            # Fetch last 5 messages for context
            history_buffer = []
            async for msg in message.channel.history(limit=5):
                clean_content = msg.clean_content 
                history_buffer.append(f"{msg.author.name}: {clean_content}")
            
            history_buffer.reverse()
            conversation_text = "\n".join(history_buffer)

            # --- PROMPT ---
            prompt = (
                f"You are a helpful and polite assistant for a Discord server. "
                f"Your goal is to answer the user's question based strictly on the 'Knowledge Base'.\n\n"
                
                f"INSTRUCTIONS:\n"
                f"1. Use the 'Conversation History' to understand context.\n"
                f"2. If the answer is found in the Knowledge Base, answer clearly.\n"
                f"3. If the answer is NOT in the Knowledge Base, reply with exactly 'SILENCE'.\n"
                f"4. Do NOT use markdown headers (like # or ##). Just plain text.\n\n"

                f"--- KNOWLEDGE BASE ---\n{knowledge_base}\n\n"
                f"--- CONVERSATION HISTORY ---\n{conversation_text}\n\n"
                f"Current User Question: {message.content}"
            )

            response = client_genai.models.generate_content(
                model=MODEL_NAME,
                contents=prompt
            )
            
            if response.text:
                response_text = response.text.strip()
                
                # --- SILENCE CHECK ---
                if response_text == "SILENCE":
                    print("Answer not found. Logging to missed_questions.txt")
                    with open(MISSED_QUESTIONS_FILE, "a", encoding="utf-8") as log:
                        log.write(f"[{message.created_at}] {message.author.name}: {message.content}\n")
                    return 

                # --- SENDING THE MESSAGE (PLAIN TEXT) ---
                # Check for length limit (2000 chars)
                if len(response_text) > 2000:
                    # Split into chunks of 1900 to be safe
                    parts = [response_text[i:i+1900] for i in range(0, len(response_text), 1900)]
                    
                    for index, part in enumerate(parts):
                        if index == 0:
                            # Reply to the user for the first part
                            await message.reply(part)
                        else:
                            # Send the rest as normal messages
                            await message.channel.send(part)
                else:
                    # Short message: Just reply normally
                    await message.reply(response_text)

        except Exception as e:
            print(f"Error: {e}")
keep_alive() # <--- ADD THIS


client_discord.run(DISCORD_TOKEN)
