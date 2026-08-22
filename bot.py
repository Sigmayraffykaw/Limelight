import os
import random
import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = "limelight.db"
CURRENCY = "🍋"
STARTING_BALANCE = 500
DAILY_REWARD = 250

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def db():
    return sqlite3.connect(DB_PATH)


def init_db():
    with db() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 500,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                games INTEGER NOT NULL DEFAULT 0,
                last_daily TEXT
            )
            """
        )


def ensure_user(user_id: int):
    with db() as con:
        con.execute(
            "INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, ?)",
            (user_id, STARTING_BALANCE),
        )


def get_user(user_id: int):
    ensure_user(user_id)
    with db() as con:
        return con.execute(
            "SELECT balance, wins, losses, games, last_daily FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()


def change_balance(user_id: int, amount: int):
    ensure_user(user_id)
    with db() as con:
        con.execute(
            "UPDATE users SET balance = MAX(0, balance + ?) WHERE user_id = ?",
            (amount, user_id),
        )


def record_result(user_id: int, won: bool):
    ensure_user(user_id)
    with db() as con:
        if won:
            con.execute(
                "UPDATE users SET wins = wins + 1, games = games + 1 WHERE user_id = ?",
                (user_id,),
            )
        else:
            con.execute(
                "UPDATE users SET losses = losses + 1, games = games + 1 WHERE user_id = ?",
                (user_id,),
            )


def fmt(amount: int) -> str:
    return f"{CURRENCY} {amount:,}"


@bot.event
async def on_ready():
    init_db()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as exc:
        print(f"Command sync failed: {exc}")
    print(f"Logged in as {bot.user} ({bot.user.id})")


@bot.tree.command(name="help", description="Show Limelight's commands")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🍋 Limelight Minigames",
        description="Play games, earn coins, and climb the server leaderboard.",
        color=0x9BE564,
    )
    embed.add_field(
        name="🎮 Games",
        value="`/rps` `/coinflip` `/dice` `/guess` `/trivia` `/blacktea`",
        inline=False,
    )
    embed.add_field(
        name="💰 Economy",
        value="`/balance` `/daily` `/pay` `/leaderboard` `/stats`",
        inline=False,
    )
    embed.add_field(
        name="🎰 Betting",
        value="Use the `bet` option on supported games. All bets use Limelight's virtual coins only.",
        inline=False,
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="balance", description="Check a Limelight coin balance")
@app_commands.describe(member="Whose balance to view")
async def balance(interaction: discord.Interaction, member: discord.Member | None = None):
    target = member or interaction.user
    balance_value, *_ = get_user(target.id)
    await interaction.response.send_message(
        f"💰 **{target.display_name}** has **{fmt(balance_value)}**."
    )


@bot.tree.command(name="daily", description="Claim your daily Limelight coins")
async def daily(interaction: discord.Interaction):
    user_id = interaction.user.id
    balance_value, wins, losses, games, last_daily = get_user(user_id)
    now = datetime.now(timezone.utc)

    if last_daily:
        last = datetime.fromisoformat(last_daily)
        next_claim = last + timedelta(hours=24)
        if now < next_claim:
            remaining = next_claim - now
            hours, rem = divmod(int(remaining.total_seconds()), 3600)
            minutes = rem // 60
            await interaction.response.send_message(
                f"⏳ You already claimed your daily. Try again in **{hours}h {minutes}m**.",
                ephemeral=True,
            )
            return

    with db() as con:
        con.execute(
            "UPDATE users SET balance = balance + ?, last_daily = ? WHERE user_id = ?",
            (DAILY_REWARD, now.isoformat(), user_id),
        )

    await interaction.response.send_message(
        f"🎁 Daily claimed! You received **{fmt(DAILY_REWARD)}**."
    )


@bot.tree.command(name="pay", description="Give another member some Limelight coins")
@app_commands.describe(member="Member to pay", amount="Amount of coins")
async def pay(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1000000]):
    if member.bot:
        await interaction.response.send_message("You can't pay bots.", ephemeral=True)
        return
    if member.id == interaction.user.id:
        await interaction.response.send_message("You can't pay yourself.", ephemeral=True)
        return

    sender_balance, *_ = get_user(interaction.user.id)
    if sender_balance < amount:
        await interaction.response.send_message("You don't have enough coins.", ephemeral=True)
        return

    change_balance(interaction.user.id, -amount)
    change_balance(member.id, amount)
    await interaction.response.send_message(
        f"💸 {interaction.user.mention} paid {member.mention} **{fmt(amount)}**."
    )


@bot.tree.command(name="stats", description="View a player's minigame stats")
@app_commands.describe(member="Player to view")
async def stats(interaction: discord.Interaction, member: discord.Member | None = None):
    target = member or interaction.user
    balance_value, wins, losses, games, _ = get_user(target.id)
    winrate = (wins / games * 100) if games else 0
    embed = discord.Embed(title=f"📊 {target.display_name}'s Stats", color=0x9BE564)
    embed.add_field(name="Balance", value=fmt(balance_value))
    embed.add_field(name="Wins", value=str(wins))
    embed.add_field(name="Losses", value=str(losses))
    embed.add_field(name="Games", value=str(games))
    embed.add_field(name="Win rate", value=f"{winrate:.1f}%")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard", description="Show the richest Limelight players")
async def leaderboard(interaction: discord.Interaction):
    with db() as con:
        rows = con.execute(
            "SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10"
        ).fetchall()

    if not rows:
        await interaction.response.send_message("No players yet.")
        return

    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, balance_value) in enumerate(rows):
        member = interaction.guild.get_member(user_id) if interaction.guild else None
        name = member.display_name if member else f"User {user_id}"
        prefix = medals[i] if i < 3 else f"**{i + 1}.**"
        lines.append(f"{prefix} {name} — **{fmt(balance_value)}**")

    embed = discord.Embed(
        title="🏆 Limelight Rich List",
        description="\n".join(lines),
        color=0x9BE564,
    )
    await interaction.response.send_message(embed=embed)


RPS_CHOICES = {
    "rock": "🪨",
    "paper": "📄",
    "scissors": "✂️",
}


@bot.tree.command(name="rps", description="Play rock paper scissors against Limelight")
@app_commands.describe(choice="Your move", bet="Virtual coins to wager")
@app_commands.choices(
    choice=[
        app_commands.Choice(name="Rock", value="rock"),
        app_commands.Choice(name="Paper", value="paper"),
        app_commands.Choice(name="Scissors", value="scissors"),
    ]
)
async def rps(
    interaction: discord.Interaction,
    choice: app_commands.Choice[str],
    bet: app_commands.Range[int, 0, 1000000] = 0,
):
    balance_value, *_ = get_user(interaction.user.id)
    if bet > balance_value:
        await interaction.response.send_message("You don't have enough coins for that bet.", ephemeral=True)
        return

    player = choice.value
    computer = random.choice(list(RPS_CHOICES))

    if player == computer:
        result = "tie"
    elif (player, computer) in [("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")]:
        result = "win"
    else:
        result = "lose"

    if result == "win":
        reward = bet if bet else 50
        change_balance(interaction.user.id, reward)
        record_result(interaction.user.id, True)
        result_text = f"🏆 You win! **+{fmt(reward)}**"
    elif result == "lose":
        loss = bet if bet else 0
        if loss:
            change_balance(interaction.user.id, -loss)
        record_result(interaction.user.id, False)
        result_text = f"💥 You lose!" + (f" **-{fmt(loss)}**" if loss else "")
    else:
        result_text = "🤝 Tie — your bet is returned."

    await interaction.response.send_message(
        f"You: {RPS_CHOICES[player]} **{player.title()}**\n"
        f"Limelight: {RPS_CHOICES[computer]} **{computer.title()}**\n\n{result_text}"
    )


@bot.tree.command(name="coinflip", description="Bet virtual coins on heads or tails")
@app_commands.describe(side="Heads or tails", bet="Virtual coins to wager")
@app_commands.choices(
    side=[
        app_commands.Choice(name="Heads", value="heads"),
        app_commands.Choice(name="Tails", value="tails"),
    ]
)
async def coinflip(
    interaction: discord.Interaction,
    side: app_commands.Choice[str],
    bet: app_commands.Range[int, 1, 1000000],
):
    balance_value, *_ = get_user(interaction.user.id)
    if bet > balance_value:
        await interaction.response.send_message("You don't have enough coins for that bet.", ephemeral=True)
        return

    result = random.choice(["heads", "tails"])
    emoji = "🪙"
    if side.value == result:
        change_balance(interaction.user.id, bet)
        record_result(interaction.user.id, True)
        text = f"{emoji} **{result.title()}!** You won **{fmt(bet)}**."
    else:
        change_balance(interaction.user.id, -bet)
        record_result(interaction.user.id, False)
        text = f"{emoji} **{result.title()}!** You lost **{fmt(bet)}**."
    await interaction.response.send_message(text)


@bot.tree.command(name="dice", description="Roll a die against Limelight")
@app_commands.describe(bet="Virtual coins to wager")
async def dice(interaction: discord.Interaction, bet: app_commands.Range[int, 0, 1000000] = 0):
    balance_value, *_ = get_user(interaction.user.id)
    if bet > balance_value:
        await interaction.response.send_message("You don't have enough coins for that bet.", ephemeral=True)
        return

    player = random.randint(1, 6)
    computer = random.randint(1, 6)
    if player > computer:
        reward = bet if bet else 40
        change_balance(interaction.user.id, reward)
        record_result(interaction.user.id, True)
        result = f"🏆 You win **+{fmt(reward)}**"
    elif player < computer:
        if bet:
            change_balance(interaction.user.id, -bet)
        record_result(interaction.user.id, False)
        result = "💥 You lose" + (f" **-{fmt(bet)}**" if bet else "")
    else:
        result = "🤝 Tie"

    await interaction.response.send_message(
        f"🎲 You rolled **{player}**\n🎲 Limelight rolled **{computer}**\n\n{result}"
    )


@bot.tree.command(name="guess", description="Guess Limelight's number from 1 to 10")
@app_commands.describe(number="Your guess", bet="Virtual coins to wager")
async def guess(
    interaction: discord.Interaction,
    number: app_commands.Range[int, 1, 10],
    bet: app_commands.Range[int, 0, 1000000] = 0,
):
    balance_value, *_ = get_user(interaction.user.id)
    if bet > balance_value:
        await interaction.response.send_message("You don't have enough coins for that bet.", ephemeral=True)
        return

    answer = random.randint(1, 10)
    if number == answer:
        reward = bet * 8 if bet else 150
        change_balance(interaction.user.id, reward)
        record_result(interaction.user.id, True)
        text = f"🎯 Correct! It was **{answer}**. You won **{fmt(reward)}**!"
    else:
        if bet:
            change_balance(interaction.user.id, -bet)
        record_result(interaction.user.id, False)
        text = f"❌ It was **{answer}**. Better luck next round." + (f" You lost **{fmt(bet)}**." if bet else "")
    await interaction.response.send_message(text)


TRIVIA = [
    ("What planet is known as the Red Planet?", "mars"),
    ("How many sides does a hexagon have?", "6"),
    ("What is the largest ocean on Earth?", "pacific"),
    ("What game uses creepers, redstone, and diamonds?", "minecraft"),
    ("What color do you get by mixing blue and yellow?", "green"),
    ("How many days are in a leap year?", "366"),
    ("What is 9 x 9?", "81"),
    ("Which animal is known as man's best friend?", "dog"),
]


@bot.tree.command(name="trivia", description="Answer a quick trivia question")
async def trivia(interaction: discord.Interaction):
    question, answer = random.choice(TRIVIA)
    await interaction.response.send_message(
        f"🧠 **Trivia**\n{question}\n\nYou have **15 seconds**. Type your answer in chat!"
    )

    def check(message: discord.Message):
        return (
            message.author.id == interaction.user.id
            and message.channel.id == interaction.channel_id
        )

    try:
        message = await bot.wait_for("message", timeout=15.0, check=check)
    except asyncio.TimeoutError:
        record_result(interaction.user.id, False)
        await interaction.followup.send(f"⌛ Time! The answer was **{answer.title()}**.")
        return

    if message.content.strip().lower() == answer:
        reward = 100
        change_balance(interaction.user.id, reward)
        record_result(interaction.user.id, True)
        await interaction.followup.send(f"✅ Correct! **+{fmt(reward)}**")
    else:
        record_result(interaction.user.id, False)
        await interaction.followup.send(f"❌ Nope — the answer was **{answer.title()}**.")


BLACKTEA_SEQUENCES = [
    "ing", "tea", "ght", "str", "ark", "ent", "pro", "lim", "sta", "cha",
    "ion", "ter", "ate", "ous", "rea", "all", "ess", "com", "ver", "tri",
]


@bot.tree.command(name="blacktea", description="Black Tea: type a word containing the letters")
async def blacktea(interaction: discord.Interaction):
    sequence = random.choice(BLACKTEA_SEQUENCES)
    await interaction.response.send_message(
        f"☕ **BLACK TEA**\nType a real word containing **`{sequence}`**.\nYou have **12 seconds**!"
    )

    def check(message: discord.Message):
        return (
            message.author.id == interaction.user.id
            and message.channel.id == interaction.channel_id
            and sequence in message.content.lower()
            and message.content.strip().isalpha()
            and len(message.content.strip()) >= len(sequence) + 1
        )

    try:
        message = await bot.wait_for("message", timeout=12.0, check=check)
    except asyncio.TimeoutError:
        record_result(interaction.user.id, False)
        await interaction.followup.send("💀 Time's up. You spilled the tea.")
        return

    reward = 80
    change_balance(interaction.user.id, reward)
    record_result(interaction.user.id, True)
    await interaction.followup.send(
        f"☕ **{message.content.strip()}** works! **+{fmt(reward)}**"
    )


if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Add it to your environment variables or .env file.")

init_db()
bot.run(TOKEN)
