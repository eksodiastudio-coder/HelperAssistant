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

MODEL_NAME = "gemini-flash-lite-latest"
# Setup Google GenAI Client
client_genai = genai.Client(api_key=GOOGLE_API_KEY)

# ================= SYSTEM BRAIN =================
# This tells the AI how to behave regardless of the knowledge base
SYSTEM_INSTRUCTION = """
You are the official 'Project Evolvers Assistant'. Your job is to help users with questions about the game and the Discord server.

CORE RULES:
1. USE THE KNOWLEDGE BASE: Always prioritize information from the provided text.
2. BE DIRECT: Give clear, concise answers. Use bullet points for lists.
3. NO MARKDOWN HEADERS: Do not use '#' for headers. Use bold text (**) or bullet points instead.
4. CONCEPT MATCHING: If a user asks about a specific example (like "TikTok"), map it to the general rule (like "Advertising/Social Media").
5. SILENCE PROTOCOL: If the question is 100% unrelated to the game, server, or Discord, reply ONLY with the word: SILENCE.
6. PUNISHMENT INQUIRIES: If a user asks why they were banned/warned, tell them to open a ticket in the Appeal Center.
7. TONE: Helpful, professional, and observant of server rules.
"""

# Setup Clients
client_genai = genai.Client(api_key=GOOGLE_API_KEY)
intents = discord.Intents.default()
intents.message_content = True
client_discord = discord.Client(intents=intents)

knowledge_base = ""

def load_knowledge():
    """Loads and refreshes the knowledge base from knowledge.txt"""
    global knowledge_base
    try:
        with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
            knowledge_base = f.read()
        print(f"✅ Knowledge base loaded ({len(knowledge_base)} chars)")
        return True
    except FileNotFoundError:
        print(f"❌ CRITICAL ERROR: {KNOWLEDGE_FILE} not found!")
        return False

# Initial load
load_knowledge()

# Optional: Keep Alive for 24/7 hosting
try:
    from keep_alive import keep_alive
    keep_alive()
except ImportError:
    pass

@client_discord.event
async def on_ready():
    print(f'Logged in as {client_discord.user}')
    print("Bot is active and listening...")

@client_discord.event
async def on_message(message):
    # 1. Basic Filters
    if message.author == client_discord.user:
        return

    # 2. Admin Reload Command
    if message.content == "!reload":
        if message.channel.id == ADMIN_CHANNEL_ID and message.author.id == ADMIN_USER_ID:
            if load_knowledge():
                await message.reply("✅ Knowledge base reloaded successfully!")
            else:
                await message.reply("❌ Error: Knowledge file missing.")
        return

    # 3. Channel/Mention Check
    is_question_channel = message.channel.id == QUESTIONS_CHANNEL_ID
    is_mentioned = client_discord.user in message.mentions
    
    # Only proceed if in the right channel or the bot is mentioned
    if not (is_question_channel or is_mentioned):
        return

    # 4. Process the Question
    async with message.channel.typing():
        try:
            # Build Conversation History for Context
            history_buffer = []
            async for msg in message.channel.history(limit=6):
                role = "model" if msg.author == client_discord.user else "user"
                history_buffer.append(f"{role.upper()}: {msg.clean_content}")
            
            history_buffer.reverse()
            conversation_context = "\n".join(history_buffer)

            # Construct the final prompt
            prompt = (
                f"--- KNOWLEDGE BASE ---\n{knowledge_base}\n\n"
                f"--- RECENT CONVERSATION ---\n{conversation_context}\n\n"
                f"USER QUESTION: {message.content}"
            )

            # API Call with Retry Logic
            response_text = None
            for attempt in range(3):
                try:
                    response = client_genai.models.generate_content(
                        model=MODEL_NAME,
                        config={
                            "system_instruction": SYSTEM_INSTRUCTION,
                            "temperature": 0.3, # Low temperature for factual accuracy
                            "top_p": 0.8,
                        },
                        contents=prompt
                    )
                    if response.text:
                        response_text = response.text.strip()
                        break
                except Exception as api_err:
                    if "429" in str(api_err): # Rate limit
                        print(f"Rate limit hit, retrying in 5s... (Attempt {attempt+1})")
                        await asyncio.sleep(5)
                    else:
                        print(f"API Error: {api_err}")
                        break

            if not response_text:
                return

            # 5. Handle AI Decision
            if "SILENCE" in response_text:
                print(f"Missed question log sent for: {message.author.name}")
                admin_channel = client_discord.get_channel(ADMIN_CHANNEL_MISSING_ANSWERS_ID)
                if admin_channel:
                    embed = discord.Embed(title="⚠️ Missed Question", color=discord.Color.orange())
                    embed.add_field(name="User", value=message.author.mention, inline=True)
                    embed.add_field(name="Channel", value=message.channel.name, inline=True)
                    embed.add_field(name="Content", value=message.content, inline=False)
                    await admin_channel.send(embed=embed)
                return

            # 6. Send Response (with 2000 char handling)
            if len(response_text) > 2000:
                for i in range(0, len(response_text), 1900):
                    await message.reply(response_text[i:i+1900])
            else:
                await message.reply(response_text)

        except Exception as e:
            print(f"Critical Error: {e}")

# Run Bot
client_discord.run(DISCORD_TOKEN)





