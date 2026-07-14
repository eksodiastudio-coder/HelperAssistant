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
MISSED_QUESTIONS_FILE = 'missed_questions.txt'

# Replace with the ID of your specific questions channel
QUESTIONS_CHANNEL_ID = 1449084904343339168 

# Channel where the bot will post questions it couldn't answer
ADMIN_CHANNEL_MISSING_ANSWERS_ID = 1461483376195145758

# NEW: Channel where helpers paste the answers. The bot will read this to learn.
# PUT YOUR CHANNEL ID HERE
ADD_MISSING_ANSWERS_CHANNEL_ID = 1474477349738381459 

ADMIN_CHANNEL_ID = 1453869127180746843
ADMIN_USER_ID = 545298092048646144 

MODEL_NAME = "gemini-flash-lite-latest"
# Setup Google GenAI Client
client_genai = genai.Client(api_key=GOOGLE_API_KEY)

# Global Variable for Combined Knowledge (File + Channel)
knowledge_base = ""

# Setup Discord Client
intents = discord.Intents.default()
intents.message_content = True
client_discord = discord.Client(intents=intents)

async def build_knowledge_base():
    """Builds knowledge from both the text file and the helpers channel."""
    global knowledge_base
    static_kb = ""
    dynamic_kb = ""
    
    # 1. Load General Info from File
    try:
        with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
            static_kb = f.read()
    except FileNotFoundError:
        print(f"CRITICAL ERROR: Could not find {KNOWLEDGE_FILE}.")
        static_kb = ""

    # 2. Load Dynamic Info from Helper Channel
    helper_channel = client_discord.get_channel(ADD_MISSING_ANSWERS_CHANNEL_ID)
    if helper_channel:
        try:
            # Fetches the last 500 messages from the helper channel
            messages = [msg async for msg in helper_channel.history(limit=500)]
            messages.reverse() # Read from oldest to newest
            for msg in messages:
                if msg.content.strip():
                    dynamic_kb += f"- {msg.content}\n"
        except Exception as e:
            print(f"Error reading helper channel: {e}")
    else:
        print("Warning: Could not find the ADD_MISSING_ANSWERS_CHANNEL_ID channel.")

    # Combine both sources
    knowledge_base = (
        f"--- GENERAL SERVER KNOWLEDGE ---\n{static_kb}\n\n"
        f"--- HELPER ADDED KNOWLEDGE (SPECIFIC ANSWERS) ---\n{dynamic_kb}"
    )
    print(f"Knowledge base compiled! ({len(knowledge_base)} characters)")
    return True


@client_discord.event
async def on_ready():
    print(f'Logged in as {client_discord.user}')
    print(f"Questions Channel: {QUESTIONS_CHANNEL_ID}")
    print(f"Admin Channel: {ADMIN_CHANNEL_ID}")
    
    # Load knowledge once the bot is connected so it can read channels
    await build_knowledge_base()


@client_discord.event
async def on_message(message):
    # Ignore own messages
    if message.author == client_discord.user:
        return

    # =======================================================
    # LOGIC 1: ADMIN COMMANDS & AUTO-LEARNING
    # =======================================================
    
    # Reload command
    if message.content == "!reload":
        if message.channel.id == ADMIN_CHANNEL_ID and message.author.id == ADMIN_USER_ID:
            success = await build_knowledge_base()
            if success:
                await message.reply("✅ Knowledge base reloaded successfully from file and channels!")
            else:
                await message.reply("❌ Error compiling knowledge base.")
        return 

    # AUTO-LEARNING: If a helper posts in the add-missing-answer channel
    if message.channel.id == ADD_MISSING_ANSWERS_CHANNEL_ID:
        await build_knowledge_base() # Update memory immediately
        await message.add_reaction("🧠") # Let the helper know the bot learned it
        return

    # =======================================================
    # LOGIC 2: PUBLIC QUESTIONS
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
            history_buffer = []
            async for msg in message.channel.history(limit=5):
                # Avoid feeding commands or empty text into the chat history
                if msg.content.startswith("!"):
                    continue
                clean_content = msg.clean_content 
                history_buffer.append(f"{msg.author.name}: {clean_content}")
            
            history_buffer.reverse()
            conversation_text = "\n".join(history_buffer)

            # --- SYSTEM INSTRUCTION & CONFIGURATION ---
            # System instructions now explicitly forbid direct copy-pasting.
            system_instruction = (
                "You are a helpful and polite Discord server support assistant.\n\n"
                "CRITICAL RULES:\n"
                "1. Answer user queries strictly using the provided Knowledge Base.\n"
                "2. DO NOT copy and paste raw paragraphs, bullet points, or list structures directly from the Knowledge Base. "
                "Instead, summarize, rephrase, and synthesize the relevant facts to construct a natural, conversational response that directly addresses the user's specific question.\n"
                "3. Match concepts, not just words. If a user asks about a specific action, apply the general guidelines present in the knowledge base.\n"
                "4. Do not use Markdown headers (like #, ##, or ###).\n"
                "5. STRICT SILENCE RULE: If the answer to the user's question cannot be found or reasonably inferred from the Knowledge Base, you MUST reply with exactly the single word 'SILENCE'. Do not explain why, do not apologize, and do not provide outside information."
            )

            # --- USER PROMPT ---
            prompt = (
                f"--- KNOWLEDGE BASE ---\n{knowledge_base}\n\n"
                f"--- CONVERSATION HISTORY ---\n{conversation_text}\n\n"
                f"User Question: {message.content}"
            )

            # Keep temperature relatively low to avoid hallucinating facts, while still allowing the language structure to be conversational.
            response = client_genai.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2
                )
            )
            
            if response.text:
                response_text = response.text.strip()
                
                # --- SILENCE CHECK (Robust evaluation) ---
                normalized_text = response_text.replace("`", "").replace('"', '').replace("'", "").strip().upper()
                
                if normalized_text == "SILENCE" or not response_text:
                    print("Answer not found. Forwarding to missing answers channel.")
                    
                    # Keep logging to file as backup
                    with open(MISSED_QUESTIONS_FILE, "a", encoding="utf-8") as log:
                        log.write(f"[{message.created_at}] {message.author.name}: {message.content}\n")
                    
                    # Send alert to Admin Missing Answers Channel
                    missing_channel = client_discord.get_channel(ADMIN_CHANNEL_MISSING_ANSWERS_ID)
                    if missing_channel:
                        await missing_channel.send(
                            f"🚨 **Unanswered Question** 🚨\n"
                            f"**User:** {message.author.mention}\n"
                            f"**Question:** {message.content}\n"
                            f"*Please add the answer to the <#{ADD_MISSING_ANSWERS_CHANNEL_ID}> channel.*"
                        )
                    return 

                # --- SENDING THE MESSAGE (PLAIN TEXT) ---
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

keep_alive()
client_discord.run(DISCORD_TOKEN)
